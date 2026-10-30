import io
import os
import pandas as pd
import streamlit as st
import folium
from folium.plugins import Fullscreen
from branca.element import MacroElement
from jinja2 import Template
import json
import math
import requests
from streamlit_folium import st_folium

st.set_page_config(page_title="IRUP Project Map", page_icon="🗺️", layout="wide")

st.title("🗺️ IRUP Project Mapping & Status Dashboard")
st.caption("Interactive map and filters powered by your IRUP SITELIST Excel sheet.")

DEFAULT_FILE = "IRUP TRACKER - 2026 OCTOBER 29.xlsx"

def load_tracker(uploaded_file):
    # The workbook has title/metadata rows above the actual headers.
    source = uploaded_file if uploaded_file is not None else DEFAULT_FILE
    if uploaded_file is None and not os.path.exists(DEFAULT_FILE):
        return None, "Upload your IRUP Tracker Excel file to get started."
    try:
        df = pd.read_excel(source, sheet_name="IRUP SITELIST", header=1)
    except Exception as exc:
        return None, f"Could not read the 'IRUP SITELIST' sheet: {exc}"

    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()

    # Remove repeated header rows and completely empty rows.
    # A row counts as a site if it has a SITE NO *or* a SITE NAME (some sites have no SITE NO yet).
    def _filled(col):
        if col not in df.columns:
            return pd.Series(False, index=df.index)
        return df[col].notna() & (df[col].astype(str).str.strip() != "")
    if "SITE NO" in df.columns:
        df = df[df["SITE NO"].astype(str).str.strip().str.upper() != "SITE NO"]
    df = df[_filled("SITE NO") | _filled("SITE NAME")]

    for col in ["LATITUDE", "LONGITUDE", "OVERALL PROGRESS", "DESIGN PROGRESS",
                "PERMITTING PROGESS", "PERMITTING PROGRESS", "EXTRACTION PROGRESS",
                "APPROX TONS", "DESIGN TONS", "TOTAL TONS EXTRACTED"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df, None

def clean_text(series):
    return series.fillna("(Blank)").astype(str).str.strip().replace("", "(Blank)")

uploaded = st.sidebar.file_uploader("Upload latest IRUP Tracker (.xlsx)", type=["xlsx"])
df, error = load_tracker(uploaded)
if error:
    st.info(error)
    st.stop()

st.sidebar.header("Filters")
filter_columns = [
    "AREA", "PROVINCE", "CITY", "QTR", "APM ASSIGNED",
    "OVERALL MILESTONE", "DESIGN STATUS", "PERMITTING GENERAL STAUS",
    "EXTRACTION STATUS", "STATUS"
]
filtered = df.copy()
active_filters = {}

for col in filter_columns:
    if col in filtered.columns:
        options = sorted(clean_text(filtered[col]).unique().tolist(), key=str.casefold)
        selected = st.sidebar.multiselect(col.replace("_", " ").title(), options, default=[])
        if selected:
            active_filters[col] = selected
            filtered = filtered[clean_text(filtered[col]).isin(selected)]

if "APPROX TONS" in filtered.columns:
    st.sidebar.divider()
    st.sidebar.caption("Optional approximate tons range")
    vals = filtered["APPROX TONS"].dropna()
    if not vals.empty and float(vals.min()) < float(vals.max()):
        low, high = st.sidebar.slider(
            "Approx. Tons", min_value=float(vals.min()), max_value=float(vals.max()),
            value=(float(vals.min()), float(vals.max()))
        )
        filtered = filtered[filtered["APPROX TONS"].between(low, high)]

# KPI row
total_sites = len(filtered)
mapped = filtered.dropna(subset=["LATITUDE", "LONGITUDE"]).copy() if {"LATITUDE", "LONGITUDE"}.issubset(filtered.columns) else filtered.iloc[0:0].copy()
progress = pd.to_numeric(filtered.get("OVERALL PROGRESS", pd.Series(dtype=float)), errors="coerce")
avg_progress = progress.mean()
approx_tons = pd.to_numeric(filtered.get("APPROX TONS", pd.Series(dtype=float)), errors="coerce").sum(min_count=1)
actual_tons = pd.to_numeric(filtered.get("TOTAL TONS EXTRACTED", pd.Series(dtype=float)), errors="coerce").sum(min_count=1)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Sites in Results", f"{total_sites:,}")
k2.metric("Sites with Coordinates", f"{len(mapped):,}")
k3.metric("Average Overall Progress", f"{avg_progress:.1%}" if pd.notna(avg_progress) else "N/A")
k4.metric("Approx. Tons", f"{approx_tons:,.1f}" if pd.notna(approx_tons) else "N/A")

# ---------------- Travel time & distance between two sites ----------------

def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def fmt_duration(seconds):
    minutes = int(round(seconds / 60))
    h, mnt = divmod(minutes, 60)
    return f"{h} hr {mnt} min" if h else f"{mnt} min"

@st.cache_data(show_spinner=False, ttl=3600)
def get_driving_route(lat1, lon1, lat2, lon2):
    """Road route from the free public OSRM server (no API key). Returns (route_dict, error_text)."""
    url = (f"https://router.project-osrm.org/route/v1/driving/"
           f"{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson")
    try:
        resp = requests.get(url, timeout=12, headers={"User-Agent": "IRUP-Project-Map"})
        data = resp.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return None, data.get("message") or data.get("code") or "No route found"
        r = data["routes"][0]
        return {"distance_km": r["distance"] / 1000.0, "duration_s": r["duration"],
                "coords": [(c[1], c[0]) for c in r["geometry"]["coordinates"]]}, None
    except Exception as exc:
        return None, str(exc)

route = None
route_points = None
_sites = mapped.copy()
for _c in ["LATITUDE", "LONGITUDE"]:
    _sites[_c] = pd.to_numeric(_sites[_c], errors="coerce")
_sites = _sites.dropna(subset=["LATITUDE", "LONGITUDE"])

with st.expander("🚗 Travel Time & Distance", expanded=False):
    if len(_sites) < 2:
        st.caption("Need at least two sites with coordinates in the current filter to calculate travel.")
    else:
        def _label(i, r):
            no = str(r.get("SITE NO", "")).strip()
            no = "" if no.lower() in ("nan", "none") else no
            name = str(r.get("SITE NAME", "Unnamed site")).strip()
            return f"{no} — {name}" if no else name
        labels = {i: _label(i, r) for i, r in _sites.iterrows()}
        ids = list(labels.keys())
        t1, t2 = st.columns(2)
        from_id = t1.selectbox("From site", ids, index=None, format_func=lambda i: labels[i],
                               placeholder="Choose starting site", key="route_from")
        to_id = t2.selectbox("To site", ids, index=None, format_func=lambda i: labels[i],
                             placeholder="Choose destination site", key="route_to")
        if from_id is not None and to_id is not None:
            if from_id == to_id:
                st.warning("Choose two different sites.")
            else:
                a, b = _sites.loc[from_id], _sites.loc[to_id]
                lat1, lon1, lat2, lon2 = float(a["LATITUDE"]), float(a["LONGITUDE"]), float(b["LATITUDE"]), float(b["LONGITUDE"])
                straight = haversine_km(lat1, lon1, lat2, lon2)
                with st.spinner("Calculating route..."):
                    route, route_err = get_driving_route(lat1, lon1, lat2, lon2)
                route_points = ((lat1, lon1), (lat2, lon2))
                m1, m2, m3 = st.columns(3)
                if route:
                    m1.metric("Driving distance", f"{route['distance_km']:,.1f} km")
                    m2.metric("Est. driving time", fmt_duration(route["duration_s"]))
                    m3.metric("Straight-line distance", f"{straight:,.1f} km")
                    st.caption("Road route from OpenStreetMap data (OSRM). Time is based on typical road speeds and "
                               "does not include traffic, stops, or ferry crossings.")
                else:
                    est_road = straight * 1.3
                    m1.metric("Straight-line distance", f"{straight:,.1f} km")
                    m2.metric("Rough road distance (est.)", f"{est_road:,.1f} km")
                    m3.metric("Rough driving time (est.)", fmt_duration(est_road / 40 * 3600))
                    st.warning(f"Could not get a road route ({route_err}). Showing a rough estimate: straight-line "
                               "distance x 1.3 at an average of 40 km/h. The sites may be on different islands, "
                               "or the routing service may be unreachable.")


st.subheader("Project Site Map")
map_height = st.slider("Map height (pixels)", min_value=600, max_value=1200, value=850, step=50)
st.caption("For an even larger view, use your browser's full-screen mode (F11).")

# Pin color per OVERALL MILESTONE (exact values from the Excel column).
MILESTONE_COLORS = {
    "NOT STARTED":          "#9E9E9E",  # gray
    "ON GOING SURVEY":      "#4FC3F7",  # light blue
    "ON GOING DESIGN":      "#1E88E5",  # blue
    "DESIGN COMPLETED":     "#3949AB",  # indigo
    "DESIGN SUBMITTED":     "#8E24AA",  # purple
    "DESIGN APPROVED":      "#00897B",  # teal
    "ON GOING PERMITTING":  "#FFB300",  # amber
    "READY FOR EXTRACTION": "#7CB342",  # light green
    "ON GOING EXTRACTION":  "#2E7D32",  # dark green
    "CANCELLED":            "#E53935",  # red
}
UNKNOWN_COLOR = "#212121"  # any milestone not listed above (or blank)

def milestone_key(value):
    if pd.isna(value):
        return ""
    return " ".join(str(value).upper().split())

def pin_color(value):
    return MILESTONE_COLORS.get(milestone_key(value), UNKNOWN_COLOR)

def make_pin(color):
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="26" height="36" viewBox="0 0 26 36">'
        f'<path d="M13 1C6.4 1 1 6.3 1 12.8c0 8.6 12 22.2 12 22.2s12-13.6 12-22.2C25 6.3 19.6 1 13 1z" '
        f'fill="{color}" stroke="#ffffff" stroke-width="2"/>'
        f'<circle cx="13" cy="12.8" r="4.5" fill="#ffffff" fill-opacity="0.9"/></svg>'
    )
    html = f'<div class="irup-pin">{svg}</div>'
    return folium.DivIcon(html=html, icon_size=(26, 36), icon_anchor=(13, 36), popup_anchor=(0, -32))

def fmt(value, percent=False):
    if pd.isna(value):
        return "N/A"
    try:
        if percent:
            n = float(value)
            return f"{n:.1%}" if abs(n) <= 1 else f"{n:.1f}%"
        return str(value)
    except Exception:
        return str(value)

class LegendControl(MacroElement):
    """Legend as a Leaflet control inside the map container, so it stays visible in full screen."""
    def __init__(self, html):
        super().__init__()
        self._html = json.dumps(html)
        self._template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
            var legend = L.control({position: "bottomleft"});
            legend.onAdd = function () {
                var div = L.DomUtil.create("div", "irup-legend");
                div.innerHTML = {{ this._html }};
                L.DomEvent.disableClickPropagation(div);
                L.DomEvent.disableScrollPropagation(div);
                return div;
            };
            legend.addTo({{ this._parent.get_name() }});
        })();
        {% endmacro %}
        """)

class PinZoomScaler(MacroElement):
    """Shrinks/grows the pins as the map is zoomed out/in."""
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function () {
            var map = {{ this._parent.get_name() }};
            function scalePins() {
                var f = Math.max(0.3, Math.min(1.2, 0.3 + (map.getZoom() - 5) * 0.17));
                document.documentElement.style.setProperty("--pin-scale", f);
            }
            map.on("zoomend", scalePins);
            scalePins();
        })();
        {% endmacro %}
    """)

PIN_CSS = "<style>.irup-pin{transform:scale(var(--pin-scale,0.64));transform-origin:50% 100%;}</style>"

def build_legend(counts):
    rows = ""
    for name, color in MILESTONE_COLORS.items():
        rows += (
            f'<div style="display:flex;align-items:center;margin:3px 0;">'
            f'<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
            f'background:{color};border:1px solid #fff;box-shadow:0 0 2px #555;margin-right:8px;"></span>'
            f'<span style="flex:1;">{name.title()}</span>'
            f'<span style="margin-left:10px;color:#666;">{counts.get(name, 0)}</span></div>'
        )
    if counts.get("OTHER", 0):
        rows += (
            f'<div style="display:flex;align-items:center;margin:3px 0;">'
            f'<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
            f'background:{UNKNOWN_COLOR};border:1px solid #fff;box-shadow:0 0 2px #555;margin-right:8px;"></span>'
            f'<span style="flex:1;">Other / Blank</span>'
            f'<span style="margin-left:10px;color:#666;">{counts["OTHER"]}</span></div>'
        )
    return (
        '<div style="background:rgba(255,255,255,0.95);'
        'padding:10px 14px;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,0.4);'
        'font-family:Arial,sans-serif;font-size:12px;color:#222;min-width:200px;">'
        '<div style="font-weight:bold;margin-bottom:6px;font-size:13px;">Overall Milestone</div>'
        f'{rows}</div>'
    )

if mapped.empty:
    st.warning("No sites with valid latitude/longitude in the current filter. Check the coordinates or relax the filters.")
else:
    mapped["LATITUDE"] = pd.to_numeric(mapped["LATITUDE"], errors="coerce")
    mapped["LONGITUDE"] = pd.to_numeric(mapped["LONGITUDE"], errors="coerce")
    mapped = mapped.dropna(subset=["LATITUDE", "LONGITUDE"])
    center = [mapped["LATITUDE"].mean(), mapped["LONGITUDE"].mean()]
    # Standard OpenStreetMap tiles only; no API key is required.
    m = folium.Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)

    # Individual pins added straight to the map (no clustering), so no numbered bubbles when zoomed out.
    legend_counts = {}
    for _, row in mapped.iterrows():
        site_no = row.get("SITE NO", "N/A")
        site_name = row.get("SITE NAME", "Unnamed site")
        milestone = row.get("OVERALL MILESTONE", "N/A")
        key = milestone_key(milestone)
        legend_counts[key if key in MILESTONE_COLORS else "OTHER"] = legend_counts.get(key if key in MILESTONE_COLORS else "OTHER", 0) + 1
        progress_value = fmt(row.get("OVERALL PROGRESS"), percent=True)
        popup_html = f"""
        <div style="font-family:Arial;min-width:220px">
          <b>{site_name}</b><br>
          <b>Site No:</b> {site_no}<br>
          <b>Area:</b> {row.get('AREA', 'N/A')}<br>
          <b>City/Province:</b> {row.get('CITY', 'N/A')}, {row.get('PROVINCE', 'N/A')}<br>
          <b>APM:</b> {row.get('APM ASSIGNED', 'N/A')}<br>
          <b>Overall Milestone:</b> {milestone}<br>
          <b>Overall Progress:</b> {progress_value}<br>
          <b>Approx. Tons:</b> {fmt(row.get('APPROX TONS'))}<br>
          <b>Design Tons:</b> {fmt(row.get('DESIGN TONS'))}<br>
          <b>Extraction Status:</b> {row.get('EXTRACTION STATUS', 'N/A')}
        </div>"""
        folium.Marker(
            location=[float(row["LATITUDE"]), float(row["LONGITUDE"])],
            icon=make_pin(pin_color(milestone)),
            popup=folium.Popup(popup_html, max_width=330),
            tooltip=f"{site_no} — {site_name}",
        ).add_to(m)

    # Permanent legend (always visible, shows all milestones with counts for the current filter).
    # Route line + fit map to the selected pair of sites.
    if route_points:
        if route:
            folium.PolyLine(route["coords"], color="#1565C0", weight=5, opacity=0.85).add_to(m)
        else:
            folium.PolyLine(list(route_points), color="#1565C0", weight=4, opacity=0.8, dash_array="8 8").add_to(m)
        pts = list(route_points) + (route["coords"] if route else [])
        m.fit_bounds([[min(p[0] for p in pts), min(p[1] for p in pts)],
                      [max(p[0] for p in pts), max(p[1] for p in pts)]], padding=(40, 40))

    LegendControl(build_legend(legend_counts)).add_to(m)

    # Pins shrink when zooming out and grow when zooming in.
    m.get_root().header.add_child(folium.Element(PIN_CSS))
    PinZoomScaler().add_to(m)

    # Full-screen button (top-right of the map).
    Fullscreen(position="topright", title="Full screen", title_cancel="Exit full screen",
               force_separate_button=True).add_to(m)
    st_folium(m, use_container_width=True, height=map_height, returned_objects=[])

st.divider()
summary_col1, summary_col2 = st.columns(2)
with summary_col1:
    st.subheader("Status Breakdown")
    if "OVERALL MILESTONE" in filtered.columns and not filtered.empty:
        counts = clean_text(filtered["OVERALL MILESTONE"]).value_counts().rename_axis("Overall Milestone").reset_index(name="Sites")
        st.dataframe(counts, use_container_width=True, hide_index=True, height=250)
with summary_col2:
    if "AREA" in filtered.columns and not filtered.empty:
        st.subheader("Sites by Area")
        area_counts = clean_text(filtered["AREA"]).value_counts().rename_axis("Area").reset_index(name="Sites")
        st.dataframe(area_counts, use_container_width=True, hide_index=True, height=250)
    st.metric("Total Tons Extracted", f"{actual_tons:,.1f}" if pd.notna(actual_tons) else "N/A")

st.divider()
st.subheader("Filtered Site List")
display_cols = [c for c in [
    "SITE NO", "SITE NAME", "AREA", "CITY", "PROVINCE", "QTR", "APM ASSIGNED",
    "OVERALL MILESTONE", "OVERALL PROGRESS", "DESIGN STATUS",
    "PERMITTING GENERAL STAUS", "EXTRACTION STATUS", "APPROX TONS",
    "DESIGN TONS", "TOTAL TONS EXTRACTED", "LATITUDE", "LONGITUDE"
] if c in filtered.columns]
st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True, height=420)

csv_data = filtered[display_cols].to_csv(index=False).encode("utf-8-sig")
st.download_button("Download filtered site list (CSV)", csv_data, "irup_filtered_sites.csv", "text/csv")

st.caption("Map tiles require an internet connection. The app filters the workbook you upload and does not edit the original Excel file.")

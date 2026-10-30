# IRUP Project Mapping & Status Dashboard

## What it does
- Reads the `IRUP SITELIST` sheet from the IRUP Tracker Excel workbook.
- Plots sites using `LATITUDE` and `LONGITUDE`.
- Shows site details when a map marker is clicked.
- Filters by Area, Province, City, Quarter, APM, Overall Milestone, Design Status, Permitting Status, Extraction Status, and Tracker Status.
- Travel Time & Distance: pick a From and To site to get driving distance and estimated time (free OSRM service, no API key) and see the route drawn on the map.
- Shows KPI cards, status breakdowns, a filtered site table, and CSV export.
- Uses standard OpenStreetMap tiles only; no map API key is required.

## How to run on Windows
1. Install Python 3.10 or newer from https://www.python.org/downloads/ (enable "Add Python to PATH" during installation).
2. Extract this ZIP to a normal folder, for example `Documents\IRUP_Project_Map`.
3. Double-click `RUN_APP.bat`.
4. Wait for the packages to install. Your browser should open the app. If not, open the URL shown in the terminal (usually http://localhost:8501).
5. Use the sidebar to upload your latest `IRUP TRACKER - YYYY MONTH DD.xlsx`.

## Important notes
- Internet is needed for OpenStreetMap tiles and first-time package installation. The map uses OpenStreetMap only and does not require a Google Maps or CartoDB API key.
- The app reads the workbook; it does not write changes back to Excel.
- This is an initial MVP. Confirm the status color rules and any milestone/progress conventions before relying on them for formal reporting.
- Keep the Excel workbook structure and sheet name `IRUP SITELIST` unchanged for best results.

@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py
) else (
  set PY=python
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package installation failed. Check your internet connection and Python installation.
  pause
  exit /b 1
)
%PY% -m streamlit run app.py
pause

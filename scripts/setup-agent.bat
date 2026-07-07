@echo off
cd /d "%~dp0.."
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m pip install -r backend\requirements.txt
) else (
  python -m pip install -r backend\requirements.txt
)

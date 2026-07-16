@echo off
cd /d "%~dp0.."
if "%AGENT_HOST%"=="" set AGENT_HOST=127.0.0.1
if "%AGENT_PORT%"=="" set AGENT_PORT=0
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m backend.server
) else (
  python -m backend.server
)

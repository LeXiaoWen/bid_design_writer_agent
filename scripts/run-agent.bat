@echo off
cd /d "%~dp0.."
if "%AGENT_HOST%"=="" set AGENT_HOST=127.0.0.1
if "%AGENT_PORT%"=="" set AGENT_PORT=8765
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m uvicorn backend.main:app --host %AGENT_HOST% --port %AGENT_PORT% --reload
) else (
  python -m uvicorn backend.main:app --host %AGENT_HOST% --port %AGENT_PORT% --reload
)

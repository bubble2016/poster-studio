@echo off
setlocal

cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"
set "URL=http://127.0.0.1:5173"

if not exist "%VENV_PY%" (
    echo [1/3] Creating virtual environment...
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -m venv .venv
    )
    if errorlevel 1 goto :error
)

echo [2/3] Installing/checking dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] Starting Poster Studio...
echo Open: %URL%
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process '%URL%'"

"%VENV_PY%" app.py
if errorlevel 1 goto :error

goto :end

:error
echo.
echo Startup failed. Please check the messages above.
pause
exit /b 1

:end
endlocal

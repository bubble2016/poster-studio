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

echo [2/3] Checking dependencies...
"%VENV_PY%" -c "import hashlib,pathlib,sys; req=pathlib.Path('requirements.txt'); stamp=pathlib.Path('.venv/requirements.sha256'); h=hashlib.sha256(req.read_bytes()).hexdigest(); sys.exit(0 if stamp.exists() and stamp.read_text().strip()==h else 1)"
if errorlevel 1 (
    echo Requirements changed, installing dependencies...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
    "%VENV_PY%" -c "import hashlib,pathlib; req=pathlib.Path('requirements.txt'); stamp=pathlib.Path('.venv/requirements.sha256'); stamp.write_text(hashlib.sha256(req.read_bytes()).hexdigest(), encoding='utf-8')"
    if errorlevel 1 goto :error
) else (
    echo Dependencies unchanged, skipping install.
)

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

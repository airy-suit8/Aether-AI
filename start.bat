@echo off
setlocal
REM Starts Aether AI for development on Windows:
REM   backend  (FastAPI)   http://localhost:8000
REM   frontend (React/Vite) http://localhost:5173  <- open this one
REM First-time setup is described in README.md.
REM
REM   start.bat                  install what changed, then start both servers
REM   start.bat --packages-only  install what changed, start nothing

cd /d "%~dp0"

REM Use the project virtual environment if it exists, otherwise whatever "python" is on PATH.
REM PYTHON, when set, names another interpreter.
if not defined PYTHON (
    if exist "%~dp0.venv\Scripts\python.exe" (
        set "PYTHON=%~dp0.venv\Scripts\python.exe"
        set "OWN_VENV=1"
    ) else (
        echo No .venv found in the project folder; using "python" from PATH.
        set "PYTHON=python"
    )
)

if not exist "%~dp0backend\.env" (
    echo backend\.env is missing. Copy backend\.env.example to backend\.env and fill it in.
    echo See README.md, step 3.
    pause
    exit /b 1
)

REM Packages are installed again when their list changed since the last install (a pull or a merge
REM that adds a package), not only on the first run: a copy of each list, as last installed, is kept
REM beside the packages and compared. Python packages are installed only into the project's .venv.
if exist "%~dp0frontend\node_modules\.aether-installed-lock" (
    fc /b "%~dp0frontend\package-lock.json" "%~dp0frontend\node_modules\.aether-installed-lock" >nul 2>&1 || set "FRONTEND_INSTALL=1"
) else (
    set "FRONTEND_INSTALL=1"
)
if defined FRONTEND_INSTALL (
    echo Installing frontend packages ^(first run, or package-lock.json changed^)...
    pushd "%~dp0frontend"
    call npm ci
    if errorlevel 1 (
        popd
        echo npm ci failed. Close the "Aether AI frontend" window if it is open, then run start.bat again.
        pause
        exit /b 1
    )
    copy /y package-lock.json node_modules\.aether-installed-lock >nul
    popd
)

if defined OWN_VENV (
    if exist "%~dp0.venv\.aether-installed-requirements" (
        fc /b "%~dp0backend\requirements.txt" "%~dp0.venv\.aether-installed-requirements" >nul 2>&1 || set "BACKEND_INSTALL=1"
    ) else (
        set "BACKEND_INSTALL=1"
    )
)
if defined BACKEND_INSTALL (
    echo Installing backend packages ^(first run, or backend\requirements.txt changed^)...
    call "%PYTHON%" -m pip install -r "%~dp0backend\requirements.txt"
    if errorlevel 1 (
        echo pip install failed. Close the "Aether AI backend" window if it is open, then run start.bat again.
        pause
        exit /b 1
    )
    copy /y "%~dp0backend\requirements.txt" "%~dp0.venv\.aether-installed-requirements" >nul
)

if /i "%~1"=="--packages-only" (
    echo Packages are up to date.
    exit /b 0
)

echo Starting backend on http://localhost:8000 ...
start "Aether AI backend" /D "%~dp0backend" cmd /k ""%PYTHON%" -m uvicorn main:app --port 8000"

echo Starting frontend on http://localhost:5173 ...
start "Aether AI frontend" /D "%~dp0frontend" cmd /k "npm run dev"

echo.
echo Open http://localhost:5173 in your browser.
echo To stop, close the two windows titled "Aether AI backend" and "Aether AI frontend".

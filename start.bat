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
REM AETHER_PYTHON, when set, names another interpreter, and the backend's packages are installed
REM into it. A PYTHON variable already set on the computer is not used: on the owner's it names a
REM folder, not a program. The names below start empty, whatever the environment holds.
set "PY_EXE="
set "OWN_VENV="
set "FRONTEND_INSTALL="
set "BACKEND_INSTALL="
if defined AETHER_PYTHON (
    set "PY_EXE=%AETHER_PYTHON%"
    set "OWN_VENV=1"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
    set "OWN_VENV=1"
) else (
    echo No .venv found in the project folder; using "python" from PATH.
    set "PY_EXE=python"
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
    call "%PY_EXE%" -m pip install -r "%~dp0backend\requirements.txt"
    if errorlevel 1 (
        echo pip install failed. Close the "Aether AI backend" window if it is open, then run start.bat again.
        pause
        exit /b 1
    )
    REM Kept in the project .venv; with AETHER_PYTHON and no .venv, the list is checked again each start
    if exist "%~dp0.venv\" copy /y "%~dp0backend\requirements.txt" "%~dp0.venv\.aether-installed-requirements" >nul
)

if /i "%~1"=="--packages-only" (
    echo Packages are up to date.
    exit /b 0
)

REM Ollama, when the settings use it (backend\.env), must answer before questions can be: after a
REM restart it is not running unless it starts with Windows, so it is started here. The settings
REM decide, as the app reads them (backend\src\ollama_ready.py); one on another computer is left alone.
pushd "%~dp0backend"
call "%PY_EXE%" -m src.ollama_ready
if errorlevel 3 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
        echo Starting Ollama ...
        start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
    ) else (
        where ollama >nul 2>&1 && (
            echo Starting Ollama ...
            start "Ollama" /min ollama serve
        )
    )
    call "%PY_EXE%" -m src.ollama_ready --wait 30
    if errorlevel 3 echo Ollama did not start. Start it from the Start menu; questions are answered once it runs.
)
popd

echo Starting backend on http://localhost:8000 ...
start "Aether AI backend" /D "%~dp0backend" cmd /k ""%PY_EXE%" -m uvicorn main:app --port 8000"

echo Starting frontend on http://localhost:5173 ...
start "Aether AI frontend" /D "%~dp0frontend" cmd /k "npm run dev"

echo.
echo Open http://localhost:5173 in your browser.
echo To stop, close the two windows titled "Aether AI backend" and "Aether AI frontend".

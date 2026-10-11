@echo off
setlocal
REM Starts Aether AI for development on Windows:
REM   backend  (FastAPI)   http://localhost:8000
REM   frontend (React/Vite) http://localhost:5173  <- open this one
REM First-time setup is described in README.md.

cd /d "%~dp0"

REM Use the project virtual environment if it exists, otherwise whatever "python" is on PATH.
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    echo No .venv found in the project folder; using "python" from PATH.
    set "PYTHON=python"
)

if not exist "%~dp0backend\.env" (
    echo backend\.env is missing. Copy backend\.env.example to backend\.env and fill it in.
    echo See README.md, step 3.
    pause
    exit /b 1
)

if not exist "%~dp0frontend\node_modules" (
    echo Installing frontend packages ^(first run only^)...
    pushd "%~dp0frontend"
    call npm ci
    popd
)

echo Starting backend on http://localhost:8000 ...
start "Aether AI backend" /D "%~dp0backend" cmd /k ""%PYTHON%" -m uvicorn main:app --port 8000"

echo Starting frontend on http://localhost:5173 ...
start "Aether AI frontend" /D "%~dp0frontend" cmd /k "npm run dev"

echo.
echo Open http://localhost:5173 in your browser.
echo To stop, close the two windows titled "Aether AI backend" and "Aether AI frontend".
pause

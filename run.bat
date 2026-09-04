@echo off
REM MathTalk - one-click launcher (Windows).
REM Checks runtime/dependencies, starts backend + frontend, opens the browser.
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "ROOT=%CD%"
set "BACKEND_DIR=%ROOT%\backend"
set "FRONTEND_DIR=%ROOT%\frontend"

echo [MathTalk] Checking runtime...

where python >nul 2>nul
if errorlevel 1 (
  echo [MathTalk] ERROR: Python is not on PATH. Install Python 3.10+ and re-run.
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [MathTalk] ERROR: Node.js is not on PATH.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [MathTalk] ERROR: npm is not on PATH.
  exit /b 1
)

echo [MathTalk] Checking dependencies...
if not exist "%BACKEND_DIR%\.venv" (
  echo [MathTalk] Creating backend virtualenv...
  python -m venv "%BACKEND_DIR%\.venv"
)
if not exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
  echo [MathTalk] ERROR: virtualenv creation failed.
  exit /b 1
)
"%BACKEND_DIR%\.venv\Scripts\python.exe" -c "import fastapi, sympy, httpx" >nul 2>nul
if errorlevel 1 (
  echo [MathTalk] Installing backend dependencies...
  "%BACKEND_DIR%\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
  "%BACKEND_DIR%\.venv\Scripts\python.exe" -m pip install -q -r "%BACKEND_DIR%\requirements.txt"
)
if not exist "%FRONTEND_DIR%\node_modules" (
  echo [MathTalk] Installing frontend dependencies...
  pushd "%FRONTEND_DIR%"
  call npm install --no-fund --no-audit
  popd
)

echo [MathTalk] Starting backend on http://127.0.0.1:8020 ...
start "MathTalk Backend" cmd /c "cd /d %BACKEND_DIR% && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8020 --log-level info"

echo [MathTalk] Waiting for backend health...
set /a tries=0
:wait_health
powershell -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8020/api/health).StatusCode } catch { 0 }" >"%TEMP%\mt_health.txt"
set /p health=<"%TEMP%\mt_health.txt"
if "%health%"=="200" goto health_ok
set /a tries+=1
if %tries% GEQ 60 (
  echo [MathTalk] ERROR: backend did not become healthy. Check the backend window.
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_health
:health_ok

echo [MathTalk] Starting frontend on http://127.0.0.1:5173 ...
start "MathTalk Frontend" cmd /c "cd /d %FRONTEND_DIR% && npm run dev"

set /a tries=0
:wait_front
powershell -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:5173).StatusCode } catch { 0 }" >"%TEMP%\mt_front.txt"
set /p front=<"%TEMP%\mt_front.txt"
if "%front%"=="200" goto front_ok
set /a tries+=1
if %tries% GEQ 60 (
  echo [MathTalk] ERROR: frontend did not become ready.
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_front
:front_ok

echo [MathTalk] Opening browser...
start "" http://127.0.0.1:5173
echo [MathTalk] MathTalk is running at http://127.0.0.1:5173
echo [MathTalk] Voice-first: click "Start with microphone", then say: Practice, Algebra, Linear Equations, Easy.
echo [MathTalk] Demo reset: reset-demo.bat
pause

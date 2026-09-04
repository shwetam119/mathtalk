@echo off
REM MathTalk - demo reset (Windows).
setlocal
cd /d "%~dp0"

set "BACKEND_URL=http://127.0.0.1:8000"
set "STUDENT=demo-student-001"

echo [MathTalk] Resetting demo learner %STUDENT% ...
powershell -Command "try { Invoke-RestMethod -Method Post -Uri '%BACKEND_URL%/api/demo/reset' -ContentType 'application/json' -Body '{\"student_id\": \"%STUDENT%\"}' | Out-Null; Write-Output 'API reset done.' } catch { Write-Output 'Backend not running - skipping API reset.' }"

if exist "%CD%\backend\data\memory_local.json" del "%CD%\backend\data\memory_local.json"
if exist "%CD%\backend\data\session_counters.json" del "%CD%\backend\data\session_counters.json"

echo [MathTalk] Demo reset complete. Run run.bat to start Session 1 again.

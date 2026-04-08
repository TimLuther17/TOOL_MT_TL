@echo off
setlocal

set "ROOT=C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass"
set "API_URL=http://127.0.0.1:8000/api/options"

echo [1/4] Starte API in neuem Fenster...
start "TOOL API" cmd /k "cd /d %ROOT% && call .venv\Scripts\activate.bat && python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload"

echo [2/4] Pruefe npm...
where npm >nul 2>nul
if errorlevel 1 (
  echo WARNUNG: npm wurde nicht gefunden. Frontend wird nicht gestartet.
  echo Bitte Node.js installieren und danach erneut ausfuehren.
  goto healthcheck
)

echo [3/4] Starte Frontend in neuem Fenster...
start "TOOL Frontend" cmd /k "cd /d %ROOT%\Frontend && npm run dev"

:healthcheck
echo [4/4] Fuehre Health-Check fuer %API_URL% aus...
set "ok=0"
for /L %%i in (1,1,25) do (
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing '%API_URL%'; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
  if not errorlevel 1 (
    set "ok=1"
    goto done
  )
  timeout /t 1 /nobreak >nul
)

:done
if "%ok%"=="1" (
  echo OK: API erreichbar unter %API_URL%
) else (
  echo FEHLER: API-Health-Check fehlgeschlagen.
  echo Bitte API-Fenster auf Fehlermeldungen pruefen.
)

echo.
echo Fertig.
pause
endlocal

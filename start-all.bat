@echo off
title DataBrain Starter
echo ========================================
echo  DataBrain - Starting all services
echo ========================================
echo [1/3] Starting backend (port 8502)...
start "DataBrain-Backend" /min "python-3.12.3-embed-amd64\python.exe" "backend\main.py"
echo      Waiting for backend...
timeout /t 5 /nobreak >nul
echo [2/3] Starting frontend nginx (port 80)...
pushd nginx-1.30.4
start "" nginx.exe
popd
echo [3/3] Opening browser...
timeout /t 2 /nobreak >nul
start http://localhost
echo.
echo Done! Visit http://localhost  (Stop with stop.bat)
pause

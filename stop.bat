@echo off
cd .\nginx-1.30.4\
chcp 65001>null
nginx.exe -s stop
taskkill /f /im nginx.exe 2>nul
taskkill /f /im python.exe 2>nul
echo 停止成功
pause
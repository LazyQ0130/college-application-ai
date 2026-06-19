@echo off
cd /d "%~dp0"
echo Starting Snowpeak College Application Assistant...
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8766/'"
py -3 server.py || python server.py
pause

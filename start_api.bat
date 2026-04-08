@echo off
cd /d C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass
call .venv\Scripts\activate.bat
python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 --reload
pause

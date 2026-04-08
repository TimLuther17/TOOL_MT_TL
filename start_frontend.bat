@echo off
cd /d C:\Users\Luther\PycharmProjects\TOOL_GTFS_Overpass\Frontend
if exist ..\.venv\Scripts\activate.bat call ..\.venv\Scripts\activate.bat
echo Install frontend deps first: npm install
echo Then start UI: npm run dev
cmd /k

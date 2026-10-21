@echo off
REM Builds dist\CloudWatchLogSearch.exe  (run on a Windows PC with Python 3.10+ installed)
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name CloudWatchLogSearch --add-data "config.yaml;." desktop.py
echo.
echo Done: dist\CloudWatchLogSearch.exe
pause

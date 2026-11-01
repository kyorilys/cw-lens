@echo off
REM Builds dist\cw-lens.exe  (run on a Windows PC with Python 3.10+ installed)
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name cw-lens --add-data "config.yaml;." --add-data "ui;ui" webapp.py
echo.
echo Done: dist\cw-lens.exe
pause

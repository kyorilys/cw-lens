#!/bin/sh
# Builds dist/cw-lens.app  (run on a Mac with Python 3.10+ from python.org)
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --windowed --name cw-lens --add-data "config.yaml:." --add-data "ui:ui" webapp.py
echo "Done: dist/cw-lens.app"

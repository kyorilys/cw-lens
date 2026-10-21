#!/bin/sh
# Builds dist/CloudWatchLogSearch.app  (run on a Mac with Python 3.10+ from python.org)
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --windowed --name CloudWatchLogSearch --add-data "config.yaml:." desktop.py
echo "Done: dist/CloudWatchLogSearch.app"

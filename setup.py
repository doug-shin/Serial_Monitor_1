#!/usr/bin/env python3
"""
SM1 - Serial Monitor v0.75 Setup Script
Simple PyInstaller build configuration (OS별 add-data 자동 구분자 처리)
"""

try:
    import PyInstaller.__main__ as PYI
except Exception:
    # 일부 환경에서 소문자 모듈명이 import 가능한 경우 대비
    import pyinstaller.__main__ as PYI  # type: ignore
import sys
import os

def build_app():
    """Build the Serial Monitor application"""
    
    # OS별 add-data 구분자
    data_sep = ';' if sys.platform == 'win32' else ':'
    add_data = f"--add-data=serial_monitor_icon.png{data_sep}."

    out_name = 'SM1_v0.75'
    icon_opt = '--icon=serial_monitor_icon.ico' if sys.platform == 'win32' else '--icon=serial_monitor_icon.icns'

    # PyInstaller arguments
    args = [
        'sm1.py',
        '--onefile',                    # Single executable file
        '--windowed',                   # No console window (GUI app)
        f'--name={out_name}',           # Output name
        icon_opt,
        add_data,                       # Include icon in bundle
        '--clean',                      # Clean cache
        '--noconfirm',                  # Overwrite without confirmation
    ]
    
    print("Building SM1 - Serial Monitor v0.75...")
    print(f"Platform: {sys.platform}")
    print(f"Arguments: {' '.join(args)}")
    
    PYI.run(args)
    
    print("\nBuild completed!")
    print("Executable location:")
    if sys.platform == 'win32':
        print("  dist/SM1_v0.75.exe")
    elif sys.platform == 'darwin':
        print("  dist/SM1_v0.75")
    else:
        print("  dist/SM1_v0.75")

if __name__ == '__main__':
    build_app()
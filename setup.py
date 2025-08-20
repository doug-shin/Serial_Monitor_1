#!/usr/bin/env python3
"""
SM1 - Serial Monitor v0.6 Setup Script
Simple PyInstaller build configuration
"""

import PyInstaller.__main__
import sys
import os

def build_app():
    """Build the Serial Monitor application"""
    
    # PyInstaller arguments
    args = [
        'sm1.py',
        '--onefile',                    # Single executable file
        '--windowed',                   # No console window (GUI app)
        '--name=SM1_v0.6',              # Output name
        '--icon=serial_monitor_icon.ico' if sys.platform == 'win32' else '--icon=serial_monitor_icon.icns',
        '--add-data=serial_monitor_icon.png:.',  # Include icon in bundle
        '--clean',                      # Clean cache
        '--noconfirm',                  # Overwrite without confirmation
    ]
    
    print("Building SM1 - Serial Monitor v0.6...")
    print(f"Platform: {sys.platform}")
    print(f"Arguments: {' '.join(args)}")
    
    PyInstaller.__main__.run(args)
    
    print("\nBuild completed!")
    print("Executable location:")
    if sys.platform == 'win32':
        print("  dist/SM1_v0.6.exe")
    elif sys.platform == 'darwin':
        print("  dist/SM1_v0.6")
    else:
        print("  dist/SM1_v0.6")

if __name__ == '__main__':
    build_app()
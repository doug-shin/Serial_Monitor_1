#!/bin/bash
# Simple build script for macOS/Linux

echo "=== SM1 - Serial Monitor v0.5 Build Script ==="

# Check if Python and required packages are installed
python3 -c "import PyQt5, pyserial, PyInstaller" 2>/dev/null || {
    echo "Error: Required packages not installed"
    echo "Run: pip3 install -r requirements.txt"
    exit 1
}

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ *.spec

# Run build
echo "Building application..."
python3 setup.py

echo "Build complete!"
ls -la dist/
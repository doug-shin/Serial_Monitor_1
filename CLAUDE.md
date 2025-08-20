# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SM1 is a PyQt5-based serial monitor application that provides bidirectional communication between a SCADA system and Master controller using a custom binary protocol over RS232/USB-Serial interfaces. The application manages multiple slave modules (up to 31) and provides real-time monitoring of system voltage, individual module currents, and temperatures.

## Essential Commands

### Development
```bash
# Install dependencies
pip3 install -r requirements.txt

# Run the main application
python3 sm1.py

# Run protocol test sender (simulates Master->SCADA data)
python3 test.py
```

### Building
```bash
# Build executable (cross-platform)
./build.sh
# or
python3 setup.py

# Manual PyInstaller build
pyinstaller --onefile --windowed --name=SM1_v0.6 sm1.py
```

## Architecture Overview

### Core Components

**SerialWorker (QObject)**
- Handles background serial I/O in separate QThread
- Implements binary protocol parsing with STX/ETX frame detection
- Manages checksum validation and error handling
- Emits signals for system voltage and slave data updates

**SerialMonitorApp (QMainWindow)**
- Main GUI application with real-time data display
- Manages connection state and UI updates
- Handles bidirectional protocol communication
- Provides module management (add/remove/reset)

### Binary Protocol Architecture

The application implements a dual-direction binary protocol:

**Master → SCADA (7 bytes)**
- System voltage (ID=0): `STX|ID|Voltage/10|Reserved|Checksum|ETX`
- Slave data (ID≠0): `STX|ID+DAB_OK|Current/100|Temp*2|Checksum|ETX`

**SCADA → Master (9 bytes)**
- Control commands: `STX|Command|MaxV|MinV|Current|Checksum|ETX`
- Command 0x00=Stop, 0x01=Start

### Threading Model

The application uses PyQt5's signal-slot mechanism with QThread:
- Main thread: GUI updates and user interactions
- Serial thread: Continuous data reading and protocol parsing
- Thread-safe communication via pyqtSignal emissions

### Data Flow

1. **Connection**: Auto-detects USB-to-Serial ports, establishes connection
2. **Receive**: Background thread reads serial data, parses binary frames
3. **Parse**: Validates checksums, extracts data based on frame type (system/slave)
4. **Display**: Updates GUI tables and system indicators via Qt signals
5. **Control**: User commands generate binary frames sent to serial port

## Protocol Implementation Details

### Frame Detection
- Uses STX (0x02) and ETX (0x03) markers for frame boundaries
- Implements buffer management for partial frame handling
- 7-byte frames for Master→SCADA, 9-byte frames for SCADA→Master

### Data Scaling
- System voltage: int16 with ÷10 scaling (3000 = 300.0V)
- Slave current: int16 with ÷100 scaling (-8000 = -80.00A) 
- Temperature: uint8 with ×0.5 scaling (50 = 25.0°C)
- All multi-byte values use big-endian format

### Error Handling
- Checksum validation (configurable ON/OFF)
- Serial port error recovery with automatic reconnection
- Frame parsing error detection and logging
- UI state management during connection failures

## Testing

The `test.py` file provides a protocol test sender that simulates Master→SCADA communication:
- Generates realistic test data for system voltage and 10 slave modules
- Implements proper binary protocol formatting with checksums
- Useful for testing protocol parsing without hardware Master device

## Module Management

- Initial state: 10 modules (ID 1-10) with zero values
- Dynamic add/remove: Up to 31 modules (5-bit ID field limit)
- Reset functionality: Returns to initial 10-module state
- Real-time current summation for system current display
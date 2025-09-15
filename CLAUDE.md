# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SM1 v0.7 is a PyQt5-based dual-channel serial monitor application that provides bidirectional communication between a SCADA system and Master controller using a custom binary protocol (v2.0) over RS232/USB-Serial interfaces. The application supports advanced 2-channel operation with Independent/Parallel modes, manages multiple slave modules (up to 31 per channel), and provides real-time monitoring of system voltage, individual module currents, and temperatures.

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
pyinstaller --onefile --windowed --name=SM1_v0.7 sm1.py
```

## Architecture Overview

### Core Components

**SerialWorker (QObject)**
- Handles background serial I/O in separate QThread per channel
- Implements binary protocol parsing with STX/ETX frame detection
- Manages checksum validation and error handling with statistics tracking
- Emits channel-aware signals for system voltage and slave data updates
- Supports dual-channel operation with independent serial connections

**SerialMonitorApp (QMainWindow)**
- Main GUI application with real-time dual-channel data display
- Manages connection state and UI updates for both channels
- Handles bidirectional protocol communication per channel
- Provides module management (add/remove/reset) per channel
- Supports channel mode switching (1CH ↔ 2CH) and operation modes (Independent/Parallel)

### Binary Protocol Architecture (v2.0)

The application implements a dual-direction binary protocol with enhanced scaling:

**Master → SCADA (7 bytes)**
- System voltage (ID=0): `STX|ID+Channel|Voltage/10|Reserved|Checksum|ETX`
- Slave data (ID≠0): `STX|ID+DAB_OK|Current_uint16_center32768/100|Temp*2|Checksum|ETX`

**SCADA → Master (10 bytes)**
- Control commands: `STX|Command|MaxV|MinV|Current_uint16_center32768/10|Reserved|Checksum|ETX`
- Command bit[0]=Start/Stop, bit[2:1]=Operation Mode (0=Stop, 1=Independent, 2=Parallel)
- Enhanced with voltage range controls and improved current scaling

### Threading Model

The application uses PyQt5's signal-slot mechanism with QThread:
- Main thread: GUI updates and user interactions
- Serial thread per channel: Continuous data reading and protocol parsing
- Thread-safe communication via pyqtSignal emissions with channel identification
- Atomic state transitions for channel mode switching

### Data Flow (2-Channel)

1. **Connection**: Auto-detects USB-to-Serial ports, establishes per-channel connections
2. **Receive**: Background threads read serial data per channel, parse binary frames
3. **Parse**: Validates checksums, extracts data based on frame type (system/slave) per channel
4. **Display**: Updates GUI tables and system indicators via Qt signals with channel routing
5. **Control**: User commands generate binary frames sent to appropriate serial port(s) based on operation mode

## Protocol Implementation Details (v2.0)

### Frame Detection
- Uses STX (0x02) and ETX (0x03) markers for frame boundaries
- Implements buffer management for partial frame handling
- 7-byte frames for Master→SCADA, 10-byte frames for SCADA→Master (enhanced from v1.0)

### Enhanced Data Scaling (v2.0)
- System voltage: uint16 with ÷10 scaling (3000 = 300.0V)
- Slave current: uint16 center-offset with ÷100 scaling (32768+8000 = 80.00A, 32768-8000 = -80.00A)
- Current command: uint16 center-offset with ÷10 scaling (32768+800 = 80.0A, 32768-800 = -80.0A)
- Temperature: uint8 with ×0.5 scaling (50 = 25.0°C)
- Voltage range: uint16 with ÷10 scaling for MaxV/MinV parameters
- All multi-byte values use big-endian format

### Error Handling & Statistics
- Checksum validation (configurable ON/OFF per channel)
- Serial port error recovery with automatic reconnection per channel
- Frame parsing error detection and logging with channel identification
- UI state management during connection failures
- Checksum error statistics tracking and rate monitoring per channel
- Automatic alerting for excessive error rates

## Testing

The `test.py` file provides a protocol test sender that simulates Master→SCADA communication:
- Generates realistic test data for system voltage and 10 slave modules
- Implements proper binary protocol formatting with checksums
- Useful for testing protocol parsing without hardware Master device
- Supports protocol v2.0 with enhanced scaling factors

## 2-Channel Operation

### Channel Modes
- **1CH Mode**: Single channel operation (traditional mode)
  - Uses only CH1 interface
  - Window size: 820×850 pixels
  - Standard single-channel workflow

- **2CH Mode**: Dual channel operation with independent serial connections
  - Uses both CH1 and CH2 interfaces
  - Window size: 1640×850 pixels (automatic resize)
  - Supports Independent and Parallel operation modes

### Operation Modes (2CH only)
- **Independent Mode**: Each channel operates independently
  - Separate control commands per channel
  - Independent voltage/current settings
  - Full control interface for both channels
  - Ideal for different systems or redundant operation

- **Parallel Mode**: Coordinated dual-channel operation
  - CH1 sends commands for both channels
  - CH2 provides feedback and monitoring only
  - CH2 control interface automatically disabled
  - Single point of control with dual monitoring
  - Ideal for synchronized operation

### UI Features
- **Channel Toggle**: Dynamic 1CH ↔ 2CH mode switching
  - Automatic window resizing with performance optimization
  - State preservation during transitions
  - Atomic operation with rollback capability

- **Operation Mode Toggle**: Independent ↔ Parallel (2CH mode only)
  - Real-time control interface adaptation
  - Automatic CH2 control disabling in Parallel mode
  - Visual indicators for current operation mode

### Connection Management
- Independent serial port selection per channel
- Concurrent connection handling for both channels
- Per-channel connection status and error monitoring
- Automatic reconnection with channel-specific retry logic

## Module Management (Per Channel)

- **Initial State**: 10 modules (ID 1-10) with zero values per channel
- **Dynamic Management**: Add/remove up to 31 modules per channel (5-bit ID field limit)
- **Reset Functionality**: Returns to initial 10-module state per channel
- **Real-time Calculation**: Current summation for system current display per channel
- **Channel Independence**: Module configurations maintained separately per channel

## Performance Optimizations

### UI Responsiveness
- Signal rate limiting with batch processing
- Dynamic resize timing optimization
- Efficient widget management for dual-channel display
- Memory-conscious buffer management per channel

### Threading Efficiency
- Per-channel worker threads for parallel processing
- Optimized signal-slot connections
- Thread-safe data structures
- Graceful shutdown with proper resource cleanup

## Command Protocol (v2.0 Enhancement)

### Enhanced Command Structure
```
SCADA → Master: STX|Command|MaxV|MinV|Current|Reserved|Checksum|ETX
- Command: bit[0]=Start/Stop, bit[2:1]=Operation Mode
- MaxV/MinV: Voltage range limits (÷10 scaling)
- Current: Target current (center-offset ÷10 scaling)
- Enhanced safety with voltage range validation
```

### Operation Mode Encoding
- `0x00`: Stop mode (all channels)
- `0x01`: Start + Independent mode
- `0x03`: Start + Parallel mode
- Automatic mode selection based on UI configuration

## Error Recovery & Monitoring

### Advanced Error Tracking
- Per-channel checksum error statistics
- Error rate monitoring with configurable thresholds
- Automatic alerting for communication issues
- Connection state recovery with backoff strategies

### Quality Metrics
- Packet reception rate tracking
- Checksum success rate monitoring
- Connection stability metrics
- Performance diagnostics per channel

## Development Guidelines

### Code Organization
- Channel-aware data structures throughout
- Consistent naming conventions for dual-channel operations
- Modular design supporting easy channel addition
- Clean separation between UI and protocol layers

### Threading Best Practices
- Use pyqtSignal for all cross-thread communication
- Implement proper resource cleanup in worker destructors
- Maintain thread safety in shared data structures
- Use atomic operations for critical state transitions

### Protocol Implementation
- Validate all frame structures before processing
- Implement robust error handling for malformed data
- Use proper scaling factors as defined in protocol v2.0
- Maintain backwards compatibility where possible

## Testing Strategy

### Unit Testing
- Protocol parsing validation
- Data scaling accuracy verification
- Channel switching logic validation
- Error handling robustness testing

### Integration Testing
- Dual-channel operation validation
- Mode switching functionality
- Serial communication reliability
- UI responsiveness under load

### Performance Testing
- Multi-channel data throughput
- UI rendering performance with large datasets
- Memory usage optimization
- Connection recovery timing
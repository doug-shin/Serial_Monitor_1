#!/usr/bin/env python3
"""
새 바이너리 프로토콜 테스트 송신기
Master -> SCADA 프로토콜 시뮬레이션
"""

import serial
import time
import struct
import random
import sys

class BinaryProtocolSender:
    def __init__(self, port, baud=38400):
        self.port = port
        self.baud = baud
        self.serial = None
        
    def connect(self):
        """시리얼 포트 연결"""
        try:
            self.serial = serial.Serial(self.port, self.baud)
            print(f"Connected to {self.port} at {self.baud} baud")
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False
            
    def calculate_checksum(self, data):
        """체크섬 계산 (바이트 1~4의 합)"""
        return sum(data[1:5]) & 0xFF
        
    def send_system_voltage(self, voltage):
        """ID=0: 시스템 전압 전송"""
        # 프레임 구성
        frame = bytearray(7)
        frame[0] = 0x02  # STX
        frame[1] = 0x00  # ID=0
        
        # 전압 (10배 스케일링)
        voltage_raw = int(voltage * 10)
        frame[2:4] = struct.pack('>H', voltage_raw)
        
        frame[4] = 0x00  # 예약
        frame[5] = self.calculate_checksum(frame)
        frame[6] = 0x03  # ETX
        
        self.serial.write(frame)
        print(f"Sent System Voltage: {voltage:.1f}V (raw=0x{voltage_raw:04X})")
        
    def send_slave_data(self, slave_id, current, temp, dab_ok=True):
        """ID≠0: Slave 데이터 전송"""
        # 프레임 구성
        frame = bytearray(7)
        frame[0] = 0x02  # STX
        
        # ID(5비트) + 예약(2비트) + DAB_OK(1비트)
        frame[1] = (slave_id << 3) | (0x00 << 1) | (0x01 if dab_ok else 0x00)
        
        # 전류 (100배 스케일링, signed)
        current_raw = int(current * 100)
        frame[2:4] = struct.pack('>h', current_raw)
        
        # 온도 (0.5도 단위)
        temp_raw = int(temp * 2)
        frame[4] = temp_raw & 0xFF
        
        frame[5] = self.calculate_checksum(frame)
        frame[6] = 0x03  # ETX
        
        self.serial.write(frame)
        print(f"Sent Slave {slave_id}: {current:.2f}A, {temp:.1f}°C, DAB_OK={dab_ok}")
        
    def run_test_sequence(self):
        """테스트 시퀀스 실행"""
        print("\nStarting test sequence...")
        
        # 시스템 전압 초기값
        system_voltage = 800.0
        
        # Slave 데이터 초기값
        slave_currents = [0.0] * 10  # 10개 모듈
        slave_temps = [25.0] * 10
        
        cycle_count = 0
        try:
            while True:
                # 시스템 전압 전송 (매 10사이클마다)
                if cycle_count % 10 == 0:
                    system_voltage += random.uniform(-10, 10)
                    system_voltage = max(0, min(1000, system_voltage))
                    self.send_system_voltage(system_voltage)
                    time.sleep(0.02)
                
                # Slave 데이터 순차 전송
                for i in range(10):
                    slave_id = i + 1
                    
                    # 전류 변동
                    slave_currents[i] += random.uniform(-2, 2)
                    slave_currents[i] = max(-80, min(80, slave_currents[i]))
                    
                    # 온도 변동
                    slave_temps[i] += random.uniform(-0.5, 0.5)
                    slave_temps[i] = max(0, min(100, slave_temps[i]))
                    
                    # DAB_OK 상태 (대부분 OK)
                    dab_ok = random.random() > 0.05  # 95% OK
                    
                    self.send_slave_data(slave_id, slave_currents[i], slave_temps[i], dab_ok)
                    time.sleep(0.05)  # 50ms로 복원
                    
                cycle_count += 1
                time.sleep(0.2)  # 사이클 간 대기 (0.5초 → 0.2초로 단축)
                
        except KeyboardInterrupt:
            print("\nTest sequence stopped")
            
    def close(self):
        """연결 종료"""
        if self.serial:
            self.serial.close()
            print("Connection closed")

def main():
    # 포트 선택
    import serial.tools.list_ports
    
    print("=== RS232 Binary Protocol Test Sender ===")
    print("Available serial ports:")
    ports = serial.tools.list_ports.comports()
    
    # RS232 관련 포트만 필터링
    filtered_ports = []
    for port in ports:
        port_info = f"{port.device} {port.description} {port.manufacturer or ''}".lower()
        if any(keyword in port_info for keyword in ['usbserial', 'ft', 'uart', 'usb', 'serial']) and not any(exclude in port_info for exclude in ['bluetooth', 'debug', 'focal']):
            filtered_ports.append(port)
    
    if not filtered_ports:
        print("No suitable serial ports found!")
        return
        
    for i, port in enumerate(filtered_ports):
        print(f"{i}: {port.device} - {port.description}")
        
    # 포트 선택
    if len(sys.argv) > 1:
        port_idx = int(sys.argv[1])
    else:
        print("\n테스트 방법:")
        print("1. 시리얼 모니터에서 첫 번째 포트에 연결")
        print("2. 이 송신기에서 두 번째 포트 선택")
        print("3. 두 포트가 RS232로 연결되어 있으면 데이터 수신 확인 가능")
        port_idx = int(input("\nSelect port number for sender: "))
        
    if port_idx >= len(filtered_ports):
        print("Invalid port number!")
        return
        
    port = filtered_ports[port_idx].device
    print(f"\nSelected sender port: {port}")
    
    # 송신기 시작
    sender = BinaryProtocolSender(port)
    
    if sender.connect():
        print("\n송신 시작... (Ctrl+C to stop)")
        try:
            sender.run_test_sequence()
        except KeyboardInterrupt:
            print("\nTest stopped by user")
        finally:
            sender.close()

if __name__ == "__main__":
    main()
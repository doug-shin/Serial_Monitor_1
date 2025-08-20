#!/usr/bin/env python3
"""
SM1 - Serial Monitor v0.6
PyQt5 기반 시리얼 모니터
모던하고 안정적인 GUI
"""

__version__ = "0.6"
__author__ = "Serial Monitor Team"

import sys
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import serial
import serial.tools.list_ports
import struct
import time
from datetime import datetime

class SerialWorker(QObject):
    """시리얼 데이터 읽기 워커"""
    slave_data_received = pyqtSignal(int, float, float, bool, str)  # id, current, temp, dab_ok, timestamp
    system_voltage_received = pyqtSignal(float, str)  # voltage, timestamp
    
    def __init__(self, parent=None):
        super().__init__()
        self.serial_port = None
        self.running = False
        self.parent_app = parent
        
    def connect_serial(self, port, baud):
        """시리얼 포트 연결"""
        try:
            self.serial_port = serial.Serial(port, baud, timeout=0.1)
            self.running = True
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False
            
    def disconnect_serial(self):
        """시리얼 포트 연결 해제"""
        self.running = False
        if self.serial_port:
            self.serial_port.close()
            
    @pyqtSlot()
    def read_serial(self):
        """시리얼 데이터 읽기 (바이너리 프로토콜)"""
        buffer = bytearray()
        while self.running:
            try:
                if self.serial_port and self.serial_port.in_waiting:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    buffer.extend(data)
                    
                    # 고정 길이 프레임 파싱 (더 안정적)
                    while len(buffer) >= 7:
                        # STX로 시작하는 프레임 찾기
                        stx_found = False
                        for i in range(len(buffer) - 6):
                            if buffer[i] == 0x02 and len(buffer) >= i + 7:
                                # 7바이트 프레임 후보
                                potential_frame = buffer[i:i+7]
                                if potential_frame[6] == 0x03:  # ETX 확인
                                    frame = potential_frame
                                    self.parse_frame(frame)
                                    buffer = buffer[i+7:]  # 처리한 프레임 제거
                                    stx_found = True
                                    break
                        
                        if not stx_found:
                            # STX를 찾지 못했으면 첫 바이트 제거하고 계속
                            buffer = buffer[1:]
                            
                self.msleep(10)  # 10ms 대기
                
            except Exception as e:
                print(f"Read error: {e}")
                self.msleep(100)
                
    def parse_frame(self, frame):
        """바이너리 프레임 파싱"""
        try:
            if len(frame) != 7:
                print(f"Invalid frame length: {len(frame)} - Frame: {frame.hex()}")
                return
                
            # 체크섬 검증 (활성화된 경우만)
            checksum_calc = sum(frame[1:5]) & 0xFF
            checksum_recv = frame[5]
            
            # ID 및 상태 비트 추출 (체크섬 검증 전에 미리 추출)
            byte1 = frame[1]
            slave_id = (byte1 >> 3) & 0x1F  # 상위 5비트
            dab_ok = byte1 & 0x01  # 최하위 비트
            
            if self.parent_app and self.parent_app.checksum_enabled and checksum_calc != checksum_recv:
                print(f"⚠️  Checksum error - ID={slave_id}: calc={checksum_calc:02X}, recv={checksum_recv:02X}, frame={frame.hex()}")
                return
            elif self.parent_app and not self.parent_app.checksum_enabled:
                # 체크섬 비활성화 시에는 로그 줄이기
                pass
                
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-5]  # 0.1초 단위까지 표시
            
            if slave_id == 0:
                # ID=0: 시스템 전압
                voltage_raw = struct.unpack('>h', frame[2:4])[0]  # signed int16
                voltage = voltage_raw / 10.0  # 10배 스케일링
                print(f"📊 System Voltage: {voltage:.1f}V at {timestamp}")
                self.system_voltage_received.emit(voltage, timestamp)
            else:
                # ID≠0: Slave 데이터
                current_raw = struct.unpack('>h', frame[2:4])[0]  # signed
                current = current_raw / 100.0  # 100배 스케일링
                
                temp_raw = frame[4]
                temp = temp_raw * 0.5  # 0.5도 단위
                
                # 각 모듈별 수신 로그 (간결하게)
                print(f"📡 ID{slave_id:2d}: {current:6.2f}A, {temp:4.1f}°C, DAB={dab_ok} at {timestamp}")
                self.slave_data_received.emit(slave_id, current, temp, bool(dab_ok), timestamp)
                
        except Exception as e:
            print(f"❌ Parse error: {e} - Frame: {frame.hex()}")
            
    def msleep(self, ms):
        """밀리초 대기"""
        QThread.msleep(ms)

class SerialMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 변수들
        self.serial_worker = None
        self.serial_thread = None
        self.connected = False
        self.packet_count = 0
        self.system_voltage = 0.0  # 시스템 전압 저장
        self.system_current = 0.0  # 시스템 전류 합계
        self.values_changed = False  # 입력값 변경 여부
        self.original_spinbox_style = ""  # 원래 스핀박스 스타일
        self.has_received_data = False  # 데이터 수신 여부
        self.checksum_enabled = True  # 체크섬 검증 사용 여부
        self.changed_spinboxes = set()  # 변경된 스핀박스 추적
        self.original_values = {}  # 원래 값 저장
        
        self.init_ui()
        self.refresh_ports()
        self.create_initial_modules()
        
        # System Current 초기값을 ---로 설정 (init_ui에서 0.00 A로 설정되는 것을 덮어씀)
        self.system_current_label.setText("---          ")
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        
    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle(f'SM1 - Serial Monitor v{__version__} - Power Control Module')
        self.setGeometry(100, 100, 800, 830)
        
        # 시스템 폰트 크기 증가
        font = self.font()
        font.setPointSize(font.pointSize() + 3)  # 총 3 증가 (1+2)
        self.setFont(font)
        
        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 메인 레이아웃
        layout = QVBoxLayout(central_widget)
        
        # ===========================================
        # 1. 연결 설정 그룹
        # ===========================================
        conn_group = QGroupBox("Connection Settings")
        conn_layout = QGridLayout(conn_group)
        
        # 포트 선택 (포트 라벨 + 새로고침 아이콘)
        port_label_layout = QHBoxLayout()
        port_label_layout.addWidget(QLabel("Port:"))
        
        # 새로고침 버튼 (텍스트)
        refresh_btn = QPushButton("refresh")
        refresh_btn.setToolTip("Refresh port list")
        refresh_btn.setFixedSize(60, 24)
        refresh_btn.setStyleSheet("""
            QPushButton {
                border: 1px solid #ccc;
                border-radius: 3px;
                background-color: #f0f0f0;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
        refresh_btn.clicked.connect(self.refresh_ports)
        port_label_layout.addWidget(refresh_btn)
        port_label_layout.addStretch()
        
        port_label_widget = QWidget()
        port_label_widget.setLayout(port_label_layout)
        conn_layout.addWidget(port_label_widget, 0, 0)
        
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        # Port 드롭다운 가운데 정렬
        self.port_combo.setStyleSheet("QComboBox { text-align: center; }")
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        # Baud rate 선택
        conn_layout.addWidget(QLabel("Baud:"), 0, 2)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud_combo.setCurrentText("38400")
        # Baud 드롭다운 우측 정렬
        self.baud_combo.setStyleSheet("QComboBox { text-align: right; }")
        conn_layout.addWidget(self.baud_combo, 0, 3)
        
        # 체크섬 검증 선택
        conn_layout.addWidget(QLabel("Checksum:"), 0, 4)
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(["ON", "OFF"])
        self.checksum_combo.setCurrentText("ON")
        self.checksum_combo.setMinimumWidth(80)
        # Checksum 드롭다운 가운데 정렬
        self.checksum_combo.setStyleSheet("QComboBox { text-align: center; }")
        self.checksum_combo.currentTextChanged.connect(self.on_checksum_changed)
        conn_layout.addWidget(self.checksum_combo, 0, 5)
        
        # 연결 버튼 (고정 크기)
        self.connect_btn = QPushButton("Disconnected")
        # 폰트 크기 증가
        connect_font = self.connect_btn.font()
        connect_font.setPointSize(connect_font.pointSize() + 2)
        self.connect_btn.setFont(connect_font)
        self.connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
        self.connect_btn.setFixedWidth(130)  # 폰트 크기 증가로 너비도 약간 증가
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn, 0, 6)
        
        
        layout.addWidget(conn_group)
        
        # ===========================================
        # 2. Control Commands (SCADA → Master)
        # ===========================================
        control_group = QGroupBox("Control Commands (SCADA → Master)")
        control_layout = QGridLayout(control_group)
        
        # 1행: Max Voltage(좌측), Current Command(우측)
        max_voltage_label = QLabel("Max Voltage:")
        max_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(max_voltage_label, 0, 0)
        
        self.max_voltage_spinbox = QDoubleSpinBox()
        self.max_voltage_spinbox.setRange(0.0, 1000.0)  # 양수만
        self.max_voltage_spinbox.setDecimals(1)
        self.max_voltage_spinbox.setSuffix(" V")
        self.max_voltage_spinbox.setValue(500.0)
        self.max_voltage_spinbox.setAlignment(Qt.AlignRight)  # 우측 정렬
        # 폰트 크기 증가
        spinbox_font = self.max_voltage_spinbox.font()
        spinbox_font.setPointSize(spinbox_font.pointSize() + 2)
        self.max_voltage_spinbox.setFont(spinbox_font)
        self.max_voltage_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        control_layout.addWidget(self.max_voltage_spinbox, 0, 1)
        
        current_label = QLabel("Current Command:")
        current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(current_label, 0, 2)
        self.current_spinbox = QDoubleSpinBox()
        self.current_spinbox.setRange(-128.0, 127.0)
        self.current_spinbox.setDecimals(0)
        self.current_spinbox.setSuffix(" A")
        self.current_spinbox.setValue(0.0)
        self.current_spinbox.setAlignment(Qt.AlignRight)  # 우측 정렬
        # 폰트 크기 증가
        current_font = self.current_spinbox.font()
        current_font.setPointSize(current_font.pointSize() + 2)
        self.current_spinbox.setFont(current_font)
        self.current_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        control_layout.addWidget(self.current_spinbox, 0, 3)
        
        # 2행: Min Voltage(좌측), Start/Stop 버튼(우측)
        min_voltage_label = QLabel("Min Voltage:")
        min_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(min_voltage_label, 1, 0)
        
        self.min_voltage_spinbox = QDoubleSpinBox()
        self.min_voltage_spinbox.setRange(0.0, 1000.0)  # 양수만
        self.min_voltage_spinbox.setDecimals(1)
        self.min_voltage_spinbox.setSuffix(" V")
        self.min_voltage_spinbox.setValue(0.0)  # 기본값 0V
        self.min_voltage_spinbox.setAlignment(Qt.AlignRight)  # 우측 정렬
        # 폰트 크기 증가
        min_font = self.min_voltage_spinbox.font()
        min_font.setPointSize(min_font.pointSize() + 2)
        self.min_voltage_spinbox.setFont(min_font)
        self.min_voltage_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        control_layout.addWidget(self.min_voltage_spinbox, 1, 1)
        
        # 원래 스핀박스 스타일 저장
        self.original_spinbox_style = self.max_voltage_spinbox.styleSheet()
        
        # 원래 값 저장
        self.original_values[self.max_voltage_spinbox] = 500.0
        self.original_values[self.min_voltage_spinbox] = 0.0
        self.original_values[self.current_spinbox] = 0.0
        
        # 입력값 변경 시그널 연결 (각각 독립적으로)
        self.max_voltage_spinbox.valueChanged.connect(lambda value: self.on_value_changed(self.max_voltage_spinbox, value))
        self.min_voltage_spinbox.valueChanged.connect(lambda value: self.on_value_changed(self.min_voltage_spinbox, value))
        self.current_spinbox.valueChanged.connect(lambda value: self.on_value_changed(self.current_spinbox, value))
        
        self.start_btn = QPushButton("Command")
        # 폰트 크기 증가
        start_font = self.start_btn.font()
        start_font.setPointSize(start_font.pointSize() + 2)
        self.start_btn.setFont(start_font)
        self.start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; }")
        self.start_btn.clicked.connect(self.send_start_command)
        control_layout.addWidget(self.start_btn, 1, 2)
        
        self.stop_btn = QPushButton("Stop")
        # 폰트 크기 증가
        stop_font = self.stop_btn.font()
        stop_font.setPointSize(stop_font.pointSize() + 2)
        self.stop_btn.setFont(stop_font)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; font-weight: bold; }")
        self.stop_btn.clicked.connect(self.send_stop_command)
        control_layout.addWidget(self.stop_btn, 1, 3)
        
        # 3행: System Voltage(좌측), System Current(우측)
        sys_voltage_label = QLabel("System Voltage:")
        sys_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(sys_voltage_label, 2, 0)
        self.system_voltage_label = QLabel("---          ")
        # System Voltage 폰트 크기 1.5배 증가 및 우측정렬
        voltage_font = self.font()
        voltage_font.setPointSize(int(voltage_font.pointSize() * 1.5))
        self.system_voltage_label.setFont(voltage_font)
        self.system_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        control_layout.addWidget(self.system_voltage_label, 2, 1)
        
        sys_current_label = QLabel("System Current:")
        sys_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(sys_current_label, 2, 2)
        self.system_current_label = QLabel("---          ")
        # System Current 폰트 크기 1.5배 증가 및 우측정렬
        current_font = self.font()
        current_font.setPointSize(int(current_font.pointSize() * 1.5))
        self.system_current_label.setFont(current_font)
        self.system_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        control_layout.addWidget(self.system_current_label, 2, 3)
        
        layout.addWidget(control_group)
        
        # ===========================================
        # 3. 통계 정보
        # ===========================================
        self.stats_label = QLabel("Connected: No | Modules: 0 | Packets: 0")
        self.stats_label.setStyleSheet("QLabel { background-color: #E3F2FD; padding: 8px; border: 1px solid #BBDEFB; }")
        layout.addWidget(self.stats_label)
        
        # ===========================================
        # 4. 데이터 테이블
        # ===========================================
        table_group = QGroupBox("Slave Module Data")
        table_layout = QVBoxLayout(table_group)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['ID', 'DAB_OK', 'Current (A)', 'Temp (°C)', 'Update'])
        
        # 테이블 설정 - 사용자가 컬럼 너비를 조절할 수 있도록 설정
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # 모든 컬럼을 사용자가 조절 가능하게
        
        # 초기 컬럼 너비 설정 (이전 Stretch 모드와 유사한 크기)
        self.table.setColumnWidth(0, 60)   # ID
        self.table.setColumnWidth(1, 100)   # DAB_OK
        self.table.setColumnWidth(2, 240)  # Current (A) - 더 넓게
        self.table.setColumnWidth(3, 240)  # Temp (°C) - 더 넓게
        self.table.setColumnWidth(4, 120)  # Update
        
        # 테이블 정렬 설정
        header.setDefaultAlignment(Qt.AlignCenter)  # 헤더 중앙정렬
        
        # 테이블 스타일
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        
        # 행 번호 숨기기
        self.table.verticalHeader().setVisible(False)
        
        # 행 높이 설정 (위아래 여백 추가)
        self.table.verticalHeader().setDefaultSectionSize(35)  # 기본 행 높이
        
        # 헤더 행 높이 설정
        header.setFixedHeight(40)  # 헤더 높이
        
        table_layout.addWidget(self.table)
        layout.addWidget(table_group)
        
        # ===========================================
        # 4. 하단 버튼
        # ===========================================
        btn_layout = QHBoxLayout()
        
        # + 버튼 (모듈 추가)
        add_btn = QPushButton("+")
        add_btn.setFixedSize(60, 30)
        add_btn.setToolTip("Add Test Module")
        add_btn.clicked.connect(self.add_test_module)
        btn_layout.addWidget(add_btn)
        
        # - 버튼 (모듈 제거)
        remove_btn = QPushButton("-")
        remove_btn.setFixedSize(60, 30)
        remove_btn.setToolTip("Remove Last Module")
        remove_btn.clicked.connect(self.remove_last_module)
        btn_layout.addWidget(remove_btn)
        
        btn_layout.addStretch()
        
        # Reset 버튼 (초기 상태로 되돌리기)
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_to_initial)
        btn_layout.addWidget(reset_btn)
        
        layout.addLayout(btn_layout)
        
        # ===========================================
        # 5. 상태바
        # ===========================================
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("● Disconnected")
        
        # 모듈 데이터 저장용
        self.module_rows = {}  # slave_id -> row_index
        self.module_currents = {}  # slave_id -> current_value (전류 합계용)
        self.module_last_update = {}  # slave_id -> last_update_time (수신 시간 추적)
        
        # DAB_OK 상태 체크 타이머 (1초마다)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_module_status)
        self.status_timer.start(1000)  # 1초마다 체크
        
    def add_slave_module(self, slave_id, current, temp, dab_ok, timestamp):
        """슬레이브 모듈 데이터 추가/업데이트"""
        # 모듈이 테이블에 없으면 새 행 추가
        if slave_id not in self.module_rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.module_rows[slave_id] = row
        
        row = self.module_rows[slave_id]
        
        # 마지막 업데이트 시간 기록 (현재 시간)
        self.module_last_update[slave_id] = time.time()
        
        # 데이터 업데이트 (열 순서 변경: ID, DAB_OK, Current, Temp, Update)
        
        # ID (중앙정렬)
        id_item = QTableWidgetItem(str(slave_id))
        id_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, id_item)
        
        # DAB_OK (중앙정렬) - 실시간 데이터이므로 정상 색상으로 표시
        dab_item = QTableWidgetItem("✓" if dab_ok else "✗")
        dab_item.setTextAlignment(Qt.AlignCenter)
        if dab_ok:
            dab_item.setBackground(QColor(200, 255, 200))  # 녹색
        else:
            dab_item.setBackground(QColor(255, 200, 200))  # 빨간색
        self.table.setItem(row, 1, dab_item)
        
        # Current (우측 여백 1.5배 증가)
        current_item = QTableWidgetItem(f"{current:.2f} A                 ")
        current_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 2, current_item)
        
        # Temp (우측 여백 1.5배 증가)
        temp_item = QTableWidgetItem(f"{temp:.1f} °C                 ")
        temp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 3, temp_item)
        
        # Update (중앙정렬)
        update_item = QTableWidgetItem(timestamp)
        update_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 4, update_item)
            
        # 모듈 전류 저장 및 시스템 전류 합계 업데이트
        self.module_currents[slave_id] = current
        self.update_system_current()
        
    def check_module_status(self):
        """모듈 상태 체크 - 1초 이상 업데이트가 없으면 회색으로 표시, 5초 이상이면 값 초기화"""
        if not self.connected:
            return
            
        current_time = time.time()
        
        for slave_id, row in self.module_rows.items():
            if slave_id in self.module_last_update:
                time_since_update = current_time - self.module_last_update[slave_id]
                
                # 1초 이상 업데이트가 없으면 회색으로 변경
                if time_since_update >= 1.0:
                    dab_item = self.table.item(row, 1)  # DAB_OK 컬럼
                    if dab_item:
                        dab_item.setBackground(QColor(200, 200, 200))  # 회색
                
                # 5초 이상 업데이트가 없으면 해당 모듈의 값을 초기화
                if time_since_update >= 5.0:
                    # Current를 0.00으로 초기화
                    current_item = self.table.item(row, 2)
                    if current_item:
                        current_item.setText("0.00 A                 ")
                    
                    # Temp를 0.0으로 초기화
                    temp_item = self.table.item(row, 3)
                    if temp_item:
                        temp_item.setText("0.0 °C                 ")
                    
                    # DAB_OK를 ✗로 초기화 (회색 배경 유지)
                    dab_item = self.table.item(row, 1)
                    if dab_item:
                        dab_item.setText("✗")
                        dab_item.setBackground(QColor(200, 200, 200))  # 회색 유지
                    
                    # Update time을 "--:--:--"로 초기화
                    update_item = self.table.item(row, 4)
                    if update_item:
                        update_item.setText("--:--:--")
                    
                    # 해당 모듈의 전류를 0으로 초기화하고 시스템 전류 업데이트
                    if slave_id in self.module_currents:
                        self.module_currents[slave_id] = 0.0
                        self.update_system_current()
        
    def create_initial_modules(self):
        """초기 실행시 10개 모듈 생성"""
        for i in range(1, 11):  # ID 1부터 10까지
            self.add_slave_module(i, 0.0, 0.0, False, "--:--:--")
        
    def get_clean_port_name(self, device_path, description):
        """포트 이름을 깔끔하게 만들기"""
        # /dev/cu. 또는 /dev/tty. 제거
        clean_name = device_path.replace('/dev/cu.', '').replace('/dev/tty.', '')
        
        # Windows COM 포트는 그대로 사용
        if clean_name.startswith('COM'):
            return clean_name
            
        # usbserial- 제거
        clean_name = clean_name.replace('usbserial-', '')
        
        # 설명에서 유용한 정보 추출
        if description:
            desc_lower = description.lower()
            if 'ftdi' in desc_lower or 'ft' in desc_lower:
                chip_type = 'FTDI'
            elif 'cp210' in desc_lower or 'silicon labs' in desc_lower:
                chip_type = 'SiLabs'
            elif 'ch340' in desc_lower or 'ch341' in desc_lower:
                chip_type = 'WCH'
            elif 'pl2303' in desc_lower or 'prolific' in desc_lower:
                chip_type = 'Prolific'
            else:
                chip_type = 'USB'
            
            # 최종 형태: "FTDI D200N07M" 또는 "USB Serial"
            if clean_name and clean_name != device_path:
                return f"{chip_type} {clean_name}"
            else:
                return f"{chip_type} Serial"
        
        # 설명이 없으면 단순히 이름만
        return clean_name if clean_name else device_path
        
    def refresh_ports(self):
        """RS232/USB-to-Serial 포트만 필터링해서 표시"""
        self.port_combo.clear()
        all_ports = serial.tools.list_ports.comports()
        
        # RS232/USB-to-Serial 관련 키워드
        serial_keywords = [
            'usbserial',     # USB-to-Serial 어댑터
            'tty.usb',       # macOS USB 포트
            'COM',           # Windows COM 포트
            'FTDI',          # FTDI 칩셋
            'CP210',         # Silicon Labs 칩셋
            'CH340',         # WCH 칩셋
            'PL2303',        # Prolific 칩셋
            'Serial',        # 일반적인 시리얼 포트
            'UART',          # UART 포트
        ]
        
        # 제외할 포트 키워드
        exclude_keywords = [
            'bluetooth',     # 블루투스 포트
            'debug-console', # 디버그 콘솔
            'focal',         # Focal 관련 포트
            'airpods',       # 에어팟 등 오디오 관련
        ]
        
        filtered_ports = []
        for port in all_ports:
            # 포트 디바이스명과 설명에서 키워드 검색
            port_info = f"{port.device} {port.description} {port.manufacturer or ''}".lower()
            
            # 제외 키워드 확인
            if any(exclude_keyword.lower() in port_info for exclude_keyword in exclude_keywords):
                print(f"✗ Excluded: {port.device} - {port.description}")
                continue
            
            # 시리얼 포트 키워드 확인
            if any(keyword.lower() in port_info for keyword in serial_keywords):
                # 포트 이름을 깔끔하게 만들기
                display_name = self.get_clean_port_name(port.device, port.description)
                # 실제 포트 경로와 표시 이름을 튜플로 저장
                filtered_ports.append((port.device, display_name))
                print(f"✓ Serial port: {port.device} -> {display_name}")
            else:
                print(f"✗ Filtered out: {port.device} - {port.description}")
        
        # 필터링된 포트가 없으면 모든 포트 표시 (안전장치)
        if not filtered_ports:
            filtered_ports = [(port.device, port.device) for port in all_ports]
            print("⚠️  No serial ports found, showing all ports")
        
        # 콤보박스에 깔끔한 이름으로 표시
        for device_path, display_name in filtered_ports:
            self.port_combo.addItem(display_name, device_path)  # 표시명, 실제경로
        
        print(f"Available serial ports: {[name for _, name in filtered_ports]}")
        
    def toggle_connection(self):
        """연결/해제 토글"""
        if not self.connected:
            self.connect_serial()
        else:
            self.disconnect_serial()
            
    def connect_serial(self):
        """시리얼 포트 연결"""
        # 콤보박스에서 실제 포트 경로 가져오기
        port = self.port_combo.currentData()  # 실제 포트 경로 (/dev/cu.xxx)
        if not port:  # currentData()가 없으면 텍스트 사용 (호환성)
            port = self.port_combo.currentText()
            
        baud = int(self.baud_combo.currentText())
        
        if not port:
            QMessageBox.warning(self, "Warning", "Please select a port")
            return
            
        # 워커와 스레드 생성
        self.serial_worker = SerialWorker(self)
        self.serial_thread = QThread()
        
        # 워커를 스레드로 이동
        self.serial_worker.moveToThread(self.serial_thread)
        
        # 시그널 연결
        self.serial_worker.slave_data_received.connect(self.update_slave_data)
        self.serial_worker.system_voltage_received.connect(self.update_system_voltage)
        self.serial_thread.started.connect(self.serial_worker.read_serial)
        
        # 시리얼 포트 연결
        if self.serial_worker.connect_serial(port, baud):
            self.connected = True
            self.serial_thread.start()
            
            # UI 업데이트
            self.connect_btn.setText("Connected")
            self.connect_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; }")
            self.status_bar.showMessage(f"● Connected to {port} at {baud} baud")
            
            # 연결됨 - 대기 상태로 표시 (회색 - 데이터 없음)
            self.system_voltage_label.setText("0.0 V          ")
            self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색 - 데이터 대기
            self.system_current_label.setText("0.0 A          ")
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색 - 데이터 대기
            
            print(f"Connected to {port} at {baud} baud")
        else:
            QMessageBox.critical(self, "Error", f"Failed to connect to {port}")
            
    def disconnect_serial(self):
        """시리얼 포트 연결 해제"""
        self.connected = False  # 먼저 연결 상태 변경
        
        if self.serial_worker:
            self.serial_worker.disconnect_serial()
            
        if self.serial_thread:
            self.serial_thread.quit()
            self.serial_thread.wait()
            
        # 워커와 스레드 완전히 정리
        self.serial_worker = None
        self.serial_thread = None
        
        # UI 업데이트
        self.connect_btn.setText("Disconnected")
        self.connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
        self.status_bar.showMessage("● Disconnected")
        
        # 연결 해제 - 미연결 상태로 표시
        self.system_voltage_label.setText("---          ")
        self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색
        self.system_current_label.setText("---          ")
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색
        self.has_received_data = False
        
        print("Disconnected - 모든 스레드 정리 완료")
        
    @pyqtSlot(int, float, float, bool, str)
    def update_slave_data(self, slave_id, current, temp, dab_ok, timestamp):
        """슬레이브 데이터 업데이트"""
        # 연결되지 않았으면 데이터 업데이트 하지 않음
        if not self.connected:
            return
        
        self.packet_count += 1
        self.add_slave_module(slave_id, current, temp, dab_ok, timestamp)
        self.update_stats()
        
    @pyqtSlot(float, str)
    def update_system_voltage(self, voltage, timestamp):
        """시스템 전압 업데이트"""
        if not self.connected:
            return
        
        self.system_voltage = voltage
        self.system_voltage_label.setText(f"{voltage:.1f} V          ")
        self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #2E7D32; }")  # 녹색 - 데이터 수신
        self.has_received_data = True
        self.packet_count += 1
        self.update_stats()
    
    def update_system_current(self):
        """시스템 전류 합계 업데이트"""
        self.system_current = sum(self.module_currents.values())
        self.system_current_label.setText(f"{self.system_current:.2f} A          ")
        if self.has_received_data:
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #1976D2; }")  # 파란색 - 데이터 수신
    
    def update_stats(self):
        """통계 정보 업데이트"""
        self.stats_label.setText(f"Connected: {'Yes' if self.connected else 'No'} | Modules: {len(self.module_rows)} | Packets: {self.packet_count}")
        
    def add_test_module(self):
        """테스트 모듈 추가 (수동으로만)"""
        next_id = len(self.module_rows) + 1
        if next_id > 31:  # 5비트 ID 최대값
            QMessageBox.warning(self, "Warning", "Maximum 31 modules reached")
            return
        
        # 깔끔한 초기값 설정 (0A, 0°C)
        self.add_slave_module(next_id, 0.0, 0.0, False, "--:--:--")
        self.update_stats()
        print(f"테스트 모듈 ID {next_id} 추가됨")
        
    def remove_last_module(self):
        """마지막 모듈 제거"""
        if not self.module_rows:
            return
            
        # 가장 큰 ID를 가진 모듈 찾기
        max_id = max(self.module_rows.keys())
        row = self.module_rows[max_id]
        
        # 테이블에서 행 제거
        self.table.removeRow(row)
        
        # 데이터 제거
        del self.module_rows[max_id]
        if max_id in self.module_currents:
            del self.module_currents[max_id]
        if max_id in self.module_last_update:
            del self.module_last_update[max_id]
            
        # 나머지 모듈들의 row 인덱스 업데이트
        for module_id, module_row in self.module_rows.items():
            if module_row > row:
                self.module_rows[module_id] = module_row - 1
                
        self.update_system_current()
        self.update_stats()
        print(f"모듈 ID {max_id} 제거됨")
        
    def reset_to_initial(self):
        """초기 상태로 되돌리기 (10개 모듈)"""
        # 모든 데이터 지우기
        self.table.setRowCount(0)
        self.module_rows.clear()
        self.module_currents.clear()
        self.module_last_update.clear()
        self.packet_count = 0
        
        # 초기 10개 모듈 생성
        self.create_initial_modules()
        
        # 시스템 값 초기화
        self.system_voltage = 0.0
        self.system_current = 0.0
        self.has_received_data = False
        
        # 연결 상태에 따른 표시
        if self.connected:
            self.system_voltage_label.setText("0.0 V          ")
            self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색 - 데이터 대기
            self.system_current_label.setText("0.0 A          ")
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색 - 데이터 대기
        else:
            self.system_voltage_label.setText("---          ")
            self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색
            self.system_current_label.setText("---          ")
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색
        
        self.stats_label.setText("Connected: No | Modules: 10 | Packets: 0")
        
        # 상태 초기화
        self.values_changed = False
        self.changed_spinboxes.clear()
        self.start_btn.setText("Command")
        self.restore_spinbox_colors()
        
        # 원래 값 초기화
        self.original_values[self.max_voltage_spinbox] = 500.0
        self.original_values[self.min_voltage_spinbox] = 0.0
        self.original_values[self.current_spinbox] = 0.0
        
        print("초기 상태로 리셋됨 (10개 모듈)")
        
    def on_value_changed(self, spinbox, value):
        """입력값 변경 시 호출되는 함수 (개별 스핀박스용)"""
        # 원래 값과 비교
        original_value = self.original_values.get(spinbox, 0.0)
        if abs(value - original_value) < 0.01:  # 원래 값으로 돌아왔을 때
            self.restore_specific_spinbox_color(spinbox)
        else:
            # 값이 변경되었을 때
            self.values_changed = True
            self.changed_spinboxes.add(spinbox)
            
            # 해당 스핀박스만 색상 변경 (노란색 배경)
            changed_style = "QDoubleSpinBox { background-color: #FFF9C4; padding-right: 50px; }"
            spinbox.setStyleSheet(changed_style)
            
            # 버튼 텍스트를 Update로 변경
            self.start_btn.setText("Update")
        
    def restore_spinbox_colors(self):
        """스핀박스 색상을 원래대로 복원"""
        normal_style = "QDoubleSpinBox { padding-right: 50px; }"
        self.max_voltage_spinbox.setStyleSheet(normal_style)
        self.min_voltage_spinbox.setStyleSheet(normal_style)
        self.current_spinbox.setStyleSheet(normal_style)
        self.changed_spinboxes.clear()
        
    def restore_specific_spinbox_color(self, spinbox):
        """특정 스핀박스 색상을 원래대로 복원"""
        normal_style = "QDoubleSpinBox { padding-right: 50px; }"
        spinbox.setStyleSheet(normal_style)
        self.changed_spinboxes.discard(spinbox)
        
        # 모든 변경사항이 복원되었으면 버튼 텍스트 원복
        if not self.changed_spinboxes:
            self.values_changed = False
            self.start_btn.setText("Command")
            
    def on_checksum_changed(self, value):
        """체크섬 설정 변경"""
        self.checksum_enabled = (value == "ON")
        if self.checksum_enabled:
            print("체크섬 검증 활성화")
        else:
            print("체크섬 검증 비활성화")
        
    def send_start_command(self):
        """시작 명령 전송 (SCADA → Master)"""
        if not self.connected or not self.serial_worker:
            QMessageBox.warning(self, "Warning", "Please connect to serial port first")
            return
            
        try:
            # SCADA → Master 프로토콜 (9바이트)
            frame = bytearray(9)
            frame[0] = 0x02  # STX
            frame[1] = 0x01  # Command: 1-시작
            
            # 전압 상한 지령 (2바이트, 스케일링 없음) - 항상 양수
            max_voltage_raw = int(abs(self.max_voltage_spinbox.value()))
            frame[2:4] = struct.pack('>h', max_voltage_raw)  # signed int16
            
            # 전압 하한 지령 (2바이트, 스케일링 없음) - 항상 양수
            min_voltage_raw = int(abs(self.min_voltage_spinbox.value()))
            frame[4:6] = struct.pack('>h', min_voltage_raw)  # signed int16
            
            # 전류 지령 (1바이트, 스케일링 없음, -128~+127)
            current_raw = int(self.current_spinbox.value())
            current_raw = max(-128, min(127, current_raw))  # -128~+127 제한
            frame[6] = struct.pack('>b', current_raw)[0]  # signed int8
            
            # 체크섬 (Byte1~6의 합)
            checksum = sum(frame[1:7]) & 0xFF
            frame[7] = checksum
            
            frame[8] = 0x03  # ETX
            
            # 시리얼로 전송
            self.serial_worker.serial_port.write(frame)
            
            # 상태 업데이트
            self.values_changed = False
            self.start_btn.setText("Command")
            self.restore_spinbox_colors()
            
            # 현재 값들을 새로운 원래 값으로 설정
            self.original_values[self.max_voltage_spinbox] = self.max_voltage_spinbox.value()
            self.original_values[self.min_voltage_spinbox] = self.min_voltage_spinbox.value()
            self.original_values[self.current_spinbox] = self.current_spinbox.value()
            
            print(f"Start command sent: Max={self.max_voltage_spinbox.value():.1f}V, Min={self.min_voltage_spinbox.value():.1f}V, Current={self.current_spinbox.value():.0f}A, Checksum=0x{checksum:02X}")
            
        except Exception as e:
            print(f"Failed to send start command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to send start command: {e}")
    
    def send_stop_command(self):
        """정지 명령 전송 (SCADA → Master)"""
        if not self.connected or not self.serial_worker:
            QMessageBox.warning(self, "Warning", "Please connect to serial port first")
            return
            
        try:
            # SCADA → Master 프로토콜 (9바이트)
            frame = bytearray(9)
            frame[0] = 0x02  # STX
            frame[1] = 0x00  # Command: 0-정지
            
            # 전압, 전류 모두 0으로 설정
            frame[2:4] = struct.pack('>h', 0)  # Max Voltage = 0
            frame[4:6] = struct.pack('>h', 0)  # Min Voltage = 0
            frame[6] = 0x00  # Current = 0
            
            # 체크섬 (Byte1~6의 합)
            checksum = sum(frame[1:7]) & 0xFF
            frame[7] = checksum
            
            frame[8] = 0x03  # ETX
            
            # 시리얼로 전송
            self.serial_worker.serial_port.write(frame)
            
            # 상태 업데이트
            self.values_changed = False
            self.start_btn.setText("Command")
            self.restore_spinbox_colors()
            
            print(f"Stop command sent: All values set to 0, Checksum=0x{checksum:02X}")
            
        except Exception as e:
            print(f"Failed to send stop command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to send stop command: {e}")
        
    def closeEvent(self, event):
        """프로그램 종료시 정리"""
        if self.connected:
            self.disconnect_serial()
        
        # 타이머 정리
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()
            
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # 애플리케이션 스타일 설정
    app.setStyle('Fusion')
    
    # 다크 테마 (선택사항)
    # palette = QPalette()
    # palette.setColor(QPalette.Window, QColor(53, 53, 53))
    # app.setPalette(palette)
    
    window = SerialMonitorApp()
    window.show()
    
    print(f"SM1 - Serial Monitor v{__version__} 시작")
    print("Add Test Module 버튼으로 테스트 데이터 추가 가능")
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
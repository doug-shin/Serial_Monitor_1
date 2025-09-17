#!/usr/bin/env python3
"""
SM1 - Serial Monitor v0.7
PyQt5 기반 시리얼 모니터
모던하고 안정적인 GUI
"""

__version__ = "0.7"
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

# 프로토콜 상수
PROTOCOL_STX = 0x02
PROTOCOL_ETX = 0x03
PROTOCOL_FRAME_SIZE = 7
PROTOCOL_COMMAND_SIZE = 10

# 시스템 상수
MAX_BUFFER_SIZE = 1024
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_INTERVAL_MS = 5000
STATUS_CHECK_INTERVAL_MS = 1000
THREAD_WAIT_TIMEOUT_MS = 5000

# UI 상수
WINDOW_SIZE_1CH = (820, 850)
WINDOW_SIZE_2CH = (1640, 850)
RESIZE_DELAY_MS = 50

# 동적 리사이즈 타이밍 상수
RESIZE_BASE_DELAY_MS = 30      # 기본 지연 시간
RESIZE_MAX_DELAY_MS = 200      # 최대 지연 시간
RESIZE_PERFORMANCE_SAMPLES = 5  # 성능 측정 샘플 수

# 체크섬 에러 모니터링 상수
CHECKSUM_ERROR_ALERT_THRESHOLD = 5  # 연속 에러 알림 임계값
CHECKSUM_ERROR_RATE_WINDOW = 100    # 에러율 계산 윈도우 (패킷 수)
CHECKSUM_ERROR_RATE_ALERT = 0.05    # 에러율 알림 임계값 (5%)

# 신호 레이트 리미팅 상수
UI_UPDATE_INTERVAL_MS = 50  # UI 업데이트 주기 (20Hz)
MAX_QUEUED_SIGNALS = 1000   # 최대 대기 중인 신호 수
SIGNAL_BATCH_SIZE = 10      # 한 번에 처리할 신호 수

# 데이터 범위 상수
VOLTAGE_SCALE = 10.0
CURRENT_SCALE = 100.0
CURRENT_CENTER = 32768
TEMP_SCALE = 0.5
MAX_SLAVE_ID = 31

class SerialWorker(QObject):
    """시리얼 데이터 읽기 워커"""
    slave_data_received = pyqtSignal(int, int, float, float, bool, str)  # channel, id, current, temp, dab_ok, timestamp
    system_voltage_received = pyqtSignal(int, float, str)  # channel, voltage, timestamp
    
    def __init__(self, parent=None, channel=0):
        super().__init__()
        self.serial_port = None
        self.running = False
        self.parent_app = parent
        self.channel = channel  # 채널 정보 저장
        
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

                    # 버퍼 크기 제한 (메모리 보호)
                    if len(buffer) > MAX_BUFFER_SIZE:
                        print(f"⚠️ CH{self.channel+1} Buffer overflow detected, clearing buffer (size: {len(buffer)})")
                        buffer = buffer[-MAX_BUFFER_SIZE//2:]  # 뒤쪽 절반만 유지

                    # 고정 길이 프레임 파싱
                    while len(buffer) >= PROTOCOL_FRAME_SIZE:
                        # STX로 시작하는 프레임 찾기
                        stx_found = False
                        for i in range(len(buffer) - (PROTOCOL_FRAME_SIZE-1)):
                            if buffer[i] == PROTOCOL_STX and len(buffer) >= i + PROTOCOL_FRAME_SIZE:
                                # 프레임 후보
                                potential_frame = buffer[i:i+PROTOCOL_FRAME_SIZE]
                                if potential_frame[PROTOCOL_FRAME_SIZE-1] == PROTOCOL_ETX:  # ETX 확인
                                    frame = potential_frame
                                    self.parse_frame(frame)
                                    buffer = buffer[i+PROTOCOL_FRAME_SIZE:]  # 처리한 프레임 제거
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
            if len(frame) != PROTOCOL_FRAME_SIZE:
                print(f"Invalid frame length: {len(frame)} - Frame: {frame.hex()}")
                return
                
            # 체크섬 검증 (활성화된 경우만)
            checksum_calc = sum(frame[1:5]) & 0xFF
            checksum_recv = frame[5]
            
            # ID 및 상태 비트 추출 (체크섬 검증 전에 미리 추출)
            byte1 = frame[1]
            slave_id = (byte1 >> 3) & 0x1F  # 상위 5비트
            dab_ok = byte1 & 0x01  # 최하위 비트
            
            # 패킷 수신 추적
            if self.parent_app:
                self.parent_app.track_packet_received(self.channel)

            # 체크섬 검증 및 에러 추적
            if self.parent_app and self.parent_app.checksum_enabled[self.channel]:
                if checksum_calc != checksum_recv:
                    # 체크섬 에러 추적
                    self.parent_app.track_checksum_error(self.channel, frame)
                    print(f"⚠️  Checksum error - ID={slave_id}: calc={checksum_calc:02X}, recv={checksum_recv:02X}, frame={frame.hex()}")
                    return
                else:
                    # 체크섬 성공 추적
                    self.parent_app.track_checksum_success(self.channel)
            elif self.parent_app and not self.parent_app.checksum_enabled[self.channel]:
                # 체크섬 비활성화 시에는 로그 줄이기
                pass
                
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-5]  # 0.1초 단위까지 표시
            
            if slave_id == 0:
                # ID=0: 시스템 전압
                voltage_raw = struct.unpack('>h', frame[2:4])[0]  # signed int16
                voltage = voltage_raw / VOLTAGE_SCALE
                print(f"📊 CH{self.channel+1} System Voltage: {voltage:.1f}V at {timestamp}")
                self.system_voltage_received.emit(self.channel, voltage, timestamp)
            else:
                # ID≠0: Slave 데이터 (프로토콜 2.0)
                current_raw = struct.unpack('>H', frame[2:4])[0]  # unsigned int16
                current = (current_raw - CURRENT_CENTER) / CURRENT_SCALE

                temp_raw = frame[4]
                temp = temp_raw * TEMP_SCALE
                
                # 각 모듈별 수신 로그 (간결하게)
                print(f"📡 CH{self.channel+1} ID{slave_id:2d}: {current:6.2f}A, {temp:4.1f}°C, DAB={dab_ok} at {timestamp}")
                self.slave_data_received.emit(self.channel, slave_id, current, temp, bool(dab_ok), timestamp)
                
        except Exception as e:
            print(f"❌ Parse error: {e} - Frame: {frame.hex()}")
            
    def msleep(self, ms):
        """밀리초 대기"""
        QThread.msleep(ms)

class SerialMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 2채널 지원 변수들
        self.serial_workers = [None, None]  # 채널별 워커
        self.serial_threads = [None, None]  # 채널별 스레드
        self.connected = [False, False]     # 채널별 연결 상태
        self.channel_count = 1              # 현재 채널 수 (1 or 2)
        self.operation_mode = "Independent" # 운전 모드 (Independent/Parallel)
        self.packet_count = [0, 0]  # 채널별 패킷 카운터 [CH1, CH2]
        self.system_voltage = 0.0  # 시스템 전압 저장
        self.system_current = 0.0  # 시스템 전류 합계
        self.values_changed = False  # 입력값 변경 여부
        self.original_spinbox_style = ""  # 원래 스핀박스 스타일
        self.has_received_data = False  # 데이터 수신 여부
        self.checksum_enabled = [True, True]  # 채널별 체크섬 검증 사용 여부 [CH1, CH2]
        self.reconnect_attempts = [0, 0]  # 채널별 재연결 시도 횟수 [CH1, CH2]
        self.max_reconnect_attempts = 10  # 최대 재연결 시도 횟수
        self.changed_spinboxes = set()  # 변경된 스핀박스 추적
        self.original_values = {}  # 원래 값 저장

        # 원자적 상태 전환을 위한 변수들
        self.state_transition_lock = False  # 상태 전환 중 잠금
        self.transition_buttons = []  # 전환 중 비활성화할 버튼들

        # 신호 레이트 리미팅을 위한 변수들
        from collections import deque
        self.signal_queue = deque(maxlen=MAX_QUEUED_SIGNALS)  # 대기 중인 신호들
        self.ui_update_timer = QTimer()  # UI 업데이트 타이머
        self.ui_update_timer.timeout.connect(self.process_queued_signals)
        self.ui_update_timer.start(UI_UPDATE_INTERVAL_MS)
        self.last_ui_update = {}  # 마지막 UI 업데이트 시간 추적

        # 동적 리사이즈 타이밍을 위한 변수들
        import time
        self.resize_performance_samples = deque(maxlen=RESIZE_PERFORMANCE_SAMPLES)  # 성능 샘플들
        self.last_resize_start = 0  # 마지막 리사이즈 시작 시간
        self.adaptive_resize_delay = RESIZE_BASE_DELAY_MS  # 적응적 지연 시간

        # 체크섬 에러 모니터링을 위한 변수들
        self.checksum_error_count = [0, 0]  # 채널별 총 에러 수 [CH1, CH2]
        self.checksum_consecutive_errors = [0, 0]  # 채널별 연속 에러 수 [CH1, CH2]
        self.checksum_total_packets = [0, 0]  # 채널별 총 패킷 수 (에러율 계산용) [CH1, CH2]
        self.checksum_error_history = [deque(maxlen=CHECKSUM_ERROR_RATE_WINDOW), deque(maxlen=CHECKSUM_ERROR_RATE_WINDOW)]  # 에러 이력 [CH1, CH2]
        self.last_checksum_alert_time = [0, 0]  # 마지막 알림 시간 [CH1, CH2]

        self.init_ui()
        self.refresh_ports()
        self.create_initial_modules()
        
        # System Current 초기값을 ---로 설정 (init_ui에서 0.00 A로 설정되는 것을 덮어씀)
        self.system_current_label.setText("---          ")
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        
    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle(f'SM1 - Serial Monitor v{__version__} - Power Control Module')
        self.setGeometry(100, 100, 820, 850)
        
        # 시스템 폰트 크기 증가
        font = self.font()
        font.setPointSize(font.pointSize() + 3)  # 총 3 증가 (1+2)
        self.setFont(font)
        
        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 레이아웃 (수평 분할 준비)
        self.main_layout = QHBoxLayout(central_widget)

        # 채널1 레이아웃
        self.ch1_widget = QWidget()
        self.ch1_layout = QVBoxLayout(self.ch1_widget)
        self.ch1_layout.setSpacing(8)  # 위젯 간 간격 줄이기 (기본값보다 작게)
        layout = self.ch1_layout  # 기존 코드 호환성을 위해
        
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
        # Port 드롭다운 가운데 정렬 및 전체 클릭 가능
        self.port_combo.setStyleSheet("""
            QComboBox {
                text-align: center;
            }
            QComboBox QAbstractItemView {
                text-align: center;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
        conn_layout.addWidget(self.port_combo, 0, 1)
        
        # Baud rate 선택
        conn_layout.addWidget(QLabel("Baud:"), 0, 2)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud_combo.setCurrentText("115200")
<<<<<<< HEAD
        # Baud 드롭다운 우측 정렬 및 전체 클릭 가능
        self.baud_combo.setStyleSheet("""
            QComboBox {
                text-align: right;
            }
            QComboBox QAbstractItemView {
                text-align: right;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
=======
        # Baud 드롭다운 우측 정렬
        self.baud_combo.setStyleSheet("QComboBox { text-align: right; }")
>>>>>>> 2e48dab (feat(v0.7): Dual/Parallel UI, independent channels, protocol v2.0 docs, default baud 115200; version bump to 0.7)
        conn_layout.addWidget(self.baud_combo, 0, 3)
        
        # 체크섬 검증 선택
        conn_layout.addWidget(QLabel("Checksum:"), 0, 4)
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(["ON", "OFF"])
        self.checksum_combo.setCurrentText("ON")
        self.checksum_combo.setMinimumWidth(80)
        # Checksum 드롭다운 가운데 정렬 및 전체 클릭 가능
        self.checksum_combo.setStyleSheet("""
            QComboBox {
                text-align: center;
            }
            QComboBox QAbstractItemView {
                text-align: center;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
        self.checksum_combo.currentTextChanged.connect(lambda value: self.on_checksum_changed(value, 0))
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
        # Control Commands 헤더를 그룹박스 밖에 배치
        control_header_layout = QHBoxLayout()
        self.control_header_label = QLabel("Control Commands")
        control_header_layout.addWidget(self.control_header_label)
        control_header_layout.addStretch()

        # "- Ch1" 라벨 제거 (그룹 제목으로 표시)

        # 채널 선택 드롭다운과 운전 모드 체크박스 (우측에 배치)
        channel_label = QLabel("Channel:")
        channel_label.setStyleSheet("QLabel { margin: 0px; padding: 0px; }")
        control_header_layout.addWidget(channel_label)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["1CH", "2CH"])
        self.channel_combo.setCurrentText("1CH")
        self.channel_combo.setMinimumWidth(60)  # baud/checksum과 비슷한 컴팩트한 크기
        self.channel_combo.currentTextChanged.connect(self.on_channel_changed)
        self.channel_combo.setStyleSheet("""
            QComboBox {
                text-align: center;
                margin: 0px;
                padding: 2px;
            }
            QComboBox QAbstractItemView {
                text-align: center;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
        control_header_layout.addWidget(self.channel_combo)

        self.operation_checkbox = QCheckBox("Parallel Mode")
        self.operation_checkbox.stateChanged.connect(self.on_operation_mode_changed)
        self.operation_checkbox.setStyleSheet("QCheckBox { font-weight: bold; margin: 0px; padding: 0px; }")
        self.operation_checkbox.setEnabled(False)  # 초기에는 비활성화 (1CH 모드)
        control_header_layout.addWidget(self.operation_checkbox)

        # 상태 전환 중 비활성화할 버튼들 등록
        self.transition_buttons = [self.channel_combo, self.operation_checkbox]

        # 헤더를 레이아웃에 추가
        control_header_widget = QWidget()
        control_header_widget.setLayout(control_header_layout)
        control_header_layout.setContentsMargins(6, 0, 6, 0)  # 헤더 상하 마진 완전 제거
        control_header_layout.setSpacing(8)  # 위젯 간 간격 줄이기
        control_header_widget.setContentsMargins(0, 0, 0, 0)  # 위젯 자체 마진 제거
        control_header_widget.setMaximumHeight(35)  # 헤더 최대 높이 제한
        layout.addWidget(control_header_widget)

        # Control Commands 그룹박스 (헤더 없이)
        control_group = QGroupBox()
        control_group_layout = QVBoxLayout(control_group)
        control_group_layout.setContentsMargins(9, 6, 9, 6)  # 상하 마진 줄이기 (기본 9,9,9,9)
        control_group_layout.setSpacing(6)  # 레이아웃 간격 줄이기

        control_layout = QGridLayout()
        control_layout.setContentsMargins(6, 3, 6, 3)  # 그리드 레이아웃 마진 줄이기
        control_layout.setVerticalSpacing(6)  # 세로 간격 줄이기
        control_layout.setHorizontalSpacing(10)  # 가로 간격 유지
        control_group_layout.addLayout(control_layout)
        
        # 0행: Max Voltage(좌측), Current Command(우측)
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
        self.current_spinbox.setRange(-3276.8, 3276.7)
        self.current_spinbox.setDecimals(1)
        self.current_spinbox.setSuffix(" A")
        self.current_spinbox.setValue(0.0)
        self.current_spinbox.setAlignment(Qt.AlignRight)  # 우측 정렬
        # 폰트 크기 증가
        current_font = self.current_spinbox.font()
        current_font.setPointSize(current_font.pointSize() + 2)
        self.current_spinbox.setFont(current_font)
        self.current_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        control_layout.addWidget(self.current_spinbox, 0, 3)
        
        # 1행: Min Voltage(좌측), Start/Stop 버튼(우측)
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
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #BDBDBD; color: #EEEEEE; }"
        )
        self.start_btn.clicked.connect(self.send_start_command)
        control_layout.addWidget(self.start_btn, 1, 2)
        
        self.stop_btn = QPushButton("Stop")
        # 폰트 크기 증가
        stop_font = self.stop_btn.font()
        stop_font.setPointSize(stop_font.pointSize() + 2)
        self.stop_btn.setFont(stop_font)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #BDBDBD; color: #EEEEEE; }"
        )
        self.stop_btn.clicked.connect(self.send_stop_command)
        control_layout.addWidget(self.stop_btn, 1, 3)
        
        # 2행: System Voltage(좌측), System Current(우측)
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
        # 4. 통계 정보
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
        # 5. 상태바 (채널별)
        # ===========================================
        self.status_bar = self.statusBar()
        self.ch1_status_label = QLabel("● CH1: Disconnected")
        self.ch2_status_label = QLabel("● CH2: Disconnected")

        self.status_bar.addWidget(self.ch1_status_label)
        self.status_bar.addPermanentWidget(self.ch2_status_label)

        # 초기에는 CH1만 표시
        self.ch2_status_label.hide()
        
        # 채널1을 메인 레이아웃에 추가
        self.main_layout.addWidget(self.ch1_widget)

        # 채널2 UI 생성 (처음엔 숨김)
        self.create_ch2_ui()

        # 모듈 데이터 저장용 (채널별)
        self.module_rows = [{}, {}]  # 채널별 slave_id -> row_index
        self.module_currents = [{}, {}]  # 채널별 slave_id -> current_value
        self.module_last_update = [{}, {}]  # 채널별 slave_id -> last_update_time

        # DAB_OK 상태 체크 타이머 (1초마다)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_module_status)
        self.status_timer.start(1000)  # 1초마다 체크

    def create_ch2_ui(self):
        """채널2 UI 생성"""
        self.ch2_widget = QWidget()
        ch2_layout = QVBoxLayout(self.ch2_widget)
        ch2_layout.setSpacing(8)  # CH1과 동일한 위젯 간 간격

        # CH2 연결 설정 그룹
        ch2_conn_group = QGroupBox("Connection Settings - Ch2")
        ch2_conn_layout = QGridLayout(ch2_conn_group)

        # 포트 선택
        ch2_port_label_layout = QHBoxLayout()
        ch2_port_label_layout.addWidget(QLabel("Port:"))

        ch2_refresh_btn = QPushButton("refresh")
        ch2_refresh_btn.setToolTip("Refresh port list")
        ch2_refresh_btn.setFixedSize(60, 24)
        ch2_refresh_btn.setStyleSheet("""
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
        ch2_refresh_btn.clicked.connect(self.refresh_ch2_ports)
        ch2_port_label_layout.addWidget(ch2_refresh_btn)
        ch2_port_label_layout.addStretch()

        ch2_port_label_widget = QWidget()
        ch2_port_label_widget.setLayout(ch2_port_label_layout)
        ch2_conn_layout.addWidget(ch2_port_label_widget, 0, 0)

        self.ch2_port_combo = QComboBox()
        self.ch2_port_combo.setMinimumWidth(200)
        self.ch2_port_combo.setStyleSheet("""
            QComboBox {
                text-align: center;
            }
            QComboBox QAbstractItemView {
                text-align: center;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
        ch2_conn_layout.addWidget(self.ch2_port_combo, 0, 1)

        # Baud rate
        ch2_conn_layout.addWidget(QLabel("Baud:"), 0, 2)
        self.ch2_baud_combo = QComboBox()
        self.ch2_baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.ch2_baud_combo.setCurrentText("115200")
        self.ch2_baud_combo.setStyleSheet("""
            QComboBox {
                text-align: right;
            }
            QComboBox QAbstractItemView {
                text-align: right;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
        ch2_conn_layout.addWidget(self.ch2_baud_combo, 0, 3)

        # 체크섬
        ch2_conn_layout.addWidget(QLabel("Checksum:"), 0, 4)
        self.ch2_checksum_combo = QComboBox()
        self.ch2_checksum_combo.addItems(["ON", "OFF"])
        self.ch2_checksum_combo.setCurrentText("ON")
        self.ch2_checksum_combo.setMinimumWidth(80)
        self.ch2_checksum_combo.setStyleSheet("""
            QComboBox {
                text-align: center;
            }
            QComboBox QAbstractItemView {
                text-align: center;
                background: white;
                selection-background-color: #e0e0e0;
                selection-color: black;
            }
        """)
        self.ch2_checksum_combo.currentTextChanged.connect(lambda value: self.on_checksum_changed(value, 1))
        ch2_conn_layout.addWidget(self.ch2_checksum_combo, 0, 5)

        # 연결 버튼
        self.ch2_connect_btn = QPushButton("Disconnected")
        ch2_connect_font = self.ch2_connect_btn.font()
        ch2_connect_font.setPointSize(ch2_connect_font.pointSize() + 2)
        self.ch2_connect_btn.setFont(ch2_connect_font)
        self.ch2_connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
        self.ch2_connect_btn.setFixedWidth(130)
        self.ch2_connect_btn.clicked.connect(self.toggle_ch2_connection)
        ch2_conn_layout.addWidget(self.ch2_connect_btn, 0, 6)

        ch2_layout.addWidget(ch2_conn_group)

        # CH2 Control Commands (CH1과 동일한 구조)
        # CH2 헤더 추가 (독립 라벨 제거)
        ch2_control_header_layout = QHBoxLayout()
        self.ch2_header_label = QLabel("Control Commands - Ch2")
        ch2_control_header_layout.addWidget(self.ch2_header_label)
        ch2_control_header_layout.addStretch()

        # CH2 헤더를 레이아웃에 추가
        self.ch2_control_header_widget = QWidget()
        self.ch2_control_header_widget.setLayout(ch2_control_header_layout)
        ch2_control_header_layout.setContentsMargins(6, 0, 6, 0)  # CH1과 동일한 마진
        ch2_control_header_layout.setSpacing(8)  # CH1과 동일한 간격
        self.ch2_control_header_widget.setContentsMargins(0, 0, 0, 0)
        self.ch2_control_header_widget.setMaximumHeight(35)  # CH1과 동일한 높이 제한
        ch2_layout.addWidget(self.ch2_control_header_widget)

        # CH2 Control Commands 그룹박스 (헤더 없이)
        self.ch2_control_group = QGroupBox()
        self.create_ch2_control_commands()
        ch2_layout.addWidget(self.ch2_control_group)

        # CH2 통계 정보
        self.ch2_stats_label = QLabel("Connected: No | Modules: 0 | Packets: 0")
        self.ch2_stats_label.setStyleSheet("QLabel { background-color: #E3F2FD; padding: 8px; border: 1px solid #BBDEFB; }")
        ch2_layout.addWidget(self.ch2_stats_label)

        # CH2 데이터 테이블
        ch2_table_group = QGroupBox("Slave Module Data - Ch2")
        ch2_table_layout = QVBoxLayout(ch2_table_group)

        self.ch2_table = QTableWidget()
        self.ch2_table.setColumnCount(5)
        self.ch2_table.setHorizontalHeaderLabels(['ID', 'DAB_OK', 'Current (A)', 'Temp (°C)', 'Update'])

        ch2_header = self.ch2_table.horizontalHeader()
        ch2_header.setSectionResizeMode(QHeaderView.Interactive)
        ch2_header.setDefaultAlignment(Qt.AlignCenter)

        self.ch2_table.setColumnWidth(0, 60)
        self.ch2_table.setColumnWidth(1, 100)
        self.ch2_table.setColumnWidth(2, 240)
        self.ch2_table.setColumnWidth(3, 240)
        self.ch2_table.setColumnWidth(4, 120)

        self.ch2_table.setAlternatingRowColors(True)
        self.ch2_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ch2_table.verticalHeader().setVisible(False)
        self.ch2_table.verticalHeader().setDefaultSectionSize(35)
        ch2_header.setFixedHeight(40)

        ch2_table_layout.addWidget(self.ch2_table)
        ch2_layout.addWidget(ch2_table_group)

        # CH2 버튼
        ch2_btn_layout = QHBoxLayout()

        ch2_add_btn = QPushButton("+")
        ch2_add_btn.setFixedSize(60, 30)
        ch2_add_btn.setToolTip("Add Test Module")
        ch2_add_btn.clicked.connect(lambda: self.add_test_module(1))
        ch2_btn_layout.addWidget(ch2_add_btn)

        ch2_remove_btn = QPushButton("-")
        ch2_remove_btn.setFixedSize(60, 30)
        ch2_remove_btn.setToolTip("Remove Last Module")
        ch2_remove_btn.clicked.connect(lambda: self.remove_last_module(1))
        ch2_btn_layout.addWidget(ch2_remove_btn)

        ch2_btn_layout.addStretch()

        ch2_reset_btn = QPushButton("Reset")
        ch2_reset_btn.clicked.connect(lambda: self.reset_to_initial(1))
        ch2_btn_layout.addWidget(ch2_reset_btn)

        ch2_layout.addLayout(ch2_btn_layout)

        # 처음엔 숨김
        self.ch2_widget.hide()

    def create_ch2_control_commands(self):
        """CH2 Control Commands 생성"""
        # CH1과 동일한 레이아웃 구조 적용
        ch2_control_group_layout = QVBoxLayout(self.ch2_control_group)
        ch2_control_group_layout.setContentsMargins(9, 6, 9, 6)  # CH1과 동일한 상하 마진
        ch2_control_group_layout.setSpacing(6)  # CH1과 동일한 레이아웃 간격

        ch2_control_layout = QGridLayout()
        ch2_control_layout.setContentsMargins(6, 3, 6, 3)  # CH1과 동일한 그리드 마진
        ch2_control_layout.setVerticalSpacing(6)  # CH1과 동일한 세로 간격
        ch2_control_layout.setHorizontalSpacing(10)  # CH1과 동일한 가로 간격
        ch2_control_group_layout.addLayout(ch2_control_layout)

        # 0행: Max Voltage, Current Command
        self.ch2_max_voltage_label = QLabel("Max Voltage:")
        self.ch2_max_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ch2_control_layout.addWidget(self.ch2_max_voltage_label, 0, 0)

        self.ch2_max_voltage_spinbox = QDoubleSpinBox()
        self.ch2_max_voltage_spinbox.setRange(0.0, 1000.0)
        self.ch2_max_voltage_spinbox.setDecimals(1)
        self.ch2_max_voltage_spinbox.setSuffix(" V")
        self.ch2_max_voltage_spinbox.setValue(500.0)
        self.ch2_max_voltage_spinbox.setAlignment(Qt.AlignRight)
        # 폰트 크기 증가 및 우측 여백 설정
        ch2_spinbox_font = self.ch2_max_voltage_spinbox.font()
        ch2_spinbox_font.setPointSize(ch2_spinbox_font.pointSize() + 2)
        self.ch2_max_voltage_spinbox.setFont(ch2_spinbox_font)
        self.ch2_max_voltage_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        ch2_control_layout.addWidget(self.ch2_max_voltage_spinbox, 0, 1)

        self.ch2_current_label = QLabel("Current Command:")
        self.ch2_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ch2_control_layout.addWidget(self.ch2_current_label, 0, 2)

        self.ch2_current_spinbox = QDoubleSpinBox()
        self.ch2_current_spinbox.setRange(-3276.8, 3276.7)
        self.ch2_current_spinbox.setDecimals(1)
        self.ch2_current_spinbox.setSuffix(" A")
        self.ch2_current_spinbox.setValue(0.0)
        self.ch2_current_spinbox.setAlignment(Qt.AlignRight)
        # 폰트 크기 증가 및 우측 여백 설정
        ch2_current_font = self.ch2_current_spinbox.font()
        ch2_current_font.setPointSize(ch2_current_font.pointSize() + 2)
        self.ch2_current_spinbox.setFont(ch2_current_font)
        self.ch2_current_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        ch2_control_layout.addWidget(self.ch2_current_spinbox, 0, 3)

        # 1행: Min Voltage, Start/Stop
        self.ch2_min_voltage_label = QLabel("Min Voltage:")
        self.ch2_min_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ch2_control_layout.addWidget(self.ch2_min_voltage_label, 1, 0)

        self.ch2_min_voltage_spinbox = QDoubleSpinBox()
        self.ch2_min_voltage_spinbox.setRange(0.0, 1000.0)
        self.ch2_min_voltage_spinbox.setDecimals(1)
        self.ch2_min_voltage_spinbox.setSuffix(" V")
        self.ch2_min_voltage_spinbox.setValue(0.0)
        self.ch2_min_voltage_spinbox.setAlignment(Qt.AlignRight)
        # 폰트 크기 증가 및 우측 여백 설정
        ch2_min_font = self.ch2_min_voltage_spinbox.font()
        ch2_min_font.setPointSize(ch2_min_font.pointSize() + 2)
        self.ch2_min_voltage_spinbox.setFont(ch2_min_font)
        self.ch2_min_voltage_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        ch2_control_layout.addWidget(self.ch2_min_voltage_spinbox, 1, 1)

        self.ch2_start_btn = QPushButton("Command")
        # 폰트 크기 증가
        ch2_start_font = self.ch2_start_btn.font()
        ch2_start_font.setPointSize(ch2_start_font.pointSize() + 2)
        self.ch2_start_btn.setFont(ch2_start_font)
        self.ch2_start_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; }")
        self.ch2_start_btn.clicked.connect(lambda: self.send_start_command(1))
        ch2_control_layout.addWidget(self.ch2_start_btn, 1, 2)

        self.ch2_stop_btn = QPushButton("Stop")
        # 폰트 크기 증가
        ch2_stop_font = self.ch2_stop_btn.font()
        ch2_stop_font.setPointSize(ch2_stop_font.pointSize() + 2)
        self.ch2_stop_btn.setFont(ch2_stop_font)
        self.ch2_stop_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; font-weight: bold; }")
        self.ch2_stop_btn.clicked.connect(lambda: self.send_stop_command(1))
        ch2_control_layout.addWidget(self.ch2_stop_btn, 1, 3)

        # 2행: System Voltage, System Current
        self.ch2_sys_voltage_label = QLabel("System Voltage:")
        self.ch2_sys_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ch2_control_layout.addWidget(self.ch2_sys_voltage_label, 2, 0)

        self.ch2_system_voltage_label = QLabel("---          ")
        ch2_voltage_font = self.font()
        ch2_voltage_font.setPointSize(int(ch2_voltage_font.pointSize() * 1.5))
        self.ch2_system_voltage_label.setFont(ch2_voltage_font)
        self.ch2_system_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ch2_system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        ch2_control_layout.addWidget(self.ch2_system_voltage_label, 2, 1)

        self.ch2_sys_current_label = QLabel("System Current:")
        self.ch2_sys_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ch2_control_layout.addWidget(self.ch2_sys_current_label, 2, 2)

        self.ch2_system_current_label = QLabel("---          ")
        ch2_current_font = self.font()
        ch2_current_font.setPointSize(int(ch2_current_font.pointSize() * 1.5))
        self.ch2_system_current_label.setFont(ch2_current_font)
        self.ch2_system_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.ch2_system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        ch2_control_layout.addWidget(self.ch2_system_current_label, 2, 3)

        # CH2 컨트롤 위젯들을 리스트로 저장 (병렬 모드에서 비활성화하기 위해)
        self.ch2_control_widgets = [
            self.ch2_max_voltage_spinbox, self.ch2_min_voltage_spinbox,
            self.ch2_current_spinbox, self.ch2_start_btn, self.ch2_stop_btn
        ]

    def add_slave_module(self, slave_id, current, temp, dab_ok, timestamp, channel=0):
        """슬레이브 모듈 데이터 추가/업데이트 (채널별)"""
        table = self.table if channel == 0 else self.ch2_table
        module_rows = self.module_rows[channel]
        module_currents = self.module_currents[channel]
        module_last_update = self.module_last_update[channel]

        # 모듈이 테이블에 없으면 새 행 추가
        if slave_id not in module_rows:
            row = table.rowCount()
            table.insertRow(row)
            module_rows[slave_id] = row

        row = module_rows[slave_id]
        
        # 마지막 업데이트 시간 기록 (현재 시간)
        module_last_update[slave_id] = time.time()

        # 데이터 업데이트 (열 순서 변경: ID, DAB_OK, Current, Temp, Update)

        # ID (중앙정렬)
        id_item = QTableWidgetItem(str(slave_id))
        id_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, id_item)

        # DAB_OK (중앙정렬) - 실시간 데이터이므로 정상 색상으로 표시
        dab_item = QTableWidgetItem("✓" if dab_ok else "✗")
        dab_item.setTextAlignment(Qt.AlignCenter)
        if dab_ok:
            dab_item.setBackground(QColor(200, 255, 200))  # 녹색
        else:
            dab_item.setBackground(QColor(255, 200, 200))  # 빨간색
        table.setItem(row, 1, dab_item)

        # Current (우측 여백 1.5배 증가)
        current_item = QTableWidgetItem(f"{current:.2f} A                 ")
        current_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row, 2, current_item)

        # Temp (우측 여백 1.5배 증가)
        temp_item = QTableWidgetItem(f"{temp:.1f} °C                 ")
        temp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        table.setItem(row, 3, temp_item)

        # Update (중앙정렬)
        update_item = QTableWidgetItem(timestamp)
        update_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 4, update_item)

        # 모듈 전류 저장 및 시스템 전류 합계 업데이트
        module_currents[slave_id] = current
        self.update_system_current(channel)
        
    def check_module_status(self):
        """모듈 상태 체크 - 1초 이상 업데이트가 없으면 회색으로 표시, 5초 이상이면 값 초기화"""
        if not any(self.connected):
            return

        current_time = time.time()

        # 채널별로 처리
        for channel in range(2):
            if not self.connected[channel]:
                continue

            table = self.table if channel == 0 else self.ch2_table
            module_rows = self.module_rows[channel]
            module_currents = self.module_currents[channel]
            module_last_update = self.module_last_update[channel]

            for slave_id, row in module_rows.items():
                if slave_id in module_last_update:
                    time_since_update = current_time - module_last_update[slave_id]

                    # 1초 이상 업데이트가 없으면 회색으로 변경
                    if time_since_update >= 1.0:
                        dab_item = table.item(row, 1)  # DAB_OK 컬럼
                        if dab_item:
                            dab_item.setBackground(QColor(200, 200, 200))  # 회색

                    # 5초 이상 업데이트가 없으면 해당 모듈의 값을 초기화
                    if time_since_update >= 5.0:
                        # Current를 0.00으로 초기화
                        current_item = table.item(row, 2)
                        if current_item:
                            current_item.setText("0.00 A                 ")

                        # Temp를 0.0으로 초기화
                        temp_item = table.item(row, 3)
                        if temp_item:
                            temp_item.setText("0.0 °C                 ")

                        # DAB_OK를 ✗로 초기화 (회색 배경 유지)
                        dab_item = table.item(row, 1)
                        if dab_item:
                            dab_item.setText("✗")
                            dab_item.setBackground(QColor(200, 200, 200))  # 회색 유지

                        # Update time을 "--:--:--"로 초기화
                        update_item = table.item(row, 4)
                        if update_item:
                            update_item.setText("--:--:--")

                        # 해당 모듈의 전류를 0으로 초기화하고 시스템 전류 업데이트
                        if slave_id in module_currents:
                            module_currents[slave_id] = 0.0
                            self.update_system_current(channel)
        
    def create_initial_modules(self, channel=0):
        """초기 실행시 10개 모듈 생성"""
        for i in range(1, 11):  # ID 1부터 10까지
            self.add_slave_module(i, 0.0, 0.0, False, "--:--:--", channel)
        
    def get_display_port_name(self, device_path):
        """상태바 표시용 깔끔한 포트 이름"""
        # 콤보박스에서 현재 선택된 표시명 가져오기
        for i in range(self.port_combo.count()):
            if self.port_combo.itemData(i) == device_path:
                return self.port_combo.itemText(i)
        # 찾지 못하면 원래 이름 반환
        return device_path

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
        """연결/해제 토글 (CH1)"""
        if not self.connected[0]:
            self.connect_serial(0)  # 채널 0 (CH1)
        else:
            self.disconnect_serial(0)  # 채널 0 (CH1)
            
    def connect_serial(self, channel=0):
        """시리얼 포트 연결 (채널별)"""
        # 콤보박스에서 실제 포트 경로 가져오기
        port = self.port_combo.currentData()  # 실제 포트 경로 (/dev/cu.xxx)
        if not port:  # currentData()가 없으면 텍스트 사용 (호환성)
            port = self.port_combo.currentText()

        baud = int(self.baud_combo.currentText())

        if not port:
            QMessageBox.warning(self, "Warning", "Please select a port")
            return

        # 워커와 스레드 생성
        self.serial_workers[channel] = SerialWorker(self, channel)
        self.serial_threads[channel] = QThread()

        # 워커를 스레드로 이동
        self.serial_workers[channel].moveToThread(self.serial_threads[channel])

        # 시그널 연결
        self.serial_workers[channel].slave_data_received.connect(self.update_slave_data)
        self.serial_workers[channel].system_voltage_received.connect(self.update_system_voltage)
        self.serial_threads[channel].started.connect(self.serial_workers[channel].read_serial)

        # 시리얼 포트 연결
        if self.serial_workers[channel].connect_serial(port, baud):
            self.connected[channel] = True
            self.serial_threads[channel].start()

            # UI 업데이트 (CH1만)
            if channel == 0:
                self.connect_btn.setText("Connected")
                self.connect_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; }")
                self.ch1_status_label.setText(f"● CH1: Connected to {self.get_display_port_name(port)}")
            else:
                self.ch2_status_label.setText(f"● CH2: Connected to {self.get_display_port_name(port)}")

                # 연결됨 - 대기 상태로 표시 (회색 - 데이터 없음)
                self.system_voltage_label.setText("0.0 V          ")
                self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색 - 데이터 대기
                self.system_current_label.setText("0.0 A          ")
                self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색 - 데이터 대기

            print(f"CH{channel+1} Connected to {port} at {baud} baud")
        else:
            QMessageBox.critical(self, "Error", f"Failed to connect CH{channel+1} to {port}")
            # 연결 실패시 재시도 타이머 시작 (최대 횟수 제한)
            if self.reconnect_attempts[channel] < self.max_reconnect_attempts:
                self.reconnect_attempts[channel] += 1
                if not hasattr(self, 'reconnect_timers'):
                    self.reconnect_timers = [None, None]
                if self.reconnect_timers[channel] is None:
                    self.reconnect_timers[channel] = QTimer()
                    self.reconnect_timers[channel].setSingleShot(True)
                    self.reconnect_timers[channel].timeout.connect(lambda ch=channel: self.retry_connection(ch))
                self.reconnect_timers[channel].start(5000)  # 5초 후 재시도
                print(f"CH{channel+1} will retry connection in 5 seconds... (Attempt {self.reconnect_attempts[channel]}/{self.max_reconnect_attempts})")
            else:
                print(f"CH{channel+1} maximum reconnection attempts ({self.max_reconnect_attempts}) reached. Please check hardware.")
            
    def disconnect_serial(self, channel=0):
        """시리얼 포트 연결 해제 (채널별)"""
        self.connected[channel] = False  # 먼저 연결 상태 변경

        if self.serial_workers[channel]:
            self.serial_workers[channel].disconnect_serial()

        if self.serial_threads[channel]:
            self.serial_threads[channel].quit()
            if not self.serial_threads[channel].wait(THREAD_WAIT_TIMEOUT_MS):
                print(f"⚠️ CH{channel+1} thread did not terminate gracefully within {THREAD_WAIT_TIMEOUT_MS}ms")
                # 강제 종료는 위험하므로 로그만 남기고 계속 진행

        # 워커와 스레드 완전히 정리
        self.serial_workers[channel] = None
        self.serial_threads[channel] = None

        # UI 업데이트 (채널별)
        if channel == 0:
            self.connect_btn.setText("Disconnected")
            self.connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
            self.ch1_status_label.setText("● CH1: Disconnected")
        else:
            self.ch2_connect_btn.setText("Disconnected")
            self.ch2_connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
            self.ch2_status_label.setText("● CH2: Disconnected")

            # 연결 해제 - 미연결 상태로 표시
            self.system_voltage_label.setText("---          ")
            self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색
            self.system_current_label.setText("---          ")
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")  # 회색
            self.has_received_data = False

        print(f"CH{channel+1} Disconnected - 스레드 정리 완료")

    def process_queued_signals(self):
        """대기 중인 신호들을 배치 처리"""
        if not self.signal_queue:
            return

        # 배치 크기만큼 신호 처리
        batch_count = min(len(self.signal_queue), SIGNAL_BATCH_SIZE)

        for _ in range(batch_count):
            signal_data = self.signal_queue.popleft()
            signal_type = signal_data['type']

            if signal_type == 'slave_data':
                self._process_slave_data_immediate(
                    signal_data['channel'], signal_data['slave_id'],
                    signal_data['current'], signal_data['temp'],
                    signal_data['dab_ok'], signal_data['timestamp']
                )
            elif signal_type == 'system_voltage':
                self._process_system_voltage_immediate(
                    signal_data['channel'], signal_data['voltage'],
                    signal_data['timestamp']
                )

        # 큐가 너무 가득 찬 경우 경고
        if len(self.signal_queue) > MAX_QUEUED_SIGNALS * 0.8:
            print(f"⚠️ Signal queue getting full: {len(self.signal_queue)}/{MAX_QUEUED_SIGNALS}")

    @pyqtSlot(int, int, float, float, bool, str)
    def update_slave_data(self, channel, slave_id, current, temp, dab_ok, timestamp):
        """슬레이브 데이터 업데이트 - 레이트 리미팅 적용"""
        if not self.connected[channel]:
            return

        # 신호를 큐에 추가 (즉시 처리 대신 배치 처리)
        signal_data = {
            'type': 'slave_data',
            'channel': channel,
            'slave_id': slave_id,
            'current': current,
            'temp': temp,
            'dab_ok': dab_ok,
            'timestamp': timestamp
        }

        # 큐가 가득 찬 경우 가장 오래된 신호 제거
        if len(self.signal_queue) >= MAX_QUEUED_SIGNALS:
            dropped_signal = self.signal_queue.popleft()
            print(f"⚠️ Signal dropped due to queue overflow: {dropped_signal['type']}")

        self.signal_queue.append(signal_data)

    def _process_slave_data_immediate(self, channel, slave_id, current, temp, dab_ok, timestamp):
        """슬레이브 데이터 즉시 처리 (내부 사용)"""
        self.packet_count[channel] += 1
        self.add_slave_module(slave_id, current, temp, dab_ok, timestamp, channel)
        self.update_stats()
        
    @pyqtSlot(int, float, str)
    def update_system_voltage(self, channel, voltage, timestamp):
        """시스템 전압 업데이트 - 레이트 리미팅 적용"""
        if not self.connected[channel]:
            return

        # 신호를 큐에 추가 (즉시 처리 대신 배치 처리)
        signal_data = {
            'type': 'system_voltage',
            'channel': channel,
            'voltage': voltage,
            'timestamp': timestamp
        }

        # 큐가 가득 찬 경우 가장 오래된 신호 제거
        if len(self.signal_queue) >= MAX_QUEUED_SIGNALS:
            dropped_signal = self.signal_queue.popleft()
            print(f"⚠️ Signal dropped due to queue overflow: {dropped_signal['type']}")

        self.signal_queue.append(signal_data)

    def _process_system_voltage_immediate(self, channel, voltage, timestamp):
        """시스템 전압 즉시 처리 (내부 사용)"""
        # CH1 전압은 기본 시스템 전압으로 사용
        if channel == 0:
            self.system_voltage = voltage
            self.system_voltage_label.setText(f"{voltage:.1f} V          ")
            self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #2E7D32; }")  # 녹색 - 데이터 수신
            self.has_received_data = True
        else:
            # CH2 전압 표시
            if hasattr(self, 'ch2_system_voltage_label'):
                self.ch2_system_voltage_label.setText(f"{voltage:.1f} V          ")
                self.ch2_system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #2E7D32; }")

        self.packet_count[channel] += 1
        self.update_stats()
    
    def update_system_current(self, channel=0):
        """시스템 전류 합계 업데이트 (채널별)"""
        if channel == 0:
            self.system_current = sum(self.module_currents[0].values())
            self.system_current_label.setText(f"{self.system_current:.2f} A          ")
            if self.has_received_data:
                self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #1976D2; }")  # 파란색 - 데이터 수신
        else:
            ch2_system_current = sum(self.module_currents[1].values())
            self.ch2_system_current_label.setText(f"{ch2_system_current:.2f} A          ")
            if self.has_received_data:
                self.ch2_system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #1976D2; }")  # 파란색 - 데이터 수신
    
    def update_stats(self):
        """통계 정보 업데이트"""
        # CH1 통계 업데이트
        connected_status = 'Yes' if self.connected[0] else 'No'
        modules_count = len(self.module_rows[0])

        # 병렬 모드 표시 추가
        mode_text = ""
        if self.channel_count == 2 and self.operation_mode == "Parallel":
            mode_text = " | Mode: Parallel"
        elif self.channel_count == 2:
            mode_text = " | Mode: Independent"

        # CH1 체크섬 통계 추가
        ch1_checksum_stats = self.get_checksum_statistics(0)
        checksum_text = ""
        if ch1_checksum_stats['total_errors'] > 0:
            checksum_text = f" | Errors: {ch1_checksum_stats['total_errors']}"
            if ch1_checksum_stats['consecutive_errors'] > 0:
                checksum_text += f"({ch1_checksum_stats['consecutive_errors']} cons)"
            if ch1_checksum_stats['recent_error_rate'] > 0:
                checksum_text += f", Rate: {ch1_checksum_stats['recent_error_rate']:.1%}"

        self.stats_label.setText(f"Connected: {connected_status} | Modules: {modules_count} | Packets: {self.packet_count[0]}{checksum_text}{mode_text}")

        # CH2 통계 업데이트 (2채널 모드일 때만)
        if self.channel_count == 2 and hasattr(self, 'ch2_stats_label'):
            ch2_connected_status = 'Yes' if self.connected[1] else 'No'
            ch2_modules_count = len(self.module_rows[1])
            ch2_mode_text = ""
            if self.operation_mode == "Parallel":
                ch2_mode_text = " | Mode: Feedback Only"
            elif self.operation_mode == "Independent":
                ch2_mode_text = " | Mode: Independent"

            # CH2 체크섬 통계 추가
            ch2_checksum_stats = self.get_checksum_statistics(1)
            ch2_checksum_text = ""
            if ch2_checksum_stats['total_errors'] > 0:
                ch2_checksum_text = f" | Errors: {ch2_checksum_stats['total_errors']}"
                if ch2_checksum_stats['consecutive_errors'] > 0:
                    ch2_checksum_text += f"({ch2_checksum_stats['consecutive_errors']} cons)"
                if ch2_checksum_stats['recent_error_rate'] > 0:
                    ch2_checksum_text += f", Rate: {ch2_checksum_stats['recent_error_rate']:.1%}"

            self.ch2_stats_label.setText(f"Connected: {ch2_connected_status} | Modules: {ch2_modules_count} | Packets: {self.packet_count[1]}{ch2_checksum_text}{ch2_mode_text}")
        
    def add_test_module(self):
        """테스트 모듈 추가 (수동으로만)"""
        next_id = len(self.module_rows) + 1
        if next_id > 31:  # 5비트 ID 최대값
            QMessageBox.warning(self, "Warning", "Maximum 31 modules reached")
            return
        
        # 깔끔한 초기값 설정 (0A, 0°C)
        self.add_slave_module(next_id, 0.0, 0.0, False, "--:--:--", channel)
        self.update_stats(channel)
        print(f"CH{channel+1} 테스트 모듈 ID {next_id} 추가됨")
        
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
        print(f"CH{channel+1} 모듈 ID {max_id} 제거됨")
        
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
        
        # update_stats()로 통일
        self.update_stats()
        
        # 상태 초기화
        self.values_changed = False
        self.changed_spinboxes.clear()
        self.start_btn.setText("Command")
        self.restore_spinbox_colors()
        
        # 원래 값 초기화
        self.original_values[self.max_voltage_spinbox] = 500.0
        self.original_values[self.min_voltage_spinbox] = 0.0
        self.original_values[self.current_spinbox] = 0.0
        
        print(f"CH{channel+1} 초기 상태로 리셋됨 (10개 모듈)")

    def track_checksum_error(self, channel, frame_data):
        """체크섬 에러 추적 및 통계 업데이트"""
        import time

        # 에러 카운터 증가
        self.checksum_error_count[channel] += 1
        self.checksum_consecutive_errors[channel] += 1

        # 에러 이력에 추가 (True = 에러)
        self.checksum_error_history[channel].append(True)

        # 에러율 계산
        if len(self.checksum_error_history[channel]) > 0:
            error_rate = sum(self.checksum_error_history[channel]) / len(self.checksum_error_history[channel])
        else:
            error_rate = 0.0

        # 연속 에러 알림
        if self.checksum_consecutive_errors[channel] >= CHECKSUM_ERROR_ALERT_THRESHOLD:
            current_time = time.time()
            # 1분에 한 번만 알림 (스팸 방지)
            if current_time - self.last_checksum_alert_time[channel] > 60:
                print(f"🚨 CH{channel+1} HIGH CHECKSUM ERROR RATE: {self.checksum_consecutive_errors[channel]} consecutive errors, rate={error_rate:.1%}")
                self.last_checksum_alert_time[channel] = current_time

        # 에러율 알림
        if error_rate >= CHECKSUM_ERROR_RATE_ALERT:
            current_time = time.time()
            if current_time - self.last_checksum_alert_time[channel] > 60:
                print(f"⚠️ CH{channel+1} checksum error rate alert: {error_rate:.1%} (threshold: {CHECKSUM_ERROR_RATE_ALERT:.1%})")
                self.last_checksum_alert_time[channel] = current_time

    def track_checksum_success(self, channel):
        """체크섬 성공 추적 (연속 에러 카운터 리셋)"""
        # 성공 시 연속 에러 카운터 리셋
        if self.checksum_consecutive_errors[channel] > 0:
            print(f"✅ CH{channel+1} checksum error recovery: {self.checksum_consecutive_errors[channel]} errors cleared")
            self.checksum_consecutive_errors[channel] = 0

        # 에러 이력에 추가 (False = 성공)
        self.checksum_error_history[channel].append(False)

    def track_packet_received(self, channel):
        """패킷 수신 추적 (총 패킷 수 증가)"""
        self.checksum_total_packets[channel] += 1

    def get_checksum_statistics(self, channel):
        """체크섬 통계 반환"""
        total_packets = self.checksum_total_packets[channel]
        total_errors = self.checksum_error_count[channel]
        consecutive_errors = self.checksum_consecutive_errors[channel]

        if total_packets > 0:
            overall_error_rate = total_errors / total_packets
        else:
            overall_error_rate = 0.0

        if len(self.checksum_error_history[channel]) > 0:
            recent_error_rate = sum(self.checksum_error_history[channel]) / len(self.checksum_error_history[channel])
        else:
            recent_error_rate = 0.0

        return {
            'total_packets': total_packets,
            'total_errors': total_errors,
            'consecutive_errors': consecutive_errors,
            'overall_error_rate': overall_error_rate,
            'recent_error_rate': recent_error_rate
        }

    def begin_state_transition(self):
        """원자적 상태 전환 시작 - 버튼 비활성화 및 잠금 설정"""
        if self.state_transition_lock:
            return False  # 이미 전환 중

        self.state_transition_lock = True

        # 전환 중 모든 버튼들 비활성화
        for button in self.transition_buttons:
            if button and button.isEnabled():
                button.setEnabled(False)

        return True

    def end_state_transition(self):
        """원자적 상태 전환 완료 - 잠금 해제 및 버튼 활성화"""
        self.state_transition_lock = False

        # 상태에 따라 버튼들 적절히 활성화
        self.channel_combo.setEnabled(True)

        # operation_checkbox는 2CH 모드에서만 활성화
        if self.channel_count == 2:
            self.operation_checkbox.setEnabled(True)
        else:
            self.operation_checkbox.setEnabled(False)

    def rollback_state_transition(self, previous_channel_count, previous_operation_mode):
        """상태 전환 실패 시 롤백"""
        try:
            print(f"⚠️ State transition failed, rolling back...")
            self.channel_count = previous_channel_count
            self.operation_mode = previous_operation_mode

            # UI 상태 복원
            self.channel_combo.setCurrentText(f"{previous_channel_count}CH")
            self.operation_checkbox.setChecked(previous_operation_mode == "Parallel")

            # 잠금 해제
            self.end_state_transition()
        except Exception as e:
            print(f"❌ Rollback failed: {e}")

    def start_resize_performance_tracking(self):
        """리사이즈 성능 추적 시작"""
        import time
        self.last_resize_start = time.time()

    def end_resize_performance_tracking(self):
        """리사이즈 성능 추적 완료 및 적응적 지연 시간 계산"""
        if self.last_resize_start == 0:
            return

        import time
        resize_duration = (time.time() - self.last_resize_start) * 1000  # ms 단위
        self.resize_performance_samples.append(resize_duration)

        # 평균 성능을 기반으로 적응적 지연 시간 계산
        if len(self.resize_performance_samples) >= 2:
            avg_duration = sum(self.resize_performance_samples) / len(self.resize_performance_samples)

            # 평균 지연시간의 1.5배를 적응적 지연으로 사용 (버퍼 포함)
            self.adaptive_resize_delay = max(
                RESIZE_BASE_DELAY_MS,
                min(RESIZE_MAX_DELAY_MS, int(avg_duration * 1.5))
            )

            print(f"📊 Resize performance: avg={avg_duration:.1f}ms, adaptive_delay={self.adaptive_resize_delay}ms")

        self.last_resize_start = 0

    def adaptive_window_resize(self, x, y, width, height, reason=""):
        """적응적 창 크기 조정"""
        self.start_resize_performance_tracking()

        try:
            # 즉시 리사이즈 (2CH 모드 확장 시)
            if width > WINDOW_SIZE_1CH[0]:
                self.setGeometry(x, y, width, height)
                self.end_resize_performance_tracking()
                print(f"✅ Immediate resize to {width}x{height} {reason}")
            else:
                # 지연 리사이즈 (1CH 모드 축소 시)
                delay = self.adaptive_resize_delay
                print(f"⏳ Delayed resize to {width}x{height} in {delay}ms {reason}")

                def delayed_resize():
                    self.setGeometry(x, y, width, height)
                    self.end_resize_performance_tracking()
                    print(f"✅ Completed delayed resize to {width}x{height}")

                QTimer.singleShot(delay, delayed_resize)

        except Exception as e:
            print(f"❌ Window resize failed: {e}")
            self.end_resize_performance_tracking()

    def toggle_channel_mode(self):
        """원자적 채널 모드 전환 (1CH ↔ 2CH)"""
        # 상태 전환 시작 (이미 전환 중이면 무시)
        if not self.begin_state_transition():
            print("⚠️ Channel mode transition already in progress, ignoring...")
            return

        # 현재 상태 백업 (롤백용)
        previous_channel_count = self.channel_count
        previous_operation_mode = self.operation_mode

        try:
            if self.channel_count == 1:
                # 1CH → 2CH 전환
                self.channel_count = 2
                # 드롭다운 업데이트
                self.channel_combo.setCurrentText("2CH")
                # CH1 그룹 제목 업데이트
                self.update_ch1_group_titles(True)
                # 2채널 UI 표시
                self.main_layout.addWidget(self.ch2_widget)
                self.ch2_widget.show()
                # 포트 목록 새로고침
                self.refresh_ch2_ports()
                # 초기 모듈 생성
                self.create_initial_modules(1)
                # 창 크기 조정
                self.adaptive_window_resize(100, 100, 1640, 850, "(1CH→2CH)")
                # CH2 상태바 표시
                self.ch2_status_label.show()
                print("✅ 2채널 모드로 전환 완료")
            else:
                # 2CH → 1CH 전환
                self.channel_count = 1
                # 드롭다운 업데이트
                self.channel_combo.setCurrentText("1CH")
                # Parallel Mode 체크박스 비활성화 및 Independent로 리셋
                self.operation_checkbox.setChecked(False)
                self.operation_mode = "Independent"
                # CH1 그룹 제목 원복
                self.update_ch1_group_titles(False)
                # 2채널 연결 해제
                if self.connected[1]:
                    self.disconnect_serial(1)
                # 2채널 UI 숨김
                self.ch2_widget.hide()
                self.main_layout.removeWidget(self.ch2_widget)
                # CH2 상태바 숨김
                self.ch2_status_label.hide()
                # 창 크기 원복 (적응적 지연으로 레이아웃 업데이트 후 크기 조정)
                self.adaptive_window_resize(100, 100, 820, 850, "(2CH→1CH)")
                print("✅ 1채널 모드로 전환 완료")

            # 상태 전환 완료
            self.end_state_transition()

        except Exception as e:
            print(f"❌ Channel mode transition failed: {e}")
            # 롤백 수행
            self.rollback_state_transition(previous_channel_count, previous_operation_mode)

    def refresh_ch2_ports(self):
        """CH2 포트 목록 새로고침"""
        self.ch2_port_combo.clear()
        all_ports = serial.tools.list_ports.comports()

        # CH1과 동일한 필터링 로직 사용
        serial_keywords = [
            'usbserial', 'tty.usb', 'COM', 'FTDI', 'CP210', 'CH340', 'PL2303', 'Serial', 'UART'
        ]
        exclude_keywords = ['bluetooth', 'debug-console', 'focal', 'airpods']

        filtered_ports = []
        for port in all_ports:
            port_info = f"{port.device} {port.description} {port.manufacturer or ''}".lower()
            if any(exclude_keyword.lower() in port_info for exclude_keyword in exclude_keywords):
                continue
            if any(keyword.lower() in port_info for keyword in serial_keywords):
                display_name = self.get_clean_port_name(port.device, port.description)
                filtered_ports.append((port.device, display_name))

        if not filtered_ports:
            filtered_ports = [(port.device, port.device) for port in all_ports]

        for device_path, display_name in filtered_ports:
            self.ch2_port_combo.addItem(display_name, device_path)

    def toggle_ch2_connection(self):
        """CH2 연결/해제 토글"""
        if not self.connected[1]:
            self.connect_ch2_serial()
        else:
            self.disconnect_serial(1)

    def connect_ch2_serial(self):
        """CH2 시리얼 포트 연결"""
        port = self.ch2_port_combo.currentData()
        if not port:
            port = self.ch2_port_combo.currentText()

        if not port:
            QMessageBox.warning(self, "Warning", "Please select a port for CH2")
            return

        # 채널 1로 연결 시도
        self.connect_serial(1)

        # UI 업데이트 (CH2 전용)
        if self.connected[1]:
            self.ch2_connect_btn.setText("Connected")
            self.ch2_connect_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; }")
            self.ch2_system_voltage_label.setText("0.0 V          ")
            self.ch2_system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
            self.ch2_system_current_label.setText("---          ")
            self.ch2_system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")

    def update_ch1_group_titles(self, add_ch1_suffix):
        """CH1 그룹 제목 업데이트 (2CH 모드일 때 - Ch1 접미사 추가/제거)"""
        if add_ch1_suffix:
            # 2CH 모드: - Ch1 접미사 추가
            for child in self.findChildren(QGroupBox):
                if child.title() == "Connection Settings":
                    child.setTitle("Connection Settings - Ch1")
                elif child.title() == "Slave Module Data":
                    child.setTitle("Slave Module Data - Ch1")
            # Control Commands 헤더에도 Ch1 추가
            if hasattr(self, 'control_header_label'):
                self.control_header_label.setText("Control Commands - Ch1")
        else:
            # 1CH 모드: 원래 제목으로 복원
            for child in self.findChildren(QGroupBox):
                if child.title() == "Connection Settings - Ch1":
                    child.setTitle("Connection Settings")
                elif child.title() == "Slave Module Data - Ch1":
                    child.setTitle("Slave Module Data")
            # Control Commands 헤더 원복
            if hasattr(self, 'control_header_label'):
                self.control_header_label.setText("Control Commands")

    def on_channel_changed(self, channel_text):
        """채널 드롭다운 변경 시 호출"""
        if channel_text == "2CH" and self.channel_count == 1:
            self.toggle_channel_mode()
        elif channel_text == "1CH" and self.channel_count == 2:
            self.toggle_channel_mode()

    def on_operation_mode_changed(self, state):
        """운전 모드 체크박스 변경 시 호출"""
        if state == Qt.Checked and self.operation_mode == "Independent":
            self.toggle_operation_mode()
        elif state == Qt.Unchecked and self.operation_mode == "Parallel":
            self.toggle_operation_mode()

    def toggle_operation_mode(self):
        """원자적 운전 모드 전환 (Independent ↔ Parallel)"""
        # 상태 전환 시작 (이미 전환 중이면 무시)
        if not self.begin_state_transition():
            print("⚠️ Operation mode transition already in progress, ignoring...")
            return

        # 현재 상태 백업 (롤백용)
        previous_channel_count = self.channel_count
        previous_operation_mode = self.operation_mode

        try:
            if self.operation_mode == "Independent":
                # Independent → Parallel 전환
                self.operation_mode = "Parallel"
                # 체크박스 업데이트
                self.operation_checkbox.setChecked(True)
                # 병렬 모드: CH2 컨트롤을 비활성화
                if hasattr(self, 'ch2_control_widgets'):
                    for widget in self.ch2_control_widgets:
                        widget.setEnabled(False)
                    # CH2 컨트롤 시각적 스타일 적용 (회색 처리)
                    self.apply_disabled_style_to_ch2_controls(True)
                # CH2 헤더에 Parallel Mode 텍스트 추가 (같은 줄에 표시)
                if hasattr(self, 'ch2_control_header_widget'):
                    self.update_ch2_header_text("Control Commands - Ch2 (Parallel Mode - Controlled by CH1)")
                print("✅ 병렬 운전 모드로 전환 완료 - CH2는 CH1으로 제어")
            else:
                # Parallel → Independent 전환
                self.operation_mode = "Independent"
                # 체크박스 업데이트
                self.operation_checkbox.setChecked(False)
                # 독립 모드: CH2 컨트롤을 활성화 (2채널 모드인 경우만)
                if hasattr(self, 'ch2_control_widgets') and self.channel_count == 2:
                    for widget in self.ch2_control_widgets:
                        widget.setEnabled(True)
                    # CH2 컨트롤 원래 스타일 복원
                    self.apply_disabled_style_to_ch2_controls(False)
                # CH2 헤더 텍스트 원복
                if hasattr(self, 'ch2_control_header_widget'):
                    self.update_ch2_header_text("Control Commands - Ch2")
                print("✅ 독립 운전 모드로 전환 완료 - CH2 독립 제어")

            # 상태 전환 완료
            self.end_state_transition()

        except Exception as e:
            print(f"❌ Operation mode transition failed: {e}")
            # 롤백 수행
            self.rollback_state_transition(previous_channel_count, previous_operation_mode)

    def update_ch2_header_text(self, text):
        """CH2 헤더 텍스트 업데이트"""
        if hasattr(self, 'ch2_header_label'):
            self.ch2_header_label.setText(text)

    def apply_disabled_style_to_ch2_controls(self, apply_disabled_style):
        """CH2 컨트롤들에 비활성화 스타일 적용/제거"""
        if not hasattr(self, 'ch2_control_widgets'):
            return

        if apply_disabled_style:
            # 비활성화 스타일 적용 (회색 처리, 크기 유지)
            disabled_style = {
                'spinbox': "QDoubleSpinBox { background-color: #f0f0f0; color: #888888; padding-right: 50px; }",
                'button': "QPushButton { background-color: #e0e0e0; color: #888888; padding: 8px; font-weight: bold; }"
            }

            for widget in self.ch2_control_widgets:
                if isinstance(widget, QDoubleSpinBox):
                    widget.setStyleSheet(disabled_style['spinbox'])
                elif isinstance(widget, QPushButton):
                    widget.setStyleSheet(disabled_style['button'])
        else:
            # 원래 스타일 복원
            for widget in self.ch2_control_widgets:
                if isinstance(widget, QDoubleSpinBox):
                    widget.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
                elif isinstance(widget, QPushButton):
                    if "Command" in widget.text():
                        widget.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; }")
                    elif "Stop" in widget.text():
                        widget.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")

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
            
    def on_checksum_changed(self, value, channel):
        """체크섬 설정 변경 (채널별)"""
        self.checksum_enabled[channel] = (value == "ON")
        if self.checksum_enabled[channel]:
            print(f"CH{channel+1} 체크섬 검증 활성화")
        else:
            print(f"CH{channel+1} 체크섬 검증 비활성화")
        
    def send_start_command(self, channel=0):
        """시작 명령 전송 (SCADA → Master) - 프로토콜 2.0"""
        # 병렬 모드: CH1만 둘 채널로 전송, 독립 모드: 각 채널 독립 전송
        if self.operation_mode == "Parallel":
            # 병렬 모드: CH1에서 모든 채널로 전송
            channels_to_send = [0, 1] if self.channel_count == 2 and self.connected[1] else [0]
        else:
            # 독립 모드: 해당 채널만 전송
            channels_to_send = [channel]

        # 전송할 채널이 연결되어 있는지 확인
        valid_channels = [ch for ch in channels_to_send if self.connected[ch] and self.serial_workers[ch]]
        if not valid_channels:
            QMessageBox.warning(self, "Warning", "Please connect to serial port first")
            return

        try:
            # 각 채널로 모두 전송
            for target_channel in valid_channels:
                # SCADA → Master 프로토콜 2.0 (10바이트)
                frame = bytearray(10)
                frame[0] = 0x02  # STX

                # Command 바이트: bit[0]=Start, bit[2:1]=운전모드
                command_byte = 0x01  # Start
                if self.operation_mode == "Independent":
                    command_byte |= (0x01 << 1)  # 독립운전 모드 (bit[2:1] = 01)
                elif self.operation_mode == "Parallel":
                    command_byte |= (0x02 << 1)  # 병렬운전 모드 (bit[2:1] = 10)
                frame[1] = command_byte

                # 전압 및 전류 값 선택 (병렬 모드는 CH1 값 사용, 독립 모드는 각자)
                if self.operation_mode == "Parallel" or target_channel == 0:
                    # CH1 값 사용
                    max_voltage_val = self.max_voltage_spinbox.value()
                    min_voltage_val = self.min_voltage_spinbox.value()
                    current_val = self.current_spinbox.value()
                else:
                    # CH2 값 사용 (독립 모드에서만)
                    max_voltage_val = self.ch2_max_voltage_spinbox.value()
                    min_voltage_val = self.ch2_min_voltage_spinbox.value()
                    current_val = self.ch2_current_spinbox.value()

                # 전압 상한 지령 (2바이트, 스케일링 없음, 음수 허용)
                max_voltage_raw = int(max_voltage_val)
                max_voltage_raw = max(-32768, min(32767, max_voltage_raw))  # signed int16 범위 제한
                frame[2:4] = struct.pack('>h', max_voltage_raw)  # signed int16

                # 전압 하한 지령 (2바이트, 스케일링 없음, 음수 허용)
                min_voltage_raw = int(min_voltage_val)
                min_voltage_raw = max(-32768, min(32767, min_voltage_raw))  # signed int16 범위 제한
                frame[4:6] = struct.pack('>h', min_voltage_raw)  # signed int16

                # 전류 지령 (2바이트, Center=32768, ÷10 스케일링)
                current_raw = int(current_val * 10 + 32768)  # ÷10 스케일링의 역변환
                current_raw = max(0, min(65535, current_raw))  # uint16 범위 제한
                frame[6:8] = struct.pack('>H', current_raw)  # unsigned int16

                # 체크섬 (Byte1~7의 합)
                checksum = sum(frame[1:8]) & 0xFF
                frame[8] = checksum

                frame[9] = 0x03  # ETX

                # 시리얼로 전송
                self.serial_workers[target_channel].serial_port.write(frame)
                print(f"Start command sent to CH{target_channel+1}: Mode={self.operation_mode}, Max={max_voltage_val:.1f}V, Min={min_voltage_val:.1f}V, Current={current_val:.1f}A")

            # 상태 업데이트 (CH1만 또는 해당 채널만)
            if channel == 0:
                self.values_changed = False
                self.start_btn.setText("Command")
                self.restore_spinbox_colors()

                # 현재 값들을 새로운 원래 값으로 설정
                self.original_values[self.max_voltage_spinbox] = self.max_voltage_spinbox.value()
                self.original_values[self.min_voltage_spinbox] = self.min_voltage_spinbox.value()
                self.original_values[self.current_spinbox] = self.current_spinbox.value()

        except Exception as e:
            print(f"Failed to send start command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to send start command: {e}")
    
    def send_stop_command(self, channel=0):
        """정지 명령 전송 (SCADA → Master) - 프로토콜 2.0"""
        # 병렬 모드: CH1만 둘 채널로 전송, 독립 모드: 각 채널 독립 전송
        if self.operation_mode == "Parallel":
            # 병렬 모드: CH1에서 모든 채널로 전송
            channels_to_send = [0, 1] if self.channel_count == 2 and self.connected[1] else [0]
        else:
            # 독립 모드: 해당 채널만 전송
            channels_to_send = [channel]

        # 전송할 채널이 연결되어 있는지 확인
        valid_channels = [ch for ch in channels_to_send if self.connected[ch] and self.serial_workers[ch]]
        if not valid_channels:
            QMessageBox.warning(self, "Warning", "Please connect to serial port first")
            return

        try:
            # 각 채널로 모두 전송
            for target_channel in valid_channels:
                # SCADA → Master 프로토콜 2.0 (10바이트)
                frame = bytearray(10)
                frame[0] = 0x02  # STX

                # Command 바이트: bit[0]=Stop, bit[2:1]=정지모드 (0)
                command_byte = 0x00  # Stop
                # bit[2:1] = 00 (정지)
                frame[1] = command_byte

                # 전압, 전류 모두 0으로 설정
                frame[2:4] = struct.pack('>h', 0)  # Max Voltage = 0
                frame[4:6] = struct.pack('>h', 0)  # Min Voltage = 0
                frame[6:8] = struct.pack('>H', 32768)  # Current = 0 (Center=32768)

                # 체크섬 (Byte1~7의 합)
                checksum = sum(frame[1:8]) & 0xFF
                frame[8] = checksum

                frame[9] = 0x03  # ETX

                # 시리얼로 전송
                self.serial_workers[target_channel].serial_port.write(frame)
                print(f"Stop command sent to CH{target_channel+1}: All values set to 0")

            # 상태 업데이트 (CH1만 또는 해당 채널만)
            if channel == 0:
                self.values_changed = False
                self.start_btn.setText("Command")
                self.restore_spinbox_colors()

        except Exception as e:
            print(f"Failed to send stop command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to send stop command: {e}")

    def retry_connection(self, channel):
        """연결 재시도 (최대 횟수 제한)"""
        if not self.connected[channel] and self.reconnect_attempts[channel] <= self.max_reconnect_attempts:
            print(f"Retrying CH{channel+1} connection... (Attempt {self.reconnect_attempts[channel]}/{self.max_reconnect_attempts})")
            if channel == 0:
                port = self.port_combo.currentData()
                baud = int(self.baud_combo.currentText())
            else:
                port = self.ch2_port_combo.currentData()
                baud = int(self.ch2_baud_combo.currentText())

            if port:
                # 조용한 재연결 시도 (에러 메시지 없이)
                worker = SerialWorker(self, channel)
                if worker.connect_serial(port, baud):
                    # 성공하면 정상 연결 프로세스 진행하고 재시도 카운터 리셋
                    self.reconnect_attempts[channel] = 0
                    self.connect_serial(channel)
                    print(f"CH{channel+1} reconnection successful!")
                else:
                    # 실패하면 최대 횟수 체크 후 재시도
                    if self.reconnect_attempts[channel] < self.max_reconnect_attempts:
                        self.reconnect_attempts[channel] += 1
                        self.reconnect_timers[channel].start(5000)
                        print(f"CH{channel+1} reconnection failed, will retry again...")
                    else:
                        print(f"CH{channel+1} maximum reconnection attempts reached. Stopping retries.")
                worker.disconnect_serial()  # 임시 워커 정리

    def closeEvent(self, event):
        """프로그램 종료시 정리"""
        # 재연결 타이머 정리
        if hasattr(self, 'reconnect_timers'):
            for timer in self.reconnect_timers:
                if timer:
                    timer.stop()

        # 모든 채널 연결 해제
        for i in range(2):
            if self.connected[i]:
                self.disconnect_serial(i)

        # 타이머 정리
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()

        # UI 업데이트 타이머 정리
        if hasattr(self, 'ui_update_timer'):
            self.ui_update_timer.stop()

        event.accept()

class ChannelPanel(QWidget):
    """채널별 독립 패널 (Ch1/Ch2)"""

    modeChanged = pyqtSignal(str)

    def __init__(self, channel_index=1, parent=None):
        super().__init__(parent)
        self.channel_index = channel_index
        self.channel_name = f"Ch{self.channel_index}"

        # 상태 변수 (채널 독립)
        self.serial_worker = None
        self.serial_thread = None
        self.connected = False
        self.packet_count = 0
        self.system_voltage = 0.0
        self.system_current = 0.0
        self.values_changed = False
        self.original_spinbox_style = ""
        self.has_received_data = False
        self.checksum_enabled = True
        self.changed_spinboxes = set()
        self.original_values = {}
        self.operation_mode = "Single"  # Single / Dual / Parallel

        self._build_ui()
        self.refresh_ports()
        self.create_initial_modules()

        # 초기 표시
        self.system_current_label.setText("---          ")
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 채널 라벨 + 모드 라디오 버튼(우측) 헤더
        channel_label = QLabel(self.channel_name)
        bold_font = channel_label.font()
        bold_font.setPointSize(bold_font.pointSize() + 3)
        bold_font.setBold(True)
        channel_label.setFont(bold_font)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_layout.addWidget(channel_label)
        header_layout.addStretch()

        # 모드 라디오 버튼 (Single / Dual / Parallel)
        self.mode_container = QWidget()
        mode_layout = QHBoxLayout(self.mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(12)
        self.mode_group = QButtonGroup(self)
        self.radio_single = QRadioButton("Single")
        self.radio_dual = QRadioButton("Dual")
        self.radio_parallel = QRadioButton("Parallel")
        self.radio_single.setChecked(True)
        self.mode_group.addButton(self.radio_single)
        self.mode_group.addButton(self.radio_dual)
        self.mode_group.addButton(self.radio_parallel)
        mode_layout.addWidget(self.radio_single)
        mode_layout.addWidget(self.radio_dual)
        mode_layout.addWidget(self.radio_parallel)
        header_layout.addWidget(self.mode_container)
        if self.channel_index != 1:
            self.mode_container.hide()
        else:
            self.radio_single.toggled.connect(lambda checked: checked and self.modeChanged.emit('Single'))
            self.radio_dual.toggled.connect(lambda checked: checked and self.modeChanged.emit('Dual'))
            self.radio_parallel.toggled.connect(lambda checked: checked and self.modeChanged.emit('Parallel'))

        # 헤더 높이를 고정해서 Ch1/Ch2가 동일 높이를 갖도록 강제
        header_widget.setFixedHeight(40)
        layout.addWidget(header_widget)

        # 1. 연결 설정
        self.conn_group = QGroupBox("Connection Settings")
        conn_layout = QGridLayout(self.conn_group)

        port_label_layout = QHBoxLayout()
        port_label_layout.addWidget(QLabel("Port:"))
        refresh_btn = QPushButton("refresh")
        refresh_btn.setToolTip("Refresh port list")
        refresh_btn.setFixedSize(60, 24)
        refresh_btn.setStyleSheet(
            """
            QPushButton { border: 1px solid #ccc; border-radius: 3px; background-color: #f0f0f0; font-size: 12px; }
            QPushButton:hover { background-color: #e0e0e0; }
            QPushButton:pressed { background-color: #d0d0d0; }
            """
        )
        refresh_btn.clicked.connect(self.refresh_ports)
        port_label_layout.addWidget(refresh_btn)
        port_label_layout.addStretch()
        port_label_widget = QWidget()
        port_label_widget.setLayout(port_label_layout)
        conn_layout.addWidget(port_label_widget, 0, 0)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(200)
        self.port_combo.setStyleSheet("QComboBox { text-align: center; }")
        conn_layout.addWidget(self.port_combo, 0, 1)

        conn_layout.addWidget(QLabel("Baud:"), 0, 2)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.setStyleSheet("QComboBox { text-align: right; }")
        conn_layout.addWidget(self.baud_combo, 0, 3)

        conn_layout.addWidget(QLabel("Checksum:"), 0, 4)
        self.checksum_combo = QComboBox()
        self.checksum_combo.addItems(["ON", "OFF"])
        self.checksum_combo.setCurrentText("ON")
        self.checksum_combo.setMinimumWidth(80)
        self.checksum_combo.setStyleSheet("QComboBox { text-align: center; }")
        self.checksum_combo.currentTextChanged.connect(self.on_checksum_changed)
        conn_layout.addWidget(self.checksum_combo, 0, 5)

        self.connect_btn = QPushButton("Disconnected")
        connect_font = self.connect_btn.font()
        connect_font.setPointSize(connect_font.pointSize() + 2)
        self.connect_btn.setFont(connect_font)
        self.connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
        self.connect_btn.setFixedWidth(130)
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn, 0, 6)

        layout.addWidget(self.conn_group)
        # Ch1/Ch2 컨테이너들의 전체 높이를 맞추기 위해 최소 높이 힌트를 맞춤
        self.conn_group.setMinimumHeight(90)

        # 2. Control Commands
        self.control_group = QGroupBox("Control Commands (SCADA → Master)")
        control_layout = QGridLayout(self.control_group)

        max_voltage_label = QLabel("Max Voltage:")
        max_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(max_voltage_label, 0, 0)

        self.max_voltage_spinbox = QDoubleSpinBox()
        self.max_voltage_spinbox.setRange(0.0, 1000.0)
        self.max_voltage_spinbox.setDecimals(1)
        self.max_voltage_spinbox.setSuffix(" V")
        self.max_voltage_spinbox.setValue(500.0)
        self.max_voltage_spinbox.setAlignment(Qt.AlignRight)
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
        self.current_spinbox.setAlignment(Qt.AlignRight)
        current_font = self.current_spinbox.font()
        current_font.setPointSize(current_font.pointSize() + 2)
        self.current_spinbox.setFont(current_font)
        self.current_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        control_layout.addWidget(self.current_spinbox, 0, 3)

        min_voltage_label = QLabel("Min Voltage:")
        min_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(min_voltage_label, 1, 0)

        self.min_voltage_spinbox = QDoubleSpinBox()
        self.min_voltage_spinbox.setRange(0.0, 1000.0)
        self.min_voltage_spinbox.setDecimals(1)
        self.min_voltage_spinbox.setSuffix(" V")
        self.min_voltage_spinbox.setValue(0.0)
        self.min_voltage_spinbox.setAlignment(Qt.AlignRight)
        min_font = self.min_voltage_spinbox.font()
        min_font.setPointSize(min_font.pointSize() + 2)
        self.min_voltage_spinbox.setFont(min_font)
        self.min_voltage_spinbox.setStyleSheet("QDoubleSpinBox { padding-right: 50px; }")
        control_layout.addWidget(self.min_voltage_spinbox, 1, 1)

        # 변경 추적 원래 값
        self.original_spinbox_style = self.max_voltage_spinbox.styleSheet()
        self.original_values[self.max_voltage_spinbox] = 500.0
        self.original_values[self.min_voltage_spinbox] = 0.0
        self.original_values[self.current_spinbox] = 0.0

        self.max_voltage_spinbox.valueChanged.connect(lambda v: self.on_value_changed(self.max_voltage_spinbox, v))
        self.min_voltage_spinbox.valueChanged.connect(lambda v: self.on_value_changed(self.min_voltage_spinbox, v))
        self.current_spinbox.valueChanged.connect(lambda v: self.on_value_changed(self.current_spinbox, v))

        self.start_btn = QPushButton("Command")
        start_font = self.start_btn.font()
        start_font.setPointSize(start_font.pointSize() + 2)
        self.start_btn.setFont(start_font)
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #BDBDBD; color: #EEEEEE; }"
        )
        self.start_btn.clicked.connect(self.send_start_command)
        control_layout.addWidget(self.start_btn, 1, 2)

        self.stop_btn = QPushButton("Stop")
        stop_font = self.stop_btn.font()
        stop_font.setPointSize(stop_font.pointSize() + 2)
        self.stop_btn.setFont(stop_font)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #BDBDBD; color: #EEEEEE; }"
        )
        self.stop_btn.clicked.connect(self.send_stop_command)
        control_layout.addWidget(self.stop_btn, 1, 3)

        # (모드 라디오 버튼은 헤더로 이동함)

        # 3. 시스템 표시
        sys_voltage_label = QLabel("System Voltage:")
        sys_voltage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        control_layout.addWidget(sys_voltage_label, 2, 0)
        self.system_voltage_label = QLabel("---          ")
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
        current_font2 = self.font()
        current_font2.setPointSize(int(current_font2.pointSize() * 1.5))
        self.system_current_label.setFont(current_font2)
        self.system_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        control_layout.addWidget(self.system_current_label, 2, 3)

        layout.addWidget(self.control_group)
        self.control_group.setMinimumHeight(150)

        # 4. 통계
        self.stats_label = QLabel("Connected: No | Modules: 0 | Packets: 0")
        self.stats_label.setStyleSheet("QLabel { background-color: #E3F2FD; padding: 8px; border: 1px solid #BBDEFB; }")
        layout.addWidget(self.stats_label)

        # 5. 데이터 테이블
        table_group = QGroupBox("Slave Module Data")
        table_layout = QVBoxLayout(table_group)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['ID', 'DAB_OK', 'Current (A)', 'Temp (°C)', 'Update'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 240)
        self.table.setColumnWidth(3, 240)
        self.table.setColumnWidth(4, 120)
        header.setDefaultAlignment(Qt.AlignCenter)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(35)
        header.setFixedHeight(40)
        table_layout.addWidget(self.table)
        layout.addWidget(table_group)
        table_group.setMinimumHeight(420)

        # 6. 하단 버튼
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("+")
        add_btn.setFixedSize(60, 30)
        add_btn.setToolTip("Add Test Module")
        add_btn.clicked.connect(self.add_test_module)
        btn_layout.addWidget(add_btn)
        remove_btn = QPushButton("-")
        remove_btn.setFixedSize(60, 30)
        remove_btn.setToolTip("Remove Last Module")
        remove_btn.clicked.connect(self.remove_last_module)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_to_initial)
        btn_layout.addWidget(reset_btn)
        layout.addLayout(btn_layout)

        # 데이터 저장용
        self.module_rows = {}
        self.module_currents = {}
        self.module_last_update = {}

        # 상태 체크 타이머
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.check_module_status)
        self.status_timer.start(1000)

    def set_controls_enabled(self, enabled: bool):
        """Control Commands 영역 활성/비활성 (병렬 모드: False)"""
        self.control_group.setEnabled(enabled)
        # 버튼 시각적 비활성화 스타일이 확실히 적용되도록 개별 처리
        self.start_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)

    def get_clean_port_name(self, device_path, description):
        clean_name = device_path.replace('/dev/cu.', '').replace('/dev/tty.', '')
        if clean_name.startswith('COM'):
            return clean_name
        clean_name = clean_name.replace('usbserial-', '')
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
            if clean_name and clean_name != device_path:
                return f"{chip_type} {clean_name}"
            else:
                return f"{chip_type} Serial"
        return clean_name if clean_name else device_path

    def refresh_ports(self):
        self.port_combo.clear()
        all_ports = serial.tools.list_ports.comports()
        serial_keywords = ['usbserial', 'tty.usb', 'COM', 'FTDI', 'CP210', 'CH340', 'PL2303', 'Serial', 'UART']
        exclude_keywords = ['bluetooth', 'debug-console', 'focal', 'airpods']
        filtered_ports = []
        for port in all_ports:
            port_info = f"{port.device} {port.description} {port.manufacturer or ''}".lower()
            if any(ex.lower() in port_info for ex in exclude_keywords):
                print(f"✗ Excluded: {port.device} - {port.description}")
                continue
            if any(k.lower() in port_info for k in serial_keywords):
                display_name = self.get_clean_port_name(port.device, port.description)
                filtered_ports.append((port.device, display_name))
                print(f"✓ Serial port: {port.device} -> {display_name}")
            else:
                print(f"✗ Filtered out: {port.device} - {port.description}")
        if not filtered_ports:
            filtered_ports = [(port.device, port.device) for port in all_ports]
            print("⚠️  No serial ports found, showing all ports")
        for device_path, display_name in filtered_ports:
            self.port_combo.addItem(display_name, device_path)
        print(f"[{self.channel_name}] Available serial ports: {[name for _, name in filtered_ports]}")

    def toggle_connection(self):
        if not self.connected:
            self.connect_serial()
        else:
            self.disconnect_serial()

    def connect_serial(self):
        port = self.port_combo.currentData()
        if not port:
            port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())
        if not port:
            QMessageBox.warning(self, "Warning", f"[{self.channel_name}] Please select a port")
            return
        self.serial_worker = SerialWorker(self)
        self.serial_thread = QThread()
        self.serial_worker.moveToThread(self.serial_thread)
        self.serial_worker.slave_data_received.connect(self.update_slave_data)
        self.serial_worker.system_voltage_received.connect(self.update_system_voltage)
        self.serial_thread.started.connect(self.serial_worker.read_serial)
        if self.serial_worker.connect_serial(port, baud):
            self.connected = True
            self.serial_thread.start()
            self.connect_btn.setText("Connected")
            self.connect_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 8px; }")
            self.system_voltage_label.setText("0.0 V          ")
            self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
            self.system_current_label.setText("0.0 A          ")
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
            print(f"[{self.channel_name}] Connected to {port} at {baud} baud")
        else:
            QMessageBox.critical(self, "Error", f"[{self.channel_name}] Failed to connect to {port}")

    def disconnect_serial(self):
        self.connected = False
        if self.serial_worker:
            self.serial_worker.disconnect_serial()
        if self.serial_thread:
            self.serial_thread.quit()
            self.serial_thread.wait()
        self.serial_worker = None
        self.serial_thread = None
        self.connect_btn.setText("Disconnected")
        self.connect_btn.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 8px; }")
        self.system_voltage_label.setText("---          ")
        self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        self.system_current_label.setText("---          ")
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        self.has_received_data = False
        print(f"[{self.channel_name}] Disconnected")

    @pyqtSlot(int, float, float, bool, str)
    def update_slave_data(self, slave_id, current, temp, dab_ok, timestamp):
        if not self.connected:
            return
        self.packet_count += 1
        self.add_slave_module(slave_id, current, temp, dab_ok, timestamp)
        self.update_stats()

    @pyqtSlot(float, str)
    def update_system_voltage(self, voltage, timestamp):
        if not self.connected:
            return
        self.system_voltage = voltage
        self.system_voltage_label.setText(f"{voltage:.1f} V          ")
        self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #2E7D32; }")
        self.has_received_data = True
        self.packet_count += 1
        self.update_stats()

    def update_system_current(self):
        self.system_current = sum(self.module_currents.values())
        self.system_current_label.setText(f"{self.system_current:.2f} A          ")
        if self.has_received_data:
            self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #1976D2; }")

    def update_stats(self):
        self.stats_label.setText(
            f"Connected: {'Yes' if self.connected else 'No'} | Modules: {len(self.module_rows)} | Packets: {self.packet_count}"
        )

    def add_slave_module(self, slave_id, current, temp, dab_ok, timestamp):
        if slave_id not in self.module_rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.module_rows[slave_id] = row
        row = self.module_rows[slave_id]
        self.module_last_update[slave_id] = time.time()
        id_item = QTableWidgetItem(str(slave_id))
        id_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, id_item)
        dab_item = QTableWidgetItem("✓" if dab_ok else "✗")
        dab_item.setTextAlignment(Qt.AlignCenter)
        if dab_ok:
            dab_item.setBackground(QColor(200, 255, 200))
        else:
            dab_item.setBackground(QColor(255, 200, 200))
        self.table.setItem(row, 1, dab_item)
        current_item = QTableWidgetItem(f"{current:.2f} A                 ")
        current_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 2, current_item)
        temp_item = QTableWidgetItem(f"{temp:.1f} °C                 ")
        temp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(row, 3, temp_item)
        update_item = QTableWidgetItem(timestamp)
        update_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 4, update_item)
        self.module_currents[slave_id] = current
        self.update_system_current()

    def check_module_status(self):
        if not self.connected:
            return
        current_time = time.time()
        for slave_id, row in self.module_rows.items():
            if slave_id in self.module_last_update:
                time_since = current_time - self.module_last_update[slave_id]
                if time_since >= 1.0:
                    dab_item = self.table.item(row, 1)
                    if dab_item:
                        dab_item.setBackground(QColor(200, 200, 200))
                if time_since >= 5.0:
                    current_item = self.table.item(row, 2)
                    if current_item:
                        current_item.setText("0.00 A                 ")
                    temp_item = self.table.item(row, 3)
                    if temp_item:
                        temp_item.setText("0.0 °C                 ")
                    dab_item = self.table.item(row, 1)
                    if dab_item:
                        dab_item.setText("✗")
                        dab_item.setBackground(QColor(200, 200, 200))
                    update_item = self.table.item(row, 4)
                    if update_item:
                        update_item.setText("--:--:--")
                    if slave_id in self.module_currents:
                        self.module_currents[slave_id] = 0.0
                        self.update_system_current()

    def add_test_module(self):
        next_id = len(self.module_rows) + 1
        if next_id > 31:
            QMessageBox.warning(self, "Warning", "Maximum 31 modules reached")
            return
        self.add_slave_module(next_id, 0.0, 0.0, False, "--:--:--")
        self.update_stats()
        print(f"[{self.channel_name}] 테스트 모듈 ID {next_id} 추가됨")

    def remove_last_module(self):
        if not self.module_rows:
            return
        max_id = max(self.module_rows.keys())
        row = self.module_rows[max_id]
        self.table.removeRow(row)
        del self.module_rows[max_id]
        if max_id in self.module_currents:
            del self.module_currents[max_id]
        if max_id in self.module_last_update:
            del self.module_last_update[max_id]
        for module_id, module_row in list(self.module_rows.items()):
            if module_row > row:
                self.module_rows[module_id] = module_row - 1
        self.update_system_current()
        self.update_stats()
        print(f"[{self.channel_name}] 모듈 ID {max_id} 제거됨")

    def reset_to_initial(self):
        self.table.setRowCount(0)
        self.module_rows.clear()
        self.module_currents.clear()
        self.module_last_update.clear()
        self.packet_count = 0
        self.create_initial_modules()
        self.system_voltage = 0.0
        self.system_current = 0.0
        self.has_received_data = False
        self.system_voltage_label.setText("---          ")
        self.system_voltage_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        self.system_current_label.setText("---          ")
        self.system_current_label.setStyleSheet("QLabel { font-weight: bold; color: #9E9E9E; }")
        self.stats_label.setText("Connected: No | Modules: 10 | Packets: 0")
        self.values_changed = False
        self.changed_spinboxes.clear()
        self.start_btn.setText("Command")
        self.restore_spinbox_colors()
        self.original_values[self.max_voltage_spinbox] = 500.0
        self.original_values[self.min_voltage_spinbox] = 0.0
        self.original_values[self.current_spinbox] = 0.0
        print(f"[{self.channel_name}] 초기 상태로 리셋됨 (10개 모듈)")

    def create_initial_modules(self):
        for i in range(1, 11):
            self.add_slave_module(i, 0.0, 0.0, False, "--:--:--")

    def on_value_changed(self, spinbox, value):
        original_value = self.original_values.get(spinbox, 0.0)
        if abs(value - original_value) < 0.01:
            self.restore_specific_spinbox_color(spinbox)
        else:
            self.values_changed = True
            self.changed_spinboxes.add(spinbox)
            changed_style = "QDoubleSpinBox { background-color: #FFF9C4; padding-right: 50px; }"
            spinbox.setStyleSheet(changed_style)
            self.start_btn.setText("Update")

    def restore_spinbox_colors(self):
        normal_style = "QDoubleSpinBox { padding-right: 50px; }"
        self.max_voltage_spinbox.setStyleSheet(normal_style)
        self.min_voltage_spinbox.setStyleSheet(normal_style)
        self.current_spinbox.setStyleSheet(normal_style)
        self.changed_spinboxes.clear()

    def restore_specific_spinbox_color(self, spinbox):
        normal_style = "QDoubleSpinBox { padding-right: 50px; }"
        spinbox.setStyleSheet(normal_style)
        self.changed_spinboxes.discard(spinbox)
        if not self.changed_spinboxes:
            self.values_changed = False
            self.start_btn.setText("Command")

    def on_checksum_changed(self, value):
        self.checksum_enabled = (value == "ON")
        print(f"[{self.channel_name}] 체크섬 검증 {'활성화' if self.checksum_enabled else '비활성화'}")

    def send_start_command(self):
        if not self.connected or not self.serial_worker:
            QMessageBox.warning(self, "Warning", f"[{self.channel_name}] Please connect to serial port first")
            return
        try:
            frame = bytearray(9)
            frame[0] = 0x02
            frame[1] = 0x01  # Start
            max_voltage_raw = int(abs(self.max_voltage_spinbox.value()))
            frame[2:4] = struct.pack('>h', max_voltage_raw)
            min_voltage_raw = int(abs(self.min_voltage_spinbox.value()))
            frame[4:6] = struct.pack('>h', min_voltage_raw)
            current_raw = int(self.current_spinbox.value())
            current_raw = max(-128, min(127, current_raw))
            frame[6] = struct.pack('>b', current_raw)[0]
            checksum = sum(frame[1:7]) & 0xFF
            frame[7] = checksum
            frame[8] = 0x03
            # 병렬 운전 모드 로그 표시
            mode_note = " (Parallel)" if self.operation_mode == 'Parallel' else ""
            self.serial_worker.serial_port.write(frame)
            self.values_changed = False
            self.start_btn.setText("Command")
            self.restore_spinbox_colors()
            self.original_values[self.max_voltage_spinbox] = self.max_voltage_spinbox.value()
            self.original_values[self.min_voltage_spinbox] = self.min_voltage_spinbox.value()
            self.original_values[self.current_spinbox] = self.current_spinbox.value()
            print(
                f"[{self.channel_name}] Start command sent{mode_note}: Max={self.max_voltage_spinbox.value():.1f}V, Min={self.min_voltage_spinbox.value():.1f}V, Current={self.current_spinbox.value():.0f}A, Checksum=0x{checksum:02X}"
            )
        except Exception as e:
            print(f"[{self.channel_name}] Failed to send start command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to send start command: {e}")

    def send_stop_command(self):
        if not self.connected or not self.serial_worker:
            QMessageBox.warning(self, "Warning", f"[{self.channel_name}] Please connect to serial port first")
            return
        try:
            frame = bytearray(9)
            frame[0] = 0x02
            frame[1] = 0x00  # Stop
            frame[2:4] = struct.pack('>h', 0)
            frame[4:6] = struct.pack('>h', 0)
            frame[6] = 0x00
            checksum = sum(frame[1:7]) & 0xFF
            frame[7] = checksum
            frame[8] = 0x03
            self.serial_worker.serial_port.write(frame)
            self.values_changed = False
            self.start_btn.setText("Command")
            self.restore_spinbox_colors()
            print(f"[{self.channel_name}] Stop command sent: Checksum=0x{checksum:02X}")
        except Exception as e:
            print(f"[{self.channel_name}] Failed to send stop command: {e}")
            QMessageBox.critical(self, "Error", f"Failed to send stop command: {e}")

class MainWindow(QMainWindow):
    """싱글/듀얼/병렬 모드 전환 및 레이아웃 관리"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'SM1 - Serial Monitor v{__version__} - Power Control Module')
        # 초기 창 크기: 가로 +10px, 세로 +20px (스크롤바 방지용)
        self.setGeometry(100, 100, 810, 850)
        font = self.font()
        font.setPointSize(font.pointSize() + 3)
        self.setFont(font)

        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.channels_layout = QHBoxLayout()
        self.main_layout.addLayout(self.channels_layout)

        # Ch1 생성
        self.ch1 = ChannelPanel(channel_index=1, parent=self)
        self.channels_layout.addWidget(self.ch1)
        self.ch2 = None

        # 모드 변경 핸들링 (Ch1만 보유)
        self.ch1.modeChanged.connect(self.on_mode_changed)

        # 원래 창 크기 저장 (스크롤바 방지 사이즈)
        self.single_size = QSize(810, 850)

    def on_mode_changed(self, mode: str):
        mode = mode.strip()
        if mode == 'Single':
            self._ensure_single()
        elif mode == 'Dual':
            self._ensure_dual(parallel=False)
        elif mode == 'Parallel':
            self._ensure_dual(parallel=True)
        else:
            print(f"Unknown mode: {mode}")

    def _ensure_single(self):
        if self.ch2 is not None:
            try:
                if self.ch2.connected:
                    self.ch2.disconnect_serial()
            except Exception:
                pass
            self.ch2.setParent(None)
            self.ch2.deleteLater()
            self.ch2 = None
        self.ch1.operation_mode = 'Single'
        # 창 크기 원복: 제약 해제 후 강제 축소, 이후 제약 복원
        try:
            if self.centralWidget():
                self.centralWidget().setMinimumSize(0, 0)
        except Exception:
            pass
        self.setMinimumSize(0, 0)
        # 일시적으로 최대 크기를 줄여 강제 축소
        self.setMaximumSize(self.single_size)
        self.resize(self.single_size)
        # 이벤트 루프 다음 틱에 최대 크기 제약 해제
        QTimer.singleShot(0, lambda: self.setMaximumSize(QSize(16777215, 16777215)))

    def _ensure_dual(self, parallel: bool):
        if self.ch2 is None:
            self.ch2 = ChannelPanel(channel_index=2, parent=self)
            self.channels_layout.addWidget(self.ch2)
        # 모드 반영
        self.ch1.operation_mode = 'Parallel' if parallel else 'Dual'
        # 병렬 모드면 Ch2 컨트롤 비활성화
        self.ch2.set_controls_enabled(not parallel)
        # 창 크기 확장 (대략 2배)
        current_size = self.size()
        self.resize(
            max(self.single_size.width() * 2, current_size.width()),
            max(self.single_size.height(), current_size.height())
        )

    def closeEvent(self, event):
        try:
            if self.ch1 and self.ch1.connected:
                self.ch1.disconnect_serial()
        except Exception:
            pass
        try:
            if self.ch2 and self.ch2.connected:
                self.ch2.disconnect_serial()
        except Exception:
            pass
        return super().closeEvent(event)

def main():
    app = QApplication(sys.argv)
    
    # 애플리케이션 스타일 설정
    app.setStyle('Fusion')
    
    # 다크 테마 (선택사항)
    # palette = QPalette()
    # palette.setColor(QPalette.Window, QColor(53, 53, 53))
    # app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    
    print(f"SM1 - Serial Monitor v{__version__} 시작")
    print("Add Test Module 버튼으로 테스트 데이터 추가 가능")
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
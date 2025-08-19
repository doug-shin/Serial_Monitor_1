# Serial Monitor

F28377D 모듈 컨트롤러용 시리얼 모니터 애플리케이션입니다.

## 🎯 주요 기능

- **실시간 시리얼 통신 모니터링**
- **SCADA → Master 제어 명령 전송**
- **Master → SCADA 데이터 수신 및 표시**
- **체크섬 검증 옵션**
- **독립적인 입력값 변경 추적**
- **다중 슬레이브 모듈 데이터 관리**
- **커스텀 아이콘 및 크로스 플랫폼 지원**

## 설치

### 필수 요구사항
- Python 3.6 이상
- pip

### 의존성 설치
```bash
pip install -r requirements.txt
```

또는 직접 설치:
```bash
pip install PyQt5 pyserial
```

## 사용법

### 1. PyQt5 시리얼 모니터 실행
```bash
python pyqt_monitor.py
```

### 2. 연결 설정
1. **Port**: USB-to-Serial 어댑터 포트 선택 (예: COM3, /dev/tty.usbserial)
2. **Baud**: 통신 속도 설정 (9600 ~ 921600)
3. **Connect** 버튼 클릭

### 3. 데이터 타입 설정
- **Data 1**: 첫 번째 32비트 데이터의 해석 방식
- **Data 2**: 두 번째 32비트 데이터의 해석 방식
- 지원 타입: float32, int32, uint32, int16, uint16

### 4. 모듈 관리
- **Add 버튼**: 새 모듈 추가
- **더블클릭**: 모듈 이름 편집
- **우클릭**: 모듈 삭제 또는 Raw 데이터 보기

## 통신 프로토콜

### 데이터 형식
```
MXX,0xHHHHHHHH,0xHHHHHHHH\n
```

- `MXX`: 모듈 ID (M01 ~ M99)
- `0xHHHHHHHH`: 32비트 데이터 1 (16진수)
- `0xHHHHHHHH`: 32비트 데이터 2 (16진수)
- `\n`: 줄바꿈 문자

### 예시
```
M01,0x44FA0000,0xFFFFFE0C
M02,0x447A0000,0x000001F4
M03,0x42C80000,0xFFFFFF9C
```

## 테스트

### 테스트 데이터 송신기 실행
```bash
python test_sender.py
```

1. 시리얼 포트 선택
2. Baud rate 선택
3. 모듈 구성 선택
4. 업데이트 속도 설정

### 가상 시리얼 포트 (개발용)
macOS에서 가상 시리얼 포트 생성:
```bash
# Terminal 1
socat -d -d pty,raw,echo=0 pty,raw,echo=0

# Terminal 2에서 송신기 실행
python test_sender.py

# Terminal 3에서 모니터 실행
python serial_monitor.py
```

Windows에서는 com0com 또는 Virtual Serial Port Driver 사용

## F28377D 구현 예시

F28377D에서 시리얼 데이터 송신 예시:

```c
// SCI 초기화 후
void send_module_data(uint16_t module_id, float voltage, int32_t current) {
    char buffer[64];
    uint32_t voltage_hex = *(uint32_t*)&voltage;  // float를 uint32로
    uint32_t current_hex = (uint32_t)current;
    
    sprintf(buffer, "M%02d,0x%08X,0x%08X\n", 
            module_id, voltage_hex, current_hex);
    
    // SCI 송신
    SCI_writeCharArray(SCIA_BASE, (uint16_t*)buffer, strlen(buffer));
}
```

## 파일 구조

```
serial_monitor/
├── serial_monitor.py    # 메인 GUI 애플리케이션
├── test_sender.py       # 테스트 데이터 송신기
├── requirements.txt     # Python 의존성
└── README.md           # 이 문서
```

## 설정 저장/불러오기

**Save** 버튼으로 현재 구성을 JSON 파일로 저장:
```json
{
  "data1_type": "float32",
  "data2_type": "int32",
  "modules": {
    "M01": {"name": "HV Power Supply"},
    "M02": {"name": "Battery Monitor"}
  }
}
```

## 문제 해결

### 일반적인 문제

1. **포트 연결 오류**
   - USB-to-Serial 드라이버 확인
   - 포트가 다른 프로그램에서 사용 중인지 확인
   - 권한 문제 (Linux/macOS에서 dialout 그룹 확인)

2. **데이터 수신 안됨**
   - Baud rate 확인
   - 케이블 연결 확인
   - 송신 측 프로토콜 형식 확인

3. **데이터 파싱 오류**
   - 프로토콜 형식 정확한지 확인
   - 줄바꿈 문자(\n) 포함 여부 확인

### Linux/macOS 포트 권한
```bash
# 현재 사용자를 dialout 그룹에 추가
sudo usermod -a -G dialout $USER
# 로그아웃 후 다시 로그인
```

## 라이선스

이 프로젝트는 F28377D 모듈 컨트롤러 프로젝트의 일부입니다.
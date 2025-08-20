# SM1 - Serial Monitor v0.6

PyQt5 기반의 시리얼 모니터 애플리케이션입니다.

## 🚀 빠른 실행

### 방법 1: 실행 스크립트 사용 (추천)
```bash
./run.sh        # macOS/Linux
python3 run.py  # 모든 플랫폼
```

### 방법 2: 직접 실행
```bash
python3 sm1.py
```

## 📦 설치

### 의존성 설치
```bash
pip3 install -r requirements.txt
```

또는 직접 설치:
```bash
pip3 install PyQt5 pyserial
```

## 🎯 주요 기능

- **실시간 시리얼 통신 모니터링**
- **SCADA → Master 제어 명령 전송**
- **Master → SCADA 데이터 수신 및 표시**
- **체크섬 검증 옵션**
- **독립적인 입력값 변경 추적**
- **다중 슬레이브 모듈 데이터 관리**
- **커스텀 아이콘 및 크로스 플랫폼 지원**

## 🔧 사용법

### 1. 연결 설정
1. **Port**: USB-to-Serial 어댑터 포트 선택
2. **Baud**: 통신 속도 설정 (기본값: 38400)
3. **Checksum**: 체크섬 검증 ON/OFF
4. **Connect** 버튼 클릭

### 2. 제어 명령
- **Max/Min Voltage**: 전압 상한/하한 설정
- **Current Command**: 전류 지령 설정
- **Run/Stop**: 시작/정지 명령

### 3. 모듈 관리
- 초기 10개 모듈 자동 생성
- **+/-** 버튼으로 모듈 추가/제거
- **Reset** 버튼으로 초기 상태 복원

## 📡 통신 프로토콜

### Master → SCADA (7 bytes)
- **시스템 전압**: ID=0, 전압 데이터
- **슬레이브 데이터**: ID≠0, 전류/온도 데이터

### SCADA → Master (9 bytes)
- **제어 명령**: Start/Stop
- **전압 지령**: Max/Min 전압
- **전류 지령**: 모듈별 전류

자세한 프로토콜은 [docs/RS232_interface_protocol.md](docs/RS232_interface_protocol.md) 참조

## 🔨 빌드

### 실행 파일 생성
```bash
./build.sh
```

빌드 결과:
- **macOS**: `dist/SM1_v0.6`
- **Windows**: `dist/SM1_v0.6.exe`

## 📁 파일 구조

```
SM1/
├── sm1.py              # 메인 애플리케이션
├── run.py              # 실행 래퍼 (Python)
├── run.sh              # 실행 스크립트 (Shell)
├── setup.py            # 빌드 스크립트
├── build.sh            # 빌드 명령어
├── requirements.txt    # 의존성
├── docs/              # 문서
│   └── RS232_interface_protocol.md
└── serial_monitor_icon.*  # 아이콘 파일들
```

## 🐛 문제 해결

### 일반적인 문제

1. **포트 연결 오류**
   - USB-to-Serial 드라이버 확인
   - 포트가 다른 프로그램에서 사용 중인지 확인

2. **패키지 누락**
   ```bash
   pip3 install -r requirements.txt
   ```

3. **권한 문제 (Linux/macOS)**
   ```bash
   sudo usermod -a -G dialout $USER
   # 로그아웃 후 다시 로그인
   ```

## 📝 라이선스

F28377D 모듈 컨트롤러 프로젝트의 일부입니다.
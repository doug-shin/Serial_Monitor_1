# 통신 프로토콜 정의 2.0

## 1. Master → SCADA (7 bytes)

### 1.1 시스템 전압 (ID = 0)
| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 |  ID<br>채널| bit[7:3]: ID<br>bit[2:0]: 채널| uint8 |  ID: 0~31 (0=Master)<br>채널: 0~3 |
| 2-3 | System Voltage | Big-endian<br>Scale: ÷10 | uint16 | 6553.5 V | 
| 4 | Reserved | Future use | 0x00 | - |
| 5 | Checksum | Sum(Byte1~4) & 0xFF | uint8 | 0~255 |
| 6 | ETX | End of Text | 0x03 | - |

---

### 1.2 슬레이브 데이터 (ID ≠ 0)
| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 | Slave ID<br>Status | bit[7:3]: Slave ID<br>bit[2:1]: Reserved<br>bit[0]: DAB_OK | uint8 | Slave ID: 1~31<br>DAB_OK: 0=Fail, 1=OK |
| 2-3 | Slave Current | Big-endian, Center=32768<br>계산식: (Value - 32768) ÷100 | uint16 | 65535 → +327.67 A<br>32768 → &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;0 A<br>0&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ -327.68 A |
| 4 | Slave Temperature | Scale: ×0.5 | uint8 | 0 ~ 127.5 °C |
| 5 | Checksum | Sum(Byte1~4) & 0xFF | uint8 | 0~255 |
| 6 | ETX | End of Text | 0x03 | - |

---

## 2. SCADA → Master (10 bytes)

| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 | Command | bit[0]: 동작 제어<br>bit[2:1]: 운전 모드 | uint8 | bit[0]: 0=Stop, 1=Start<br>bit[2:1]: 0=정지, 1=독립운전, 2=병렬운전 |
| 2-3 | Max Voltage | Big-endian | int16 | 0 ~ +1000 V |
| 4-5 | Min Voltage | Big-endian | int16 | 0 ~ +1000 V |
| 6-7 | Current Command | Per module<br>Center = 32768 → 0 A<br>계산식: (Value - 32768) ÷ 10 | uint16 | 65535 → +3276.7 A<br>32768 → 0 A<br>0 → -3276.8 A |
| 8 | Checksum | **Sum(Byte1~7) & 0xFF** | uint8 | 0~255 |
| 9 | ETX | End of Text | 0x03 | - |

---
## 3. 데이터 타입 및 스케일링

### Master → SCADA
- **시스템 전압**: int16, ÷10 (예: 3000 = 300.0 V)  
- **슬레이브 전류**: uint16, Center=32768 → 0 A (예: 32768=0.00 A, 65535=+327.67 A, 0=-327.68 A)  
- **슬레이브 온도**: uint8, ×0.5 (예: 50 = 25.0 °C)

### SCADA → Master
- **전압 상한/하한**: int16, 스케일링 없음
- **전류 지령**: uint16, Center=32768 → 0 A, ÷10 스케일링 (예: 32768=0 A, 65535=+3276.7 A, 0=-3276.8 A)

---

## 4. 체크섬 계산

- 방식: 단순 합 체크섬 (Sum Checksum)  
- 계산: 데이터 바이트 합의 하위 8비트 사용  

- Master → SCADA: `Sum(Byte1~4) & 0xFF`  
- SCADA → Master: `Sum(Byte1~7) & 0xFF`  

---

## 5. 통신 파라미터

- Baud Rate: **115200 bps**  
- Data Bits: **8**  
- Stop Bits: **1**  
- Parity: **None**  
- Flow Control: **None**  

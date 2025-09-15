# RS232 Interface 프로토콜 명세서 1.0

## 1. Master → SCADA (7 bytes)

### 1.1 시스템 전압 (ID = 0)
| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 | ID + Reserved | bit[7:3]: ID=0<br>bit[2:0]: Reserved | uint8 | ID: 0~31 |
| 2-3 | System Voltage | Big-endian<br>Scale: ÷10 | int16 | -3276.8 ~ +3276.7 V |
| 4 | Reserved | Future use | 0x00 | - |
| 5 | Checksum | Sum(Byte1~4) & 0xFF | uint8 | 0~255 |
| 6 | ETX | End of Text | 0x03 | - |

### 1.2 슬레이브 데이터 (ID ≠ 0)
| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 | ID + Status | bit[7:3]: Slave ID<br>bit[2:1]: Reserved<br>bit[0]: DAB_OK | uint8 | ID: 1~31 |
| 2-3 | Slave Current | Big-endian<br>Scale: ÷100 | int16 | -327.68 ~ +327.67 A |
| 4 | Slave Temperature | Scale: ×0.5 | uint8 | 0 ~ 127.5 °C |
| 5 | Checksum | Sum(Byte1~4) & 0xFF | uint8 | 0~255 |
| 6 | ETX | End of Text | 0x03 | - |

## 2. SCADA → Master (9 bytes)

| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 | Command | 0x00: Stop<br>0x01: Start | uint8 | 0~1 |
| 2-3 | Max Voltage | Big-endian<br>No scaling | int16 | 0 ~ +1000 V |
| 4-5 | Min Voltage | Big-endian<br>No scaling | int16 | 0 ~ +1000 V |
| 6 | Current Command | Per module<br>No scaling | int8 | -128 ~ +127 A |
| 7 | Checksum | Sum(Byte1~6) & 0xFF | uint8 | 0~255 |
| 8 | ETX | End of Text | 0x03 | - |

## 3. 데이터 타입 및 스케일링 정리

### Master → SCADA
- **시스템 전압**: int16, ÷10 스케일링 (예: 3000 = 300.0V)
- **슬레이브 전류**: int16, ÷100 스케일링 (예: -8000 = -80.00A)
- **슬레이브 온도**: uint8, ×0.5 스케일링 (예: 50 = 25.0°C)

### SCADA → Master
- **전압 상한/하한**: int16, 스케일링 없음 (직접 전압값)
- **전류 지령**: int8, 스케일링 없음 (직접 전류값)

## 4. 체크섬 계산
- 방식: 단순 합 체크섬 (Sum Checksum)
- 계산: 데이터 바이트들의 합을 구한 후 하위 8비트만 사용
- Master → SCADA: Sum(Byte1~4) & 0xFF
- SCADA → Master: Sum(Byte1~6) & 0xFF

## 5. 통신 파라미터
- Baud Rate: 38400 bps (기본값)
- Data Bits: 8
- Stop Bits: 1
- Parity: None
- Flow Control: None


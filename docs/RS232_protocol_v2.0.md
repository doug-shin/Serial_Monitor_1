<<<<<<<< HEAD:docs/RS232_interface_protocol_1.md
# RS232 Interface 프로토콜 명세서 1.0
========
# RS232 Interface 프로토콜 v2.0

본 문서는 RS232 시리얼 통신 기반의 Power Control Module 시스템에서 사용되는 프로토콜 v2.0 명세입니다.
>>>>>>>> 2e48dab (feat(v0.7): Dual/Parallel UI, independent channels, protocol v2.0 docs, default baud 115200; version bump to 0.7):docs/RS232_protocol_v2.0.md

## 1. Master → SCADA (7 bytes)

### 1.1 시스템 전압 (ID = 0)
| Byte | Field | Description | Type | Range |
|------|-------|-------------|------|---------|
| 0 | STX | Start of Text | 0x02 | - |
| 1 | ID + Reserved | bit[7:3]: ID=0<br>bit[2:0]: Reserved | uint8 | ID: 0~31 |
| 2-3 | System Voltage | Big-endian<br>Scale: ÷10 | int16 | -3276.8 ~ +327.7 V |
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

## 3. 데이터 타입 및 스케일링 요약

- 시스템 전압: int16, ÷10
- 슬레이브 전류: int16, ÷100
- 슬레이브 온도: uint8, ×0.5

## 4. 체크섬 계산

- Sum Checksum (하위 8비트 사용)
- Master → SCADA: Sum(Byte1~4) & 0xFF
- SCADA → Master: Sum(Byte1~6) & 0xFF

## 5. 통신 파라미터 (v2.0)

- Baud Rate: 115200 bps (기본값)
- Data Bits: 8
- Stop Bits: 1
- Parity: None
- Flow Control: None



# RS232 Interface 프로토콜 v1.0

본 문서는 기존 시스템에서 사용되던 RS232 프로토콜 v1.0의 개요입니다. 상세 규격은 과거 문서 기준이며, v2.0 대비 차이만 요약합니다.

## 1. Master → SCADA (7 bytes)
- STX(0x02), ETX(0x03)
- Byte1: ID(5bit) + Reserved(3bit)
- ID=0: System Voltage (int16, ÷10)
- ID≠0: Current(int16, ÷100), Temp(uint8, ×0.5)
- Checksum: Sum(Byte1~4) & 0xFF

## 2. SCADA → Master (9 bytes)
- STX/ETX 동일
- Command: 0x00 Stop / 0x01 Start
- Max/Min Voltage: int16 (0~1000), 스케일 없음
- Current Command: int8 (-128~127)
- Checksum: Sum(Byte1~6) & 0xFF

## 3. 통신 파라미터 (v1.0)
- Baud Rate: 38400 bps (기본값)
- Data Bits: 8, Stop Bits: 1, Parity: None
- Flow Control: None

## 4. v1.0 ↔ v2.0 주요 차이
- 기본 Baud: v1.0=38400 → v2.0=115200
- 프레임 구조/스케일: 동일

> 참고: 이 파일은 기존 문서를 요약 정리한 것으로, 필요시 상세 원문을 추가로 병합하세요.

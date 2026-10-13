# LoRaWAN Integration & Network Decoder Guide

## 1. Network Architecture

The AquaGuard detector functions as a municipal early-warning node:

```
┌─────────────────────────────────────────────────────────┐
│              AQUAGUARD DETECTOR NODE                    │
│                                                         │
│  [STM32 MCU]              [QRB2210 Linux]               │
│  5 Physical Sensors        Optical Vision Chamber       │
│         │                         │                     │
│         └──────────┬──────────────┘                     │
│                    ▼                                    │
│        Contamination Fusion Engine                      │
│                    │                                    │
│                    ▼                                    │
│        15-Byte Binary Packet Encoder                    │
│                    │                                    │
│                    ▼                                    │
│        LoRaWAN Modem: Ebyte E78-900M22S                 │
│        (ASR6505 / SX1262, +22dBm, IN865 Band)           │
└────────────────────┬────────────────────────────────────┘
                     │  868 MHz / 915 MHz / 865 MHz (RF)
                     ▼
         ┌───────────────────────┐
         │ Municipal LoRa Gateway│
         └───────────┬───────────┘
                     │  IP / Cellular Backhaul
                     ▼
  ┌─────────────────────────────────────┐
  │ Network Server (TTN / ChirpStack)    │
  │ Decodes 15-byte Payload via Codec   │
  └──────────────────┬──────────────────┘
                     │  MQTT / Webhooks
                     ▼
  ┌─────────────────────────────────────┐
  │ Municipal SCADA / Emergency SMS     │
  └─────────────────────────────────────┘
```

---

## 2. 15-Byte Compact Binary Payload Specification

To operate reliably within regional radio regulations (e.g. 1% duty cycle in Europe) and achieve maximum RF range (SF10–SF12), the payload is packed into **15 bytes**:

| Byte Offset | Field Name | Data Type | Scaling Factor | Range / Description |
| :--- | :--- | :--- | :--- | :--- |
| **Byte 0** | Header / Hazard Code | `uint8` | Bitfield | **Bit 7**: Alert Flag (`1` = Alarm, `0` = Routine)<br>**Bits 0–3**: Hazard Code (`0x00`–`0x08`) |
| **Byte 1** | Water Quality Index (WQI) | `uint8` | 1 | $0 - 100$ ($>85$ = Safe, $<50$ = Critical) |
| **Bytes 2–3** | pH Level | `uint16_BE` | $\times 100$ | $0 - 1400$ ($742 \implies 7.42\text{ pH}$) |
| **Bytes 4–5** | Turbidity | `uint16_BE` | $\times 10$ | $0 - 30000$ ($45 \implies 4.5\text{ NTU}$) |
| **Bytes 6–7** | Total Dissolved Solids | `uint16_BE` | 1 | $0 - 65535\text{ ppm}$ |
| **Bytes 8–9** | ORP (Redox Disinfection)| `int16_BE` | 1 | $-2000\text{ to }+2000\text{ mV}$ (Signed) |
| **Bytes 10–11**| Water Temperature | `int16_BE` | $\times 10$ | $-400\text{ to }+1000$ ($215 \implies 21.5^\circ\text{C}$) |
| **Byte 12** | Visual Clarity Index | `uint8` | 1 | $0 - 100\%$ |
| **Byte 13** | Suspended Particulates | `uint8` | 1 | $0 - 255$ Particle Count |
| **Byte 14** | Optical Anomaly Flags | `uint8` | Bitfield | **Bit 0**: Surface Sheen Detected<br>**Bit 1**: Discoloration Anomaly |

### Hazard Codes Reference:
- `0x00`: Normal Potable Water
- `0x01`: Disinfection Loss ($ORP < 580\text{ mV}$)
- `0x02`: Acid Contamination ($pH < 6.0$)
- `0x03`: Caustic / Alkaline Influx ($pH > 9.0$)
- `0x04`: Biological Sewage Ingress (Low ORP, high turbidity, discolored)
- `0x05`: Main Pipe Burst / Heavy Sediment
- `0x06`: Petroleum / Hydrocarbon Surface Oil Sheen
- `0x07`: High Salinity / TDS Intrusion ($TDS > 1000\text{ ppm}$)

---

## 3. The Things Network (TTN) & ChirpStack JavaScript Payload Formatter

Copy and paste this decoder directly into your LoRaWAN Application console (**The Things Stack Console $\rightarrow$ Payload formatters $\rightarrow$ Custom JavaScript formatter** or **ChirpStack $\rightarrow$ Device Profile $\rightarrow$ Codec**):

```javascript
function decodeUplink(input) {
  var bytes = input.bytes;
  if (bytes.length !== 15) {
    return { errors: ["Invalid payload length: expected 15 bytes"] };
  }

  // Byte 0
  var isAlert = (bytes[0] & 0x80) !== 0;
  var hazardCode = bytes[0] & 0x0F;

  var hazardNames = {
    0: "NONE",
    1: "DISINFECTION_LOSS",
    2: "ACID_CONTAMINATION",
    3: "CAUSTIC_ALKALINE",
    4: "SEWAGE_INGRESS",
    5: "SEDIMENT_PIPE_BURST",
    6: "HYDROCARBON_SHEEN",
    7: "HIGH_SALINITY_TDS",
    8: "GENERAL_DEGRADATION"
  };

  // Byte 1
  var wqi = bytes[1];

  // Bytes 2-3: pH * 100
  var phRaw = (bytes[2] << 8) | bytes[3];
  var ph = phRaw / 100.0;

  // Bytes 4-5: Turbidity * 10
  var turbRaw = (bytes[4] << 8) | bytes[5];
  var turbidityNtu = turbRaw / 10.0;

  // Bytes 6-7: TDS
  var tdsPpm = (bytes[6] << 8) | bytes[7];

  // Bytes 8-9: ORP mV (Signed int16)
  var orpRaw = (bytes[8] << 8) | bytes[9];
  if (orpRaw & 0x8000) orpRaw -= 0x10000;

  // Bytes 10-11: Temp * 10 (Signed int16)
  var tempRaw = (bytes[10] << 8) | bytes[11];
  if (tempRaw & 0x8000) tempRaw -= 0x10000;
  var tempC = tempRaw / 10.0;

  // Byte 12: Clarity %
  var clarityPct = bytes[12];

  // Byte 13: Particle Count
  var particleCount = bytes[13];

  // Byte 14: Flags
  var surfaceSheen = (bytes[14] & 0x01) !== 0;
  var discolorationAnomaly = (bytes[14] & 0x02) !== 0;

  return {
    data: {
      alert_active: isAlert,
      hazard_code: hazardCode,
      hazard_description: hazardNames[hazardCode] || "UNKNOWN",
      wqi_score: wqi,
      ph: ph,
      turbidity_ntu: turbidityNtu,
      tds_ppm: tdsPpm,
      orp_mv: orpRaw,
      temperature_c: tempC,
      optical_clarity_percent: clarityPct,
      particulate_count: particleCount,
      surface_sheen_detected: surfaceSheen,
      discoloration_detected: discolorationAnomaly
    }
  };
}
```

---

## 4. India Regional Configuration: IN865 Band (865 - 867 MHz)

For deployment across rural India under the **Jal Jeevan Mission**, the modem is configured for the **IN865-867** band, governed by India's Wireless Planning & Coordination (WPC) Wing:

### Frequency Channels:
- **Uplink Channel 0**: `865.0625 MHz` (BW 125 kHz, DR0 - DR5)
- **Uplink Channel 1**: `865.4025 MHz` (BW 125 kHz, DR0 - DR5)
- **Uplink Channel 2**: `865.9850 MHz` (BW 125 kHz, DR0 - DR5)
- **RX2 Downlink**: `866.5500 MHz` (DR2 / SF10, BW 125 kHz)
- **Max EIRP**: `+30 dBm` (1 Watt)

---

## 5. Ebyte E78-900M22S Modem Configuration & AT Command Guide

The **Ebyte E78-900M22S** incorporates the **ASR6505 SoC** (Semtech **SX1262** transceiver + STM8L152 microcontroller) offering high sensitivity ($-140\text{ dBm}$) and up to **+22 dBm** transmission power.

### A. Ebyte E78-900M22S Hardware Pinout & Wiring

| E78 Pin | Signal Name | Connection Target | Description |
| :--- | :--- | :--- | :--- |
| **VCC** | Power In | **3.3V Rail** on Arduino UNO Q | $1.8\text{ V} - 3.7\text{ V}$ DC ($>150\text{ mA}$ peak current) |
| **GND** | System Ground | **GND Rail** (Star Ground) | Common ground reference |
| **TXD** | UART Out | **Arduino UNO Q D0 (RX)** or USB-UART RXD | 3.3V TTL output from modem |
| **RXD** | UART In | **Arduino UNO Q D1 (TX)** or USB-UART TXD | 3.3V TTL input to modem (no shifter required) |
| **NRST** | Active-Low Reset| Arduino UNO Q D3 (Optional) | Pull up to 3.3V with $10\text{ k}\Omega$ resistor |
| **IPEX** | RF Antenna Port| 865-867 MHz 50Ω Antenna | Connect via IPEX-to-SMA pigtail cable |

### B. AT Command Sequence for Ebyte E78-900M22S (IN865 OTAA)

Connect via serial terminal at **9600 baud, 8 data bits, no parity, 1 stop bit (8N1)**:

```bash
# 1. Test basic AT communication
AT
# Response: OK

# 2. Query module model and firmware version
AT+CGMI?
# Response: +CGMI:Ebyte
AT+CGMM?
# Response: +CGMM:E78-900M22S

# 3. Configure OTAA Join Mode (0 = OTAA, 1 = ABP)
AT+CJOINMODE=0
# Response: OK

# 4. Set LoRaWAN Identity Keys (EUIs & AppKey)
AT+CDEVEUI=70B3D57ED006A1B2
# Response: OK
AT+CAPPEUI=0000000000000000
# Response: OK
AT+CAPPKEY=2B7E151628AED2A6ABF7158809CF4F3C
# Response: OK

# 5. Configure Frequency Band Mask for India IN865 (Channels 0-2)
AT+CFREQBANDMASK=0001
# Response: OK

# 6. Set RF Transmit Power (+22 dBm for rural coverage)
AT+CRFTXPOW=0
# Response: OK (0 indicates maximum power: 22 dBm)

# 7. Enable Adaptive Data Rate (ADR)
AT+CADR=1
# Response: OK

# 8. Set Device Class (0 = Class A for lowest power)
AT+CCLASS=0
# Response: OK

# 9. Initiate Network Join (1 = Join, 0 = Auto, 10s step, 8 attempts)
AT+CJOIN=1,0,10,8
# Response: OK
# Followed asynchronously upon gateway handshake: +CJOIN:OK

# 10. Check Join Status
AT+CJOIN?
# Response: +CJOIN:OK (1,0)
```

### C. Transmitting Binary Water Contamination Payloads

The Ebyte E78-900M22S firmware uses the `AT+DTRX` command format:
$$\text{AT+DTRX}=\langle\text{confirm}\rangle,\,\langle\text{f\_port}\rangle,\,\langle\text{data\_length}\rangle,\,\langle\text{hex\_payload}\rangle$$

- **Routine Heartbeat Uplink (Port 10, Unconfirmed, 15 bytes)**:
  ```bash
  AT+DTRX=0,10,15,005E02E6000400B902A300D75F0200
  # Response: OK+SENT
  ```

- **Urgent Emergency Alert Uplink (Port 15, Confirmed with Gateway ACK, 15 bytes)**:
  ```bash
  AT+DTRX=1,15,15,841C027600550352FF8800F01E2D02
  # Response: OK+SENT
  # Followed by gateway downlink ACK confirmation: OK+RECV:00,00,00
  ```

---

## 6. Alternative Modem Reference (RAK3172 / LoRa-E5)

If substituting with a RAK3172 or Seeed LoRa-E5 module:
```bash
AT+BAND=7          # 7 = IN865 for RAK3172
AT+JOIN=1:0:10:8   # Join OTAA
AT+DEVEUI=70B3D57ED006A1B2
AT+APPEUI=0000000000000000
AT+APPKEY=2B7E151628AED2A6ABF7158809CF4F3C
AT+SEND=15:1:805E02E6000400B902A300D75F0200
```

# AquaWatch: Hardware Wiring & Electrical Guide
### Edge-AI LoRaWAN Water Quality Monitoring for Rural India

## Architecture Overview
The **Arduino UNO Q** integrates an **STM32U585 MCU** (handling deterministic real-time analog/digital sensor reading) and a **Qualcomm QRB2210 MPU** (running Linux, computer vision via USB camera, and network services).

---

## 1. Pin Assignment Table

| Function | Arduino UNO Q Header Pin | Target Sensor / Actuator | Signal Type | Electrical Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **pH Probe** | `A0` | Analog pH Signal Board *(Not connected in current prototype / Static: 7.35)* | Analog ($0 - 3.3\text{ V}$) | High-Z BNC (Not connected in current prototype) |
| **Turbidity** | `A1` | **ASAIR AZDM01 Photoelectric (940nm IR)** | Analog ($0 - 3.3\text{ V}$ scaled) | 3.3V powered; 10k/30k divider to Pin A1 |
| **TDS Sensor** | `A2` | Analog TDS Conductivity Probe *(Not connected in current prototype / Static: 180 ppm)* | Analog ($0 - 2.3\text{ V}$) | AC-excited board (Not connected in current prototype) |
| **ORP Probe** | `A3` | Redox Potential Board *(Not connected in current prototype / Static: 675 mV)* | Analog ($0 - 3.3\text{ V}$) | $1.65\text{ V}$ midpoint (Not connected in current prototype) |
| **Water Temp** | `D2` | DS18B20 Waterproof Probe | Digital (1-Wire) | $4.7\text{ k}\Omega$ pull-up resistor to $+3.3\text{ V}$ |
| **Spectral Sensor** | `SDA / SCL` | **Adafruit AS7341 10-Channel Spectrophotometer** | Digital (I2C 0x39) | Direct 3.3V / 5V I2C; Onboard LED illumination |
| **LoRaWAN Radio**| `D0 / D1` (or USB-UART) | **Ebyte E78-900M22S** (ASR6505 / SX1262) | 3.3V UART (9600 baud) | **IN865 Band (865 - 867 MHz)**; +22 dBm RF power |
| **USB Camera** | `USB-A / USB-C Host` | UVC Compliant USB Camera (720p/1080p) | USB 2.0 / 3.0 | Connected directly to QRB2210 Host port through USB HuB|
| **Power In** | `USB-C` | Input to USB HUB USB-C PD port   |5V 2A Wall charger| Supplies both QRB2210 MPU and STM32 |


---

## 2. ASAIR AZDM01 Turbidity Sensor Wiring & Interfacing

The **ASAIR AZDM01** is a high-reliability photoelectric turbidity sensor utilizing a 940nm infrared beam and phototransistor receiver. It features a 3-pin XHB2.54mm connector:

```
    ┌───────────────────────────────────┐
    │       ASAIR AZDM01 SENSOR         │
    │   PIN 1       PIN 2       PIN 3   │
    │   [+5V]       [PT]      [IR_ADJ]  │
    └─────┬───────────┬───────────┬─────┘
          │           │           │
          │           │           └─── Connect to GND (via 100Ω or direct)
          │           │
          │           └─── [R1: 10 kΩ, 0.1%] ──┬──> To STM32 Pin A1 (0 - 3.3V)
          │                                    │
          │                               [R2: 30 kΩ, 0.1%]
          │                                    │
          │                                   GND
          │
          └─── Connect to +3.3V Rail (4.8V - 5.5V DC)
```

### Voltage Divider Math:
- **Clean Water Output ($U_0$)**: $3.80\text{ V}$ nominal at Pin 2 (PT).
- **Divider Attenuation Factor**:
  $$\text{Divider Ratio} = \frac{R_2}{R_1 + R_2} = \frac{30\text{ k}\Omega}{10\text{ k}\Omega + 30\text{ k}\Omega} = \frac{2}{3} \approx 0.75$$
- **Voltage at STM32 Pin A1 in Clean Water**:
  $$V_{\text{ADC}} = 3.19\text{ V} \times 0.75 = 2.39\text{ V}$$
  This safely stays below the $3.30\text{ V}$ ceiling of the STM32 ADC.
- The firmware automatically multiplies by $1.5\times$ to reconstruct true $U_m$ and computes the turbidity ratio $f = U_m / U_0$.



## 3. Grounding & Anti-Interference Isolation (Star Ground)

High-impedance probes (especially **pH** with glass electrode internal resistance $>100\text{ M}\Omega$ and **ORP**) are extremely sensitive to ground noise:
1. **Star Ground Topology**: Connect the ground wires of the pH, ORP, Turbidity, and TDS boards to a single central ground bus bar before tying to the Arduino UNO Q `GND`.
2. **TDS Isolation**: TDS probes emit high-frequency AC square waves to prevent electrode electrolysis. If the TDS probe is placed in the exact same water beaker as the pH or ORP probes without electrical isolation, the AC excitation can inject noise into the pH/ORP readings.
   - *Recommendation*: Mount the TDS probe downstream of the pH and ORP probes in the flow loop, or space them at least $10\text{ cm}$ apart.
3. **LoRa Antenna Placement**: LoRaWAN signals at 868/915 MHz propagate via ground plane reflections. Ensure the SMA or whip antenna is mounted externally outside the metallic enclosure, oriented vertically, and kept at least 5 cm away from the USB camera cable to minimize RF desensitization.

---

## 4. DS18B20 Waterproof Temperature Sensor Wiring

The DS18B20 digital temperature probe communicates over Dallas 1-Wire protocol:
```
DS18B20 Probe:
- RED wire   ──>  +3.3V
- BLACK wire ──>  GND
- YELLOW/BLUE wire (Data) ──┬──> Arduino UNO Q Pin D2
                            │
                            [4.7 kΩ Pull-up Resistor]
                            │
                           +3.3V
```

---

## 5. Ebyte E78-900M22S LoRaWAN Module Wiring & Interfacing

The **Ebyte E78-900M22S** is based on the **ASR6505 SoC** (integrating an STMicroelectronics STM8L152 MCU and Semtech SX1262 LoRa transceiver) providing up to **+22 dBm (~160 mW)** RF transmission power across 850 – 925 MHz (ideal for India IN865).

### Module Interface & Pinout:
```
                      ┌─────────────────────────────────┐
                      │    Ebyte E78-900M22S MODULE     │
                      │       (ASR6505 / SX1262)        │
                      │                                 │
                      │ [VCC]  [GND]  [TXD]  [RXD] [RST]│
                      └───┬──────┬──────┬──────┬─────┬──┘
                          │      │      │      │     │
                          │      │      │      │     └──> Optional: Reset pin to Pin D3
                          │      │      │      │          (or pull-up to 3.3V via 10kΩ)
                          │      │      │      │
                          │      │      │      └───> Connect to Arduino UNO Q Pin D1 (TX)
                          │      │      │            or USB-UART TXD (Native 3.3V TTL)
                          │      │      │
                          │      │      └──────────> Connect to Arduino UNO Q Pin D0 (RX)
                          │      │                   or USB-UART RXD (Native 3.3V TTL)
                          │      │
                          │      └─────────────────> Connect to System Star Ground (GND)
                          │
                          └────────────────────────> Connect to 3.3V DC Power Rail
                                                     (Requires >= 150mA transient capability)
```

### Electrical Characteristics & Notes:
1. **Supply Voltage**: $1.8\text{ V} - 3.7\text{ V}$ DC (Nominal **$3.3\text{ V}$**).
   - Peak current during $+22\text{ dBm}$ transmission bursts reaches $\approx 110 - 140\text{ mA}$. Ensure the 3.3V regulator on the Arduino UNO Q or external LDO (e.g. AMS1117-3.3) has adequate thermal and decoupling headroom ($10\mu\text{F}$ electrolytic + $100\text{ nF}$ ceramic capacitor placed adjacent to VCC/GND pins).
2. **Native 3.3V Logic (No Shifter Needed)**:
   - Unlike the 5V AZDM01 turbidity sensor, the E78-900M22S UART pins (TXD, RXD) operate natively at **3.3V TTL**.
   - They connect **directly** to Arduino UNO Q pins D0 (RX) and D1 (TX), or to a 3.3V USB-to-UART bridge without any resistor divider or voltage level shifter.
3. **RF Antenna Connection**:
   - The module provides an IPEX (U.FL) coaxial micro-connector or RF pin.
   - Use an IPEX-to-SMA pigtail cable leading to an external $865 - 867\text{ MHz}$, $50\ \Omega$ omnidirectional rubber duck or collinear antenna (2 dBi to 5 dBi gain).
   - Keep the antenna mounted outside any metal enclosures and at least 5 cm away from the camera ribbon/USB cable.

---

## 6. Adafruit AS7341 10-Channel Multi-Spectral Sensor Wiring

The **Adafruit AS7341** 10-channel light and color spectrometer operates over standard I2C at address `0x39`. It integrates an onboard white illumination LED for active transmission spectrometry through the water sample.

### Electrical Connections:
```
Adafruit AS7341 Breakout:
- VIN  ──> +3.3V DC (Arduino UNO Q 3.3V rail)
- GND  ──> Star Ground (GND)
- SDA  ──> Arduino UNO Q SDA pin (Hardware I2C Data)
- SCL  ──> Arduino UNO Q SCL pin (Hardware I2C Clock)
```

### Optical Flow-Cell Alignment:
1. **Flow-Cell Integration**: Mount the AS7341 breakout board on the flow-cell opposite or orthogonal to the camera window, positioning the sensor photodiodes directly against the borosilicate glass wall.
2. **Illumination LED**: The breakout board includes an onboard white LED. The firmware enables this LED during spectral sampling (4mA current limit) to pass light through the water column directly into the photodiodes, measuring transmission and absorption across the 8 visible wavelengths (415nm – 680nm), Clear, and NIR (910nm).
3. **Ambient Light Shielding**: Ensure the flow-cell inspection chamber is enclosed in an opaque (black 3D-printed or ABS) shroud to prevent ambient sunlight from skewing the spectral readings.

# AquaWatch: Master Installation, Wiring & Deployment Guide
### Edge-AI LoRaWAN Water Quality Monitoring for Rural India (Jal Jeevan Mission)

This guide provides step-by-step instructions for wiring, building, flashing, and deploying the **AquaWatch** node on the **Arduino UNO Q** (Dual-Architecture: STMicroelectronics STM32U585 MCU + Qualcomm Dragonwing QRB2210 MPU).

---

## 1. Hardware Bill of Materials (BOM)

| Component | Specification | Quantity | Role |
| :--- | :--- | :--- | :--- |
| **Main Processing Board** | **Arduino UNO Q** | 1 | Dual MPU (Qualcomm QRB2210 Linux) + MCU (STM32U585) |
| **Turbidity Sensor** | **ASAIR AZDM01** (940nm Photoelectric) | 1 | Suspended sediment, colloidal silt, monsoon runoff |
| **Spectral Sensor** | **Adafruit AS7341** 10-Channel Spectrometer | 1 | Algae bloom (chlorophyll-a), organic CDOM, industrial dye |
| **pH Sensor** | Analog pH Probe + Conditioning Board *(Optional / Static Mode: 7.35)* | 1 | Acidity / alkalinity detection (or safe static BIS baseline) |
| **Conductivity (TDS)** | Analog Titanium TDS Probe *(Optional / Static Mode: 180 ppm)* | 1 | Dissolved solids, salinity (or safe static BIS baseline) |
| **ORP Sensor** | Platinum Redox Probe *(Optional / Static Mode: 675 mV)* | 1 | Disinfection efficacy (or safe static CPHEEO baseline) |
| **Temperature Sensor** | **DS18B20** Waterproof Probe (Stainless Steel) | 1 | Water temperature & dynamic Nernst/TDS compensation |
| **Optical Inspection** | USB Macro Camera (UVC Compliant, 720p/1080p) | 1 | Visual flow-cell inspection (sheen, rust, particles) |
| **Optical Flow Chamber** | Clear Borosilicate Glass / Acrylic (25x25mm) | 1 | Continuous fluidic inspection chamber |
| **LoRaWAN Radio** | **Ebyte E78-900M22S** (ASR6505 / SX1262, +22 dBm) | 1 | Long-range rural emergency alert telemetry (IN865 Band) |
| **Storage** | MicroSD Card (Class 10, FAT32/ext4, 16GB–64GB) | 1 | Automated 1-minute high-res image & JSON logging |
| **Resistors** | 10 kΩ (0.1% or 1%), 20 kΩ (0.1% or 1%), 4.7 kΩ | 1 each | AZDM01 voltage divider (10k/20k) & DS18B20 pullup (4.7k) |
| **Power Supply** | 12V DC Regulated Power Adapter (≥ 2.5A) | 1 | Powers Arduino UNO Q Barrel Jack / VIN rail |


---

## 2. Complete Wiring Diagram & Electrical Schematics

```
                                      ARDUINO UNO Q
                      ┌──────────────────────────────────────────────┐
                      │                                              │
                      │  [POWER RAILS]                               │
                      │   VIN  ───────> +12V DC (From Power Supply)  │
                      │   5V   ───────┬────────────────────────────┐ │
                      │   3V3  ───────┼──────────────┐             │ │
                      │   GND  ───────┼─────────┐    │             │ │
                      │               │         │    │             │ │
                      │  [ANALOG IN]  │         │    │             │ │
                      │   A0 ─────────┼─────────┼────┼──[pH Probe Board OUT]
                      │   A1 ─────────┼─────────┼────┼──[AZDM01 Divider OUT]
                      │   A2 ─────────┼─────────┼────┼──[TDS Probe Board OUT]
                      │   A3 ─────────┼─────────┼────┼──[ORP Probe Board OUT]
                      │               │         │    │             │ │
                      │  [DIGITAL IN] │         │    │             │ │
                      │   D2 ─────────┼─────────┼────┼──[DS18B20 Data]
                      │   D0/D1 ──────┼─────────┼────┼──[LoRa Modem RX/TX]
                      │               │         │    │             │ │
                      │  [USB HOST]   │         │    │             │ │
                      │   USB-A/C ────┼─────────┼────┼──[USB Camera]
                      │   SD SLOT ────┼─────────┼────┼──[MicroSD Card]
                      └───────────────┼─────────┼────┼─────────────┘ │
                                      │         │    │               │
                                      ▼         ▼    ▼               ▼
```

### A. ASAIR AZDM01 Turbidity Sensor Wiring (Pin A1)
The AZDM01 operates on 5.0V and outputs $U_0 = 3.80\text{V}$ in clean water. To safely interface with the 3.3V ADC of the STM32 MCU, use a precision $10\text{ k}\Omega / 20\text{ k}\Omega$ resistor divider:

```
AZDM01 3-Pin Connector (XHB2.54mm):
- PIN 1 (VCC)    ──> Connect to Arduino UNO Q 5V Rail
- PIN 3 (IR_ADJ) ──> Connect to GND (via 100Ω or direct for full IR power)
- PIN 2 (PT Out) ──┬──[ R1: 10 kΩ Resistor ]──┬──> Connect to STM32 Pin A1
                   │                          │
                  (3.8V)                 [ R2: 20 kΩ Resistor ]
                                              │
                                             GND (Star Ground)
```
- **Voltage Math**: $V_{\text{ADC}} = 3.80\text{V} \times \frac{20\text{k}}{10\text{k} + 20\text{k}} = 2.533\text{V}$ (Safely below the 3.3V ADC limit).
- The firmware automatically multiplies by $1.5\times$ to recover $U_m$ and computes ratio $f = U_m / 3.80\text{V}$.

---

### B. DS18B20 Digital Temperature Sensor Wiring (Pin D2)
```
DS18B20 Waterproof Cable:
- RED wire   (VDD) ──> Connect to 3.3V Rail
- BLACK wire (GND) ──> Connect to GND Rail
- YELLOW wire (Data) ──┬──> Connect to Arduino UNO Q Pin D2
                       │
                  [ 4.7 kΩ Pull-up Resistor ]
                       │
                      3.3V Rail
```

---

### C. pH, TDS, and ORP Sensor Connections (Physical Probes OR Cost-Saving Static Mode)

Physical pH glass electrodes (₹1,500 – ₹3,500) and laboratory TDS/ORP probes (₹2,000 – ₹4,000) are expensive and require regular buffer recalibration. To enable affordable student prototypes and low-cost village pilot deployments, AquaWatch includes **native Static Baseline Modes** for all three parameters:

1. **pH Sensor (`A0`)**:
   - **With Physical Probe**: Signal $\to$ `A0`, VCC $\to$ `3V3`, GND $\to$ Star Ground. In `water_sensor_node.ino`, set `#define USE_PHYSICAL_PH_SENSOR 1`.
   - **Cost-Saving Static Mode (No Probe Required)**: Leave `A0` disconnected! Keep `#define USE_PHYSICAL_PH_SENSOR 0`. The node injects a safe, nominal **7.35 pH** baseline (BIS IS 10500 compliant: $6.5 - 8.5$) with natural ADC micro-jitter, displaying a `STATIC` badge on the web dashboard.
2. **TDS Conductivity Sensor (`A2`)**:
   - **With Physical Probe**: Signal $\to$ `A2`, VCC $\to$ `3V3`, GND $\to$ Star Ground. Set `#define USE_PHYSICAL_TDS_SENSOR 1`. Place the probe downstream to avoid AC square-wave interference.
   - **Cost-Saving Static Mode (No Probe Required)**: Leave `A2` disconnected! Keep `#define USE_PHYSICAL_TDS_SENSOR 0`. The node injects a safe mineral baseline of **180.0 ppm** (BIS limit: $< 500\text{ ppm}$).
3. **ORP Redox Sensor (`A3`)**:
   - **With Physical Probe**: Signal $\to$ `A3`, VCC $\to$ `3V3`, GND $\to$ Star Ground. Set `#define USE_PHYSICAL_ORP_SENSOR 1`.
   - **Cost-Saving Static Mode (No Probe Required)**: Leave `A3` disconnected! Keep `#define USE_PHYSICAL_ORP_SENSOR 0`. The node injects a nominal **675.0 mV** tap-water chlorinated baseline (CPHEEO target: $> 650\text{ mV}$).

> [!TIP]
> **Recommended Low-Cost Deployment Setup**:
> For budget-constrained deployments under the Jal Jeevan Mission, you only need to connect:
> 1. **ASAIR AZDM01 Turbidity Sensor** (Pin A1 via 10k/20k divider) — detects silt, pipe bursts, monsoon runoff, and suspended solids.
> 2. **DS18B20 Temperature Probe** (Pin D2 with 4.7k pull-up) — provides thermal tracking.
> 3. **USB Camera Viewing Flow Cell** — detects oil sheen, chemical discoloration, and particulate blobs.
> 4. **Ebyte E78-900M22S LoRaWAN Node** (Pins D0/D1) — sends emergency alerts and routine telemetry.
> 
> Keep pH, TDS, and ORP in **Static Mode**. This saves over ₹5,000–₹8,000 in hardware costs while retaining full computer vision, turbidity detection, and LoRaWAN alerting functionality!

---

### D. LoRaWAN Radio Module: Ebyte E78-900M22S (IN865 India Band)
- **Modem Model**: **Ebyte E78-900M22S** (ASR6505 SoC + Semtech SX1262 LoRa transceiver, +22 dBm power).
- **VCC**: Connect to Arduino UNO Q **3V3 Rail** (must support $\ge 150\text{ mA}$ during TX bursts).
- **GND**: Connect to common system **GND**.
- **TXD (Module Out)**: Connect to Arduino UNO Q **D0** (STM32 RX) or USB-UART RXD.
- **RXD (Module In)**: Connect to Arduino UNO Q **D1** (STM32 TX) or USB-UART TXD.
- *Logic Level Note*: Native 3.3V TTL logic — no level converter required!
- *Antenna*: Connect an 865–867 MHz 50Ω antenna via IPEX/U.FL to SMA pigtail.
- *Alternative*: Connect via CP2102/CH340 USB-UART dongle plugged directly into the QRB2210 USB host port (`/dev/ttyUSB0`).

---

## 3. Part 1: Flashing the STM32 MCU Firmware

### Step 1: Install Arduino IDE & Board Package
1. Download and install **Arduino IDE 2.3+** (or Arduino App Lab).
2. Add the **Arduino UNO Q (STM32U585 Core)** board package via Boards Manager.
3. Install required libraries via Library Manager (`Ctrl + Shift + I`):
   - **Adafruit AS7341** (by Adafruit) — for 10-channel multi-spectral analysis
   - **OneWire** (by Paul Stoffregen / Jim Studt)
   - **DallasTemperature** (by Miles Burton)

### Step 2: Configure Firmware
Open `mcu_firmware/water_sensor_node.ino`.
Verify the hardware options:
```cpp
#define USE_PHYSICAL_PH_SENSOR     0  // 0 = Static 7.35 pH baseline (Save ₹2,500)
#define USE_PHYSICAL_TDS_SENSOR    0  // 0 = Static 180 ppm baseline (Save ₹3,000)
#define USE_PHYSICAL_ORP_SENSOR    0  // 0 = Static 675 mV baseline (Save ₹3,500)
#define USE_AS7341_SPECTRAL_SENSOR 1  // 1 = Enable Adafruit AS7341 10-Channel Spectrophotometer
```


### Step 3: Compile and Flash
1. Select Board: **Arduino UNO Q -> STM32 Core**.
2. Select Port (e.g. `COM5` on Windows or `/dev/ttyACM0` on Linux).
3. Click **Upload** (`Ctrl + U`).
4. Open the Serial Monitor at **115200 baud**. You should see:
   ```text
   [STM32] RouterBridge RPC Server active for QRB2210.
   [STM32] AquaWatch Rural India Water Monitor Ready (AZDM01 Turbidity).
   {"temp_c":21.50,"ph":7.40,"turbidity_ntu":0.35,"tds_ppm":180.0,"orp_mv":675.0,"orp_dummy":true,"alert":false,"hazard_code":0,"samples":1,"uptime_ms":1000}
   ```

---

## 4. Part 2: Configuring the Qualcomm QRB2210 Linux Environment

The QRB2210 runs Debian Linux. Connect to it via SSH or serial console:
```bash
ssh root@<uno-q-ip-address>
```

### Step 1: Clone or Copy Project Code
Copy the project folder to the QRB2210:
```bash
mkdir -p /opt/aquawatch
cd /opt/aquawatch
```

### Step 2: Create Python Virtual Environment & Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r mpu_vision_service/requirements.txt
```
*(Dependencies: `fastapi`, `uvicorn[standard]`, `opencv-python-headless`, `numpy`, `scikit-learn`, `pyserial`)*

### Step 3: Format & Mount MicroSD Card
Insert your MicroSD card (FAT32 or ext4 formatted) into the onboard slot:
```bash
mkdir -p /media/sdcard/samples
# If not auto-mounted by udev:
mount /dev/mmcblk1p1 /media/sdcard
```

### Step 4: Verify USB Camera Access
Plug in the USB inspection camera and check:
```bash
v4l2-ctl --list-devices
# Should list /dev/video0 (UVC Camera)
```

---

## 5. Part 3: Running the Full AquaWatch Service

### Interactive Execution (For Testing & Verification)
```bash
cd /opt/aquawatch/mpu_vision_service
source ../venv/bin/activate
python dashboard_app.py
```
Output:
```text
INFO:     Started server process
INFO:     Waiting for application startup.
[INFO] BridgeClient: Connected to STM32 via RouterBridge RPC
[INFO] SDCardManager: SD card active at /media/sdcard. Circular buffer quota: 16.0 GB
[INFO] LoRaWANService: IN865 band active (Channels: 865.0625, 865.4025, 865.9850 MHz)
--> Executing 1-minute water quality sampling cycle...
--> Sample complete: WQI=94.5 | Status=SAFE
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

### Production Deployment (Auto-start via Systemd Service)
To make the node boot up automatically on power restore:

1. Create service file:
   ```bash
   sudo nano /etc/systemd/system/aquawatch.service
   ```
2. Paste configuration:
   ```ini
   [Unit]
   Description=AquaWatch Edge-AI Water Quality Monitor (Jal Jeevan Mission)
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/aquawatch/mpu_vision_service
   ExecStart=/opt/aquawatch/venv/bin/python dashboard_app.py
   Restart=always
   RestartSec=5
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```
3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable aquawatch
   sudo systemctl start aquawatch
   sudo systemctl status aquawatch
   ```

---

## 6. Accessing the Minimalist SCADA Web UI

Open any browser on the local network:
```
http://<uno-q-ip-address>:8000/
```

### Features:
1. **Top Bar**: Live status pill (`● BIS POTABLE WATER • WQI 94`) and live countdown ticker (`Next Sample: 00:45`).
2. **Left Panel**: The latest 1-minute high-res flow-cell camera snapshot with timestamp and SD card save path.
3. **Right Panel (Metrics Grid)**:
   - **pH Level**: Live reading (BIS 6.5 – 8.5).
   - **Turbidity (AZDM01)**: Live NTU reading calculated via $f = U_m/U_0$ ratio curve (`940nm IR` badge).
   - **ORP (Disinfection)**: Shows live mV or `[DUMMY]` badge if physical sensor is detached.
   - **Dissolved Solids (TDS)**: Live ppm conductivity (BIS < 500 ppm).
   - **Temperature**: Digital DS18B20 reading (°C).
   - **Edge AI Anomaly Probability**: Multi-variate Isolation Forest threat score.
4. **Action Button**: `[⚡ TAKE SAMPLE NOW]` button to force an immediate camera capture, AI inference, and SD card log.
5. **Bottom Bar**:
   - **LoRaWAN Status**: `IN865 India (Port 10)` with the exact 15-byte hex payload.
   - **MicroSD Status**: Storage health and total sample image count.
   - **Inject Test Scenario**: Dropdown to simulate events (`Normal`, `Disinfection Loss`, `Acid Spill`, `Sewage`, `Pipe Burst`, `Oil Sheen`).

---

## 7. Verifying the Automated Test Suite

To verify all algorithms, math, and AI models:
```bash
python -m unittest discover tests -v
```

---

## 8. Troubleshooting FAQ

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **Turbidity reads 0 NTU or 4000 NTU constantly** | Voltage divider missing or inverted | Verify 10kΩ is between AZDM01 Pin 2 and STM32 A1, and 20kΩ is between A1 and GND. In clean water, voltage at Pin A1 must measure $\approx 2.53\text{V}$. |
| **ORP displays alarming negative values (-1650 mV)** | Open analog pin floating near 0V | In `water_sensor_node.ino`, ensure `#define USE_PHYSICAL_ORP_SENSOR 0` is set. The firmware will inject a safe 675.0 mV baseline. |
| **Camera frame is black or corrupted** | Wrong V4L2 device index | Run `v4l2-ctl --list-devices` and check camera index in `mpu_vision_service/vision_inspector.py` (default `camera_index=0`). |
| **SD card not logging images** | Directory missing or write permissions | Run `sudo mkdir -p /media/sdcard/samples && sudo chmod 777 /media/sdcard/samples`. |
| **LoRaWAN gateway not receiving packets** | Frequency mismatch | Ensure gateway is listening on **IN865 channels** (`865.0625`, `865.4025`, `865.9850 MHz`). |

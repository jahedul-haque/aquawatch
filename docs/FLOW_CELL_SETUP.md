# Optical Inspection Chamber & Flow-Cell Setup Guide

The **Qualcomm QRB2210** processor performs high-speed computer vision inspection of water flowing through an optical chamber. To maximize inspection accuracy, follow these physical mounting and optical alignment guidelines.

---

## 1. Flow-Cell Geometry & Optical Chamber Layout

```
                  Diffused White LED Backlight Panel
                                 │
                 ┌───────────────▼──────────────┐
                 │  Target Pattern (Grid/Lines)  │
                 ├──────────────────────────────┤
                 │  ══════════════════════════  │
Water Inflow ───>│  [Clear Borosilicate / Acrylic]───> Water Outflow
                 │  Flow Inspection Chamber     │
                 │  ══════════════════════════  │
                 └───────────────▲──────────────┘
                                 │
                         Transparent Window
                                 │
                         ┌───────▼───────┐
                         │   Macro Lens  │
                         │   USB Camera  │ (Connected to QRB2210 Host)
                         └───────────────┘
```

### Components:
1. **Chamber Material**: Optical-grade clear cast acrylic or borosilicate glass flow-tube with a square or rectangular cross-section ($20\text{ mm} \times 20\text{ mm}$ or $30\text{ mm} \times 30\text{ mm}$). Avoid round tubes because cylindrical refraction creates optical distortion and lens flares.
2. **Backlight Panel**: 5000K–6500K neutral daylight white LED with a milky acrylic diffuser sheet. Constant DC driving (avoid PWM dimming at low frequencies to prevent camera rolling shutter banding).
3. **Fiducial / Contrast Target**: A high-contrast grid pattern ($2\text{ mm}$ line pitch) placed behind the chamber. When water is crystal clear, the camera resolves the high-frequency edges with high Laplacian variance ($\sigma^2 > 300$). When particulate turbidity or colloidal haziness enters, the edges blur, lowering the clarity metric.

---

## 2. Camera Positioning & Optics

- **Resolution**: $640 \times 480$ or $1280 \times 720$ at 30 FPS.
- **Focus Distance**: Set manual focus on the center of the water column ($5\text{ cm}$ to $10\text{ cm}$ working distance). Disable auto-focus to avoid hunting when water is clear.
- **Exposure Control**: Set fixed exposure and white balance in `v4l2-ctl` or OpenCV to prevent automatic camera gain adjustments from masking water discoloration.

---

## 3. Bubble Elimination & Surface Meniscus Inspection

1. **Upward Water Flow (Bottom-to-Top)**:
   - Introduce municipal sample water into the **bottom** of the chamber and exit through the **top**. This forces micro-bubbles to float rapidly up and out of the inspection frame rather than clinging to the glass walls.
2. **Surface Meniscus Viewing**:
   - Align the camera view so the top 20% of the frame captures the free water surface / liquid-air interface (meniscus). This allows the algorithm to detect surface oil slicks (hydrocarbon rainbow fringes) or surfactant foam.
3. **Anti-Condensation**:
   - If sampling cold tap water ($10^\circ\text{C}$) in a humid environment, external condensation on the glass can mimic turbidity. Keep a small $5\text{V}$ low-noise DC fan blowing warm air from the QRB2210 heatsink across the outer glass face.

---

## 4. ASAIR AZDM01 Sensor In-Line Flow Installation

According to the manufacturer datasheet (ASAIR AZDM01 Section 5):
1. **Perpendicular Flow Direction**:
   - The sensor must be installed such that the **water flow direction is strictly perpendicular to the 940nm infrared light path**.
   - This ensures uniform particulate transit and prevents sediment pooling inside the optical measurement gap.
2. **Snap Buckle & Waterproof Gasket**:
   - Install using the integrated snap buckle and black rubber sealing gasket (Part 1 in datasheet Figure 6).
   - Ensure the gasket is compressed evenly to maintain IP67 water tightness under hydraulic line pressure.
3. **Cleaning & Maintenance**:
   - Clean the transparent optical window regularly using soft cotton gauze or a lint-free sponge with deionized water.
   - Never use abrasive brushes, metal scrapers, or harsh solvents that could scratch the light-transmitting acrylic housing.

---

## 5. Adafruit AS7341 10-Channel Multi-Spectral Sensor Optical Setup

The **Adafruit AS7341** spectrophotometer-on-a-chip monitors optical absorption and reflection across 10 discrete wavelength bands (415 nm to 680 nm, Clear, NIR).

```
                     Active White LED Illumination
                     (AS7341 Integrated White LED)
                                  │
                  ┌───────────────▼──────────────┐
                  │ ════════════════════════════ │
   Water Inflow ─>│ [Clear Borosilicate Tube]    │─> Water Outflow
                  │ ════════════════════════════ │
                  └───────────────▲──────────────┘
                                  │
                         Collimated Light Path
                                  │
                  ┌───────────────▼──────────────┐
                  │   Adafruit AS7341 Optical    │
                  │   10-Channel Spectrometer    │ (Connected via I2C at 0x39)
                  └──────────────────────────────┘
```

### Physical Mounting & Alignment:
1. **Borosilicate Glass Interface**:
   - The AS7341 optical window must be mounted **flush against the flat external surface** of the clear borosilicate flow cell.
   - Use an optical silicone coupling gasket or light-baffling 3D-printed shroud (opaque black PLA or PETG) around the sensor to eliminate ambient room light bleed into the photodiodes.
2. **Active Transmission Illumination**:
   - The AS7341 integrates a calibrated high-CRI white LED. The MCU firmware pulses this LED during the 1-minute sampling cycle (`SET_SPECTRAL_LED:1`) to pass light through the fluid column for direct transmission spectrophotometry.
3. **Biological & Chemical Indices**:
   - **Normalized Difference Algal Index (NDAI)**:
     $$\text{NDAI} = \frac{F_5 (555\text{ nm}) - F_8 (680\text{ nm})}{F_5 (555\text{ nm}) + F_8 (680\text{ nm})}$$
     Detects chlorophyll-a absorption ($680\text{ nm}$) and green algae reflectance ($555\text{ nm}$) to flag algal blooms ($\text{NDAI} > +0.35$).
   - **Colored Dissolved Organic Matter (CDOM) Sewage Index**:
     $$\text{CDOM} = \frac{F_6 (590\text{ nm}) - F_1 (415\text{ nm})}{F_6 (590\text{ nm}) + F_1 (415\text{ nm})}$$
     Detects high violet absorption ($415\text{ nm}$) from dissolved humic/fulvic acids and sewage effluents ($\text{CDOM} > +0.40$).


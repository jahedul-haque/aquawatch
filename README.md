# AquaWatch

AquaWatch is an autonomous, edge-AI-based water contamination early-warning system designed for continuous monitoring of drinking-water sources.

The system uses the **Arduino Uno Q's heterogeneous architecture** to combine three complementary sensing pillars:

- **Physical Sensing** – turbidity and temperature measurements, with provision for future pH, ORP, and TDS/conductivity sensors.
- **Spectral Analysis** – an AS7341 multi-spectral sensor captures the optical signature of the water across multiple wavelength channels.
- **Computer Vision** – a USB camera analyses water appearance, colour, suspended particles, and optical clarity using edge-based image processing.

The **STM32U585** handles low-power, deterministic sensor acquisition, while the **Qualcomm QRB2210 running Debian Linux** performs image processing, spectral analysis, multimodal fusion, and AI inference.

AquaWatch is designed to overcome the limitations of relying on a single physical sensor. Biofouling, sediment deposition, and mineral buildup can cause sensor drift and false readings. By cross-validating physical measurements with independent spectral and visual observations, AquaWatch can distinguish potential contamination events from sensor anomalies.

The system can generate local contamination alerts and transmit water-quality telemetry over **LoRaWAN**, enabling long-range operation without requiring continuous cellular connectivity. Sensor measurements and selected images can also be stored locally for audit and analysis.

Measure. Inspect. Cross-validate. Alert.**

AquaWatch is intended as an **early-warning system** and does not replace laboratory testing required for definitive confirmation of water contamination.
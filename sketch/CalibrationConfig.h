#ifndef CALIBRATION_CONFIG_H
#define CALIBRATION_CONFIG_H

#include <Arduino.h>

struct SensorCalibration {
    // ADC reference voltage on STM32U585
    float adcVref;                // Typically 3.3V
    int adcResolutionBits;        // 12-bit or 14-bit (4095 or 16383)

    // pH Calibration (2-point standard buffer at 25°C)
    float ph_v7;                  // Voltage at pH 7.00 (neutral midpoint)
    float ph_v4;                  // Voltage at pH 4.01 (acidic buffer)
    float ph_slope;               // Calculated Volts per pH unit (nominal -0.05916 V/pH)

    // ASAIR AZDM01 Photoelectric Turbidity Sensor Parameters (940nm IR)
    float azdm01_u0_volts;        // Baseline output voltage in clear water (<1 NTU) on 5V scale (nominal 3.80V)
    float azdm01_divider_ratio;   // Hardware voltage divider ratio: R2 / (R1 + R2), e.g. 20k / (10k + 20k) = 0.6667

    // TDS Calibration (Total Dissolved Solids)
    float tds_k_factor;           // Conversion factor (default ~0.50)
    float tds_temp_coeff;         // Temperature coefficient (typically 0.02 / °C)

    // ORP (Oxidation-Reduction Potential) Calibration
    float orp_offset_mv;          // Offset in millivolts
    float orp_gain;               // Gain amplifier factor
};

// Factory default parameters calibrated for 3.3V STM32 ADC
inline SensorCalibration getDefaultCalibration() {
    SensorCalibration cal;
    cal.adcVref = 3.30f;
    cal.adcResolutionBits = 12;   // 12-bit default for STM32 analogRead (4096 levels)
    
    // pH defaults (assuming 3.3V level-shifted sensor or 3.3V Gravity pH)
    cal.ph_v7 = 1.65f;            // Midpoint of 3.3V rail
    cal.ph_v4 = 2.03f;            // Voltage at pH 4.01
    cal.ph_slope = (cal.ph_v4 - cal.ph_v7) / (4.01f - 7.00f); // ~ -0.127V/pH or tailored
    
    // ASAIR AZDM01 Turbidity defaults (10k/30k divider on 3.3V, measured 3.19V in clear water)
    cal.azdm01_u0_volts = 3.19f;          // Measured clear water output voltage U0
    cal.azdm01_divider_ratio = 30.0f / (10.0f + 30.0f); // 10k/30k voltage divider => 0.7500 (3.19V -> 2.393V on STM32)

    // TDS defaults
    cal.tds_k_factor = 0.50f;
    cal.tds_temp_coeff = 0.02f;

    // ORP defaults (ORP probe amplifier maps ±2000mV to 0-3.3V with 1.65V zero)
    cal.orp_offset_mv = 0.0f;
    cal.orp_gain = 1.0f;

    return cal;
}

// Convert ADC raw count to Millivolts
inline float adcToMillivolts(int rawAdc, const SensorCalibration& cal) {
    float maxAdc = (float)((1 << cal.adcResolutionBits) - 1);
    return ((float)rawAdc / maxAdc) * (cal.adcVref * 1000.0f);
}

// Temperature-compensated pH calculation using Nernst equation
inline float calculatePH(float voltageVolts, float waterTempC, const SensorCalibration& cal) {
    if (waterTempC < -10.0f || waterTempC > 100.0f) {
        waterTempC = 25.0f; // Fallback to standard room temperature
    }
    // Nernst slope scaling: S(T) = S(25) * (T + 273.15) / 298.15
    float tempKelvin = waterTempC + 273.15f;
    float nernstRatio = tempKelvin / 298.15f;
    float compensatedSlope = cal.ph_slope * nernstRatio;
    
    if (fabs(compensatedSlope) < 0.001f) {
        compensatedSlope = -0.05916f;
    }

    float ph = 7.00f + ((voltageVolts - cal.ph_v7) / compensatedSlope);
    
    // Clamp to physically valid aqueous pH range
    if (ph < 0.0f) ph = 0.0f;
    if (ph > 14.0f) ph = 14.0f;
    return ph;
}

// ASAIR AZDM01 Photoelectric Turbidity Sensor calculation (NTU)
// Based on ASAIR AZDM01 Product Specification V1.1 (Table 4 & Formula f = Um / U0)
inline float calculateTurbidityAZDM01(float adcVoltageVolts, const SensorCalibration& cal) {
    // 1. Recover the true 5V-domain sensor output voltage Um from the ADC reading
    float divider = (cal.azdm01_divider_ratio > 0.05f) ? cal.azdm01_divider_ratio : 1.0f;
    float Um = adcVoltageVolts / divider;

    // 2. Calculate turbidity coefficient ratio: f = Um / U0
    float u0 = (cal.azdm01_u0_volts > 0.5f) ? cal.azdm01_u0_volts : 3.80f;
    float f = Um / u0;

    // 3. Piecewise linear interpolation based on Table 4 (Measuring Turbidity Meter):
    //    f >= 1.000 (100.0%) -> 0 NTU (Clear water, <1 NTU)
    //    f = 0.643  (64.3%)  -> 500 NTU
    //    f = 0.435  (43.5%)  -> 1000 NTU
    //    f = 0.236  (23.6%)  -> 2000 NTU
    //    f = 0.079  (7.9%)   -> 4000 NTU
    //    f < 0.079           -> > 4000 NTU (extrapolated/clamped up to 4500 NTU)
    float ntu = 0.0f;

    if (f >= 1.0f) {
        ntu = 0.0f;
    } else if (f >= 0.643f) {
        ntu = (1.0f - f) / (1.0f - 0.643f) * 500.0f;
    } else if (f >= 0.435f) {
        ntu = 500.0f + ((0.643f - f) / (0.643f - 0.435f)) * 500.0f;
    } else if (f >= 0.236f) {
        ntu = 1000.0f + ((0.435f - f) / (0.435f - 0.236f)) * 1000.0f;
    } else if (f >= 0.079f) {
        ntu = 2000.0f + ((0.236f - f) / (0.236f - 0.079f)) * 2000.0f;
    } else {
        float extra = (0.079f - f) / 0.074f * 500.0f;
        ntu = 4000.0f + extra;
        if (ntu > 4500.0f) ntu = 4500.0f;
    }

    if (ntu < 0.0f) ntu = 0.0f;
    return ntu;
}

// Wrapper for backward compatibility
inline float calculateTurbidityNTU(float voltageVolts, const SensorCalibration& cal) {
    return calculateTurbidityAZDM01(voltageVolts, cal);
}

// Temperature-compensated Total Dissolved Solids (ppm / mg/L)
inline float calculateTDS(float voltageVolts, float waterTempC, const SensorCalibration& cal) {
    if (waterTempC < 0.0f || waterTempC > 80.0f) {
        waterTempC = 25.0f;
    }
    // Temperature compensation factor
    float compensationCoefficient = 1.0f + cal.tds_temp_coeff * (waterTempC - 25.0f);
    if (compensationCoefficient <= 0.1f) compensationCoefficient = 0.1f;
    
    float compensationVoltage = voltageVolts / compensationCoefficient;
    
    // Convert voltage to EC (Electrical Conductivity in µS/cm) then to TDS (ppm)
    // Standard polynomial formula for analog TDS probe
    float tds = (133.42f * pow(compensationVoltage, 3) 
                 - 255.86f * pow(compensationVoltage, 2) 
                 + 857.39f * compensationVoltage) * cal.tds_k_factor;
                 
    if (tds < 0.0f) tds = 0.0f;
    return tds;
}

// Oxidation-Reduction Potential (ORP in mV)
inline float calculateORP(float voltageVolts, const SensorCalibration& cal) {
    // Standard ORP probe boards (e.g., Gravity ORP) output:
    // V_out = (ORP_mV * gain) + V_ref_midpoint
    // For 3.3V rail: V_ref_midpoint is ~1.65V (or 2.5V on 5V modules)
    float midpointVolts = cal.adcVref / 2.0f;
    float deltaV = voltageVolts - midpointVolts;
    float orp_mv = ((deltaV * 1000.0f) / cal.orp_gain) + cal.orp_offset_mv;
    return orp_mv;
}

// ----------------------------------------------------------------------------
// Adafruit AS7341 10-Channel Multi-Spectral Water Analysis
// ----------------------------------------------------------------------------
struct AS7341SpectralReadings {
    uint16_t f1_415;  // Violet (415 nm) - CDOM absorption band
    uint16_t f2_445;  // Indigo (445 nm) - Chlorophyll-a Soret peak
    uint16_t f3_480;  // Blue (480 nm)
    uint16_t f4_515;  // Cyan (515 nm)
    uint16_t f5_555;  // Green (555 nm) - Algal reflectance peak
    uint16_t f6_590;  // Yellow (590 nm) - Organic matter reference
    uint16_t f7_630;  // Orange (630 nm) - Phycocyanin / rust tint
    uint16_t f8_680;  // Red (680 nm) - Chlorophyll-a Q-band absorption peak
    uint16_t clear;   // Broad visible photopic transmission
    uint16_t nir;     // Near-Infrared (910 nm) - Turbidity backscatter
    
    float algae_ndai;    // Raw Normalized Difference Algae Index: (F5 - F8) / (F5 + F8)
    float cdom_index;    // Raw Colored Dissolved Organic Matter: (F6 - F1) / (F6 + F1)
    float delta_ndai;    // Baseline-compensated NDAI: algae_ndai - baseline_ndai
    float delta_cdom;    // Baseline-compensated CDOM: cdom_index - baseline_cdom
    float baseline_ndai; // Clear water reference NDAI (default 0.48f for white LED)
    float baseline_cdom; // Clear water reference CDOM (default 0.64f)
    bool sensor_present;
};

// Computes water quality spectral indices with baseline compensation and division-by-zero protection
inline void computeSpectralIndices(AS7341SpectralReadings& s, float baseNdai = 0.48f, float baseCdom = 0.64f) {
    s.baseline_ndai = baseNdai;
    s.baseline_cdom = baseCdom;

    // Algae Index (NDAI): green reflection (555nm) vs red absorption (680nm)
    float denom_algae = (float)s.f5_555 + (float)s.f8_680;
    if (denom_algae > 10.0f) {
        s.algae_ndai = ((float)s.f5_555 - (float)s.f8_680) / denom_algae;
        s.delta_ndai = s.algae_ndai - s.baseline_ndai;
    } else {
        s.algae_ndai = 0.0f;
        s.delta_ndai = 0.0f;
    }

    // CDOM / Tannin / Sewage Index: yellow reference (590nm) vs violet absorption (415nm)
    float denom_cdom = (float)s.f6_590 + (float)s.f1_415;
    if (denom_cdom > 10.0f) {
        s.cdom_index = ((float)s.f6_590 - (float)s.f1_415) / denom_cdom;
        s.delta_cdom = s.cdom_index - s.baseline_cdom;
    } else {
        s.cdom_index = 0.0f;
        s.delta_cdom = 0.0f;
    }
}

#endif // CALIBRATION_CONFIG_H



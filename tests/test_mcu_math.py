"""
Unit Tests for STM32 Firmware Mathematical Algorithms & Temperature Compensation
"""

import math
import unittest

def calculate_ph(voltage: float, temp_c: float, v7: float = 1.65, slope_25: float = -0.05916) -> float:
    nernst_ratio = (temp_c + 273.15) / 298.15
    compensated_slope = slope_25 * nernst_ratio
    ph = 7.00 + ((voltage - v7) / compensated_slope)
    return max(0.0, min(14.0, ph))

def calculate_tds(voltage: float, temp_c: float, k_factor: float = 0.50, temp_coeff: float = 0.02) -> float:
    comp_coeff = 1.0 + temp_coeff * (temp_c - 25.0)
    if comp_coeff <= 0.1: comp_coeff = 0.1
    comp_v = voltage / comp_coeff
    tds = (133.42 * (comp_v ** 3) - 255.86 * (comp_v ** 2) + 857.39 * comp_v) * k_factor
    return max(0.0, tds)

def calculate_orp(voltage: float, vref: float = 3.3, gain: float = 1.0, offset_mv: float = 0.0) -> float:
    midpoint = vref / 2.0
    delta_v = voltage - midpoint
    return ((delta_v * 1000.0) / gain) + offset_mv

def calculate_turbidity_azdm01(adc_voltage: float, u0_volts: float = 3.80, divider_ratio: float = (20.0 / 30.0)) -> float:
    Um = adc_voltage / divider_ratio
    f = Um / u0_volts

    if f >= 1.0:
        return 0.0
    elif f >= 0.643:
        return (1.0 - f) / (1.0 - 0.643) * 500.0
    elif f >= 0.435:
        return 500.0 + ((0.643 - f) / (0.643 - 0.435)) * 500.0
    elif f >= 0.236:
        return 1000.0 + ((0.435 - f) / (0.435 - 0.236)) * 1000.0
    elif f >= 0.079:
        return 2000.0 + ((0.236 - f) / (0.236 - 0.079)) * 2000.0
    else:
        extra = (0.079 - f) / 0.074 * 500.0
        return min(4500.0, 4000.0 + extra)

class TestMCUMath(unittest.TestCase):
    def test_ph_neutral_at_25c(self):
        # At 1.65V (neutral midpoint), pH must equal 7.00 regardless of temperature
        self.assertAlmostEqual(calculate_ph(1.65, 25.0), 7.00, places=2)
        self.assertAlmostEqual(calculate_ph(1.65, 10.0), 7.00, places=2)
        self.assertAlmostEqual(calculate_ph(1.65, 40.0), 7.00, places=2)

    def test_ph_temperature_slope_correction(self):
        # In acidic solution (e.g. 1.768V), pH changes with temperature due to Nernst equation
        ph_25 = calculate_ph(1.768, 25.0)
        ph_10 = calculate_ph(1.768, 10.0)
        # Nernst slope magnitude is smaller at 10°C, so delta is divided by smaller number => further from 7
        self.assertLess(ph_10, ph_25)

    def test_tds_temperature_compensation(self):
        # A solution tested at 35°C has higher ion mobility; compensation should adjust down to 25°C equivalent
        v_raw = 1.2
        tds_25 = calculate_tds(v_raw, 25.0)
        tds_35 = calculate_tds(v_raw, 35.0)
        self.assertLess(tds_35, tds_25)

    def test_orp_zero_midpoint(self):
        # At 1.65V (half of 3.3V), ORP should be exactly 0 mV
        self.assertAlmostEqual(calculate_orp(1.65, vref=3.3), 0.0, places=1)
        # At 2.30V (+0.65V above midpoint), ORP should be +650 mV
        self.assertAlmostEqual(calculate_orp(2.30, vref=3.3), 650.0, places=1)

    def test_azdm01_turbidity_calibration_points(self):
        # Datasheet Table 4 verification with 10k/20k voltage divider (2/3 ratio)
        divider = 20.0 / 30.0
        u0 = 3.80

        # Point 1: Clean Water (f = 1.0, Um = 3.8V, ADC = 2.533V) => 0.0 NTU (<1 NTU)
        v_adc_clean = 3.80 * divider
        self.assertAlmostEqual(calculate_turbidity_azdm01(v_adc_clean, u0, divider), 0.0, places=1)

        # Point 2: 500 NTU (f = 0.643, Um = 2.4434V)
        v_adc_500 = (3.80 * 0.643) * divider
        self.assertAlmostEqual(calculate_turbidity_azdm01(v_adc_500, u0, divider), 500.0, places=1)

        # Point 3: 1000 NTU (f = 0.435, Um = 1.653V)
        v_adc_1000 = (3.80 * 0.435) * divider
        self.assertAlmostEqual(calculate_turbidity_azdm01(v_adc_1000, u0, divider), 1000.0, places=1)

        # Point 4: 2000 NTU (f = 0.236, Um = 0.8968V)
        v_adc_2000 = (3.80 * 0.236) * divider
        self.assertAlmostEqual(calculate_turbidity_azdm01(v_adc_2000, u0, divider), 2000.0, places=1)

        # Point 5: 4000 NTU (f = 0.079, Um = 0.3002V)
        v_adc_4000 = (3.80 * 0.079) * divider
        self.assertAlmostEqual(calculate_turbidity_azdm01(v_adc_4000, u0, divider), 4000.0, places=1)

    def test_azdm01_turbidity_monotonicity(self):
        # Verify that as ADC voltage decreases, calculated NTU monotonically increases
        voltages = [2.533, 2.0, 1.5, 1.0, 0.5, 0.2]
        ntu_readings = [calculate_turbidity_azdm01(v) for v in voltages]
        for i in range(len(ntu_readings) - 1):
            self.assertLess(ntu_readings[i], ntu_readings[i + 1])

if __name__ == "__main__":
    unittest.main()

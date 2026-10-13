"""
Unit tests for Adafruit AS7341 10-Channel Multi-Spectral Water Analysis in AquaWatch.
Tests optical index formulas (NDAI, CDOM), anomaly detection, contamination diagnostics,
bridge client simulation, and LoRaWAN binary encoding.
"""

import sys
import os
import unittest
import struct

# Add mpu_vision_service to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mpu_vision_service")))

from sensor_anomaly_model import SensorAnomalyModel
from contamination_engine import ContaminationEngine, HAZARD_CODES
from lorawan_service import LoRaWANService
from bridge_client import STM32BridgeClient


class TestSpectralSensor(unittest.TestCase):
    def setUp(self):
        self.anomaly_model = SensorAnomalyModel()
        self.engine = ContaminationEngine()
        self.lorawan = LoRaWANService()

    def test_spectral_indices_calculation(self):
        """Validates that NDAI (Algae) and CDOM (Organics) mathematical calculations behave correctly."""
        # Clean water baseline
        f5_clean = 1750
        f8_clean = 1850
        ndai_clean = (f5_clean - f8_clean) / (f5_clean + f8_clean)
        self.assertAlmostEqual(ndai_clean, -0.0277, places=3)

        # Algal bloom: High green (555nm) reflectance, strong red (680nm) chlorophyll-a absorption
        f5_bloom = 3800
        f8_bloom = 720
        ndai_bloom = (f5_bloom - f8_bloom) / (f5_bloom + f8_bloom)
        self.assertGreater(ndai_bloom, 0.50)

        # Colored Dissolved Organic Matter (CDOM): High violet (415nm) absorption, yellow (590nm) transmission
        f1_sewage = 260
        f6_sewage = 1680
        cdom_sewage = (f6_sewage - f1_sewage) / (f6_sewage + f1_sewage)
        self.assertGreater(cdom_sewage, 0.60)

    def test_sensor_ai_clean_with_spectral(self):
        """Verifies that clean water with AS7341 baseline readings yields safe z-scores and low anomaly score."""
        mcu_data = {
            "temp_c": 18.0,
            "ph": 7.35,
            "turbidity_ntu": 0.40,
            "tds_ppm": 180.0,
            "orp_mv": 680.0,
            "spectral": {
                "f1": 1250, "f2": 1420, "f3": 1580, "f4": 1620,
                "f5": 1750, "f6": 1800, "f7": 1820, "f8": 1850,
                "clear": 8500, "nir": 920,
                "algae_ndai": 0.02,
                "cdom_index": 0.04,
                "detected": True
            }
        }
        vision_data = {"clarity_percent": 95.0, "particulate_count": 2, "discoloration_delta_e": 0.5}
        vision_ai = {"optical_anomaly_score": 0.08, "top_classification": "Clean_Potable"}

        res = self.anomaly_model.predict(mcu_data, vision_data, vision_ai)
        self.assertLess(res["ai_anomaly_score"], 0.20)
        self.assertEqual(res["predicted_threat"], "CLEAN_POTABLE_WATER")
        self.assertFalse(res["critical_alert_active"])

    def test_sensor_ai_algal_bloom_threat(self):
        """Verifies that high NDAI from AS7341 triggers ALGAL_BLOOM_EUTROPHICATION threat."""
        mcu_data = {
            "temp_c": 25.0,
            "ph": 8.40,
            "turbidity_ntu": 3.80,
            "tds_ppm": 240.0,
            "orp_mv": 520.0,
            "spectral": {
                "f1": 850, "f2": 620, "f3": 1100, "f4": 1550,
                "f5": 3800, "f6": 1950, "f7": 1400, "f8": 720,
                "clear": 5200, "nir": 1650,
                "algae_ndai": 0.68,
                "cdom_index": 0.39,
                "detected": True
            }
        }
        vision_data = {"clarity_percent": 75.0, "particulate_count": 8, "discoloration_delta_e": 4.5}
        vision_ai = {"optical_anomaly_score": 0.45, "top_classification": "Suspended_Sediment"}

        res = self.anomaly_model.predict(mcu_data, vision_data, vision_ai)
        self.assertEqual(res["predicted_threat"], "ALGAL_BLOOM_EUTROPHICATION")

    def test_contamination_engine_algal_bloom_hazard(self):
        """Verifies ContaminationEngine diagnoses HAZARD_ALGAL_BLOOM (code 0x0A) when NDAI exceeds threshold."""
        mcu_data = {
            "temp_c": 24.0,
            "ph": 8.20,
            "turbidity_ntu": 2.50,
            "tds_ppm": 220.0,
            "orp_mv": 620.0,
            "spectral": {
                "f1": 900, "f2": 700, "f3": 1200, "f4": 1500,
                "f5": 3600, "f6": 1800, "f7": 1400, "f8": 800,
                "clear": 6000, "nir": 1300,
                "algae_ndai": 0.63,
                "cdom_index": 0.33,
                "detected": True
            }
        }
        vision_data = {
            "clarity_percent": 82.0, "particulate_count": 5,
            "discoloration_delta_e": 3.0, "tint_classification": "Clear",
            "surface_sheen_detected": False
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        hazard_codes = [h["code"] for h in assessment["active_hazards"]]
        self.assertIn("HAZARD_ALGAL_BLOOM", hazard_codes)
        self.assertEqual(assessment["hazard_code"], HAZARD_CODES["ALGAL_BLOOM"])
        self.assertTrue(assessment["lorawan_alert_required"])

    def test_contamination_engine_chemical_dye_hazard(self):
        """Verifies ContaminationEngine diagnoses HAZARD_CHEMICAL_DYE (code 0x0B) on chromatic skew."""
        mcu_data = {
            "temp_c": 21.5,
            "ph": 6.90,
            "turbidity_ntu": 1.20,
            "tds_ppm": 350.0,
            "orp_mv": 640.0,
            "spectral": {
                "f1": 1400, "f2": 1500, "f3": 1600, "f4": 920,
                "f5": 580, "f6": 1100, "f7": 2950, "f8": 3250,
                "clear": 4200, "nir": 1150,
                "algae_ndai": -0.69,
                "cdom_index": -0.12,
                "detected": True
            }
        }
        vision_data = {
            "clarity_percent": 80.0, "particulate_count": 4,
            "discoloration_delta_e": 8.0, "tint_classification": "Reddish",
            "surface_sheen_detected": False
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        hazard_codes = [h["code"] for h in assessment["active_hazards"]]
        self.assertIn("HAZARD_CHEMICAL_DYE", hazard_codes)
        self.assertEqual(assessment["hazard_code"], HAZARD_CODES["CHEMICAL_DYE"])
        self.assertTrue(assessment["lorawan_alert_required"])

    def test_lorawan_spectral_dedicated_payload(self):
        """Verifies that build_spectral_payload generates a valid 12-byte binary uplink on Port 12."""
        assessment = {
            "wqi": 78.0,
            "hazard_code": HAZARD_CODES["ALGAL_BLOOM"],
            "lorawan_alert_required": True,
            "spectral_readings": {
                "f1": 900, "f2": 700, "f3": 1200, "f4": 1500,
                "f5": 3600, "f6": 1800, "f7": 1400, "f8": 800,
                "clear": 6000, "nir": 1200,
                "algae_ndai": 0.63,
                "cdom_index": 0.33
            }
        }

        payload = self.lorawan.build_spectral_payload(assessment)
        self.assertEqual(len(payload), 12)
        
        # Unpack payload
        header, ndai_val, cdom_val = struct.unpack(">Bbb", payload[:3])
        self.assertEqual(header & 0x80, 0x80)  # Alert bit set
        self.assertEqual(header & 0x0F, HAZARD_CODES["ALGAL_BLOOM"])
        self.assertEqual(ndai_val, 63)         # 0.63 * 100
        self.assertEqual(cdom_val, 33)         # 0.33 * 100

    def test_bridge_client_spectral_simulation(self):
        """Verifies that BridgeClient generates realistic 10-channel spectral data in simulation mode."""
        client = STM32BridgeClient(mode="mock")
        
        # Normal water test
        client.set_simulation_scenario("normal")
        spec_normal = client.get_spectral_data()
        self.assertIn("f1", spec_normal)
        self.assertIn("algae_ndai", spec_normal)
        self.assertIn("cdom_index", spec_normal)
        self.assertAlmostEqual(spec_normal["algae_ndai"], 0.0, delta=0.15)

        # Algal bloom scenario test
        client.set_simulation_scenario("algal_bloom")
        spec_algae = client.get_spectral_data()
        self.assertGreater(spec_algae["algae_ndai"], 0.40)
        self.assertGreater(spec_algae["f5"], spec_algae["f8"])


if __name__ == "__main__":
    unittest.main()

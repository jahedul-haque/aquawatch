"""
Unit Tests for Contamination Engine & WQI Scoring (LoRaWAN Alerting)
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mpu_vision_service"))

from contamination_engine import ContaminationEngine

class TestContaminationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ContaminationEngine()

    def test_normal_drinking_water(self):
        mcu_data = {
            "temp_c": 18.5,
            "ph": 7.35,
            "turbidity_ntu": 0.30,
            "tds_ppm": 140.0,
            "orp_mv": 680.0
        }
        vision_data = {
            "clarity_percent": 96.0,
            "discoloration_delta_e": 2.1,
            "tint_classification": "Clear",
            "particulate_count": 1,
            "surface_sheen_detected": False
        }

        result = self.engine.evaluate(mcu_data, vision_data)
        
        self.assertEqual(result["safety_level"], "SAFE")
        self.assertGreaterEqual(result["wqi"], 85.0)
        self.assertFalse(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x00)
        self.assertEqual(len(result["active_hazards"]), 0)

    def test_acid_spill_detection(self):
        mcu_data = {
            "temp_c": 21.0,
            "ph": 4.50, # Critical acidic contamination
            "turbidity_ntu": 1.2,
            "tds_ppm": 550.0,
            "orp_mv": 710.0
        }
        vision_data = {
            "clarity_percent": 90.0,
            "discoloration_delta_e": 4.0,
            "tint_classification": "Clear",
            "particulate_count": 4,
            "surface_sheen_detected": False
        }

        result = self.engine.evaluate(mcu_data, vision_data)
        
        self.assertEqual(result["safety_level"], "CRITICAL")
        self.assertTrue(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x02) # ACID_CONTAMINATION
        hazard_codes = [h["code"] for h in result["active_hazards"]]
        self.assertIn("HAZARD_ACID_CONTAMINATION", hazard_codes)

    def test_sewage_ingress_detection(self):
        mcu_data = {
            "temp_c": 24.0,
            "ph": 6.30,
            "turbidity_ntu": 7.8,
            "tds_ppm": 900.0,
            "orp_mv": 160.0 # Strongly reducing / anaerobic bacteria
        }
        vision_data = {
            "clarity_percent": 35.0,
            "discoloration_delta_e": 18.5,
            "tint_classification": "Sewage / Black Sludge",
            "particulate_count": 32,
            "surface_sheen_detected": False
        }

        result = self.engine.evaluate(mcu_data, vision_data)
        
        self.assertEqual(result["safety_level"], "CRITICAL")
        self.assertTrue(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x04) # SEWAGE_INGRESS
        hazard_codes = [h["code"] for h in result["active_hazards"]]
        self.assertIn("HAZARD_SEWAGE_INGRESS", hazard_codes)

    def test_disinfection_loss(self):
        mcu_data = {
            "temp_c": 20.0,
            "ph": 7.40,
            "turbidity_ntu": 0.40,
            "tds_ppm": 160.0,
            "orp_mv": 480.0 # Sub-threshold ORP (< 650mV)
        }
        vision_data = {
            "clarity_percent": 95.0,
            "discoloration_delta_e": 1.0,
            "tint_classification": "Clear",
            "particulate_count": 1,
            "surface_sheen_detected": False
        }

        result = self.engine.evaluate(mcu_data, vision_data)
        
        self.assertEqual(result["safety_level"], "WARNING")
        self.assertTrue(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x01) # DISINFECTION_LOSS
        hazard_codes = [h["code"] for h in result["active_hazards"]]
        self.assertIn("HAZARD_DISINFECTION_LOSS", hazard_codes)

    def test_hydrocarbon_sheen(self):
        mcu_data = {
            "temp_c": 19.0,
            "ph": 7.20,
            "turbidity_ntu": 1.1,
            "tds_ppm": 210.0,
            "orp_mv": 660.0
        }
        vision_data = {
            "clarity_percent": 88.0,
            "discoloration_delta_e": 5.0,
            "tint_classification": "Clear",
            "particulate_count": 5,
            "surface_sheen_detected": True # Oil slick on surface
        }

        result = self.engine.evaluate(mcu_data, vision_data)
        
        self.assertEqual(result["safety_level"], "CRITICAL")
        self.assertTrue(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x06) # HYDROCARBON_SHEEN
        hazard_codes = [h["code"] for h in result["active_hazards"]]
        self.assertIn("HAZARD_HYDROCARBON_SHEEN", hazard_codes)

    def test_missing_orp_dummy_fallback(self):
        """Verify that when ORP sensor is absent and dummy value (675mV) is supplied, evaluation is safe and robust."""
        mcu_data = {
            "temp_c": 20.5,
            "ph": 7.30,
            "turbidity_ntu": 0.40,
            "tds_ppm": 165.0,
            "orp_mv": 675.0,
            "orp_dummy": True
        }
        vision_data = {
            "clarity_percent": 96.0,
            "discoloration_delta_e": 1.5,
            "tint_classification": "Clear",
            "particulate_count": 2,
            "surface_sheen_detected": False
        }

        result = self.engine.evaluate(mcu_data, vision_data)
        
        self.assertEqual(result["safety_level"], "SAFE")
        self.assertGreaterEqual(result["wqi"], 85.0)
        self.assertFalse(result["lorawan_alert_required"])
        self.assertTrue(result["sensor_readings"].get("orp_dummy"))
        self.assertFalse(result["ai_diagnostics"]["sensor_drift_fault"])

    def test_static_ph_tds_and_orp_all_dummy(self):
        """
        Verify that when expensive pH, TDS, and ORP probes are omitted and safe static baselines
        (pH=7.35, TDS=180ppm, ORP=675mV) are injected, the node evaluates safe drinking water,
        produces zero false alarms, and flags static status on all dummy metrics.
        """
        mcu_data = {
            "temp_c": 21.0,
            "ph": 7.35,
            "ph_dummy": True,
            "turbidity_ntu": 0.45,
            "tds_ppm": 180.0,
            "tds_dummy": True,
            "orp_mv": 675.0,
            "orp_dummy": True
        }
        vision_data = {
            "clarity_percent": 95.0,
            "discoloration_delta_e": 1.8,
            "tint_classification": "Clear",
            "particulate_count": 2,
            "surface_sheen_detected": False
        }

        result = self.engine.evaluate(mcu_data, vision_data)

        self.assertEqual(result["safety_level"], "SAFE")
        self.assertGreaterEqual(result["wqi"], 88.0)
        self.assertFalse(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x00)
        self.assertTrue(result["sensor_readings"].get("ph_dummy"))
        self.assertTrue(result["sensor_readings"].get("tds_dummy"))
        self.assertTrue(result["sensor_readings"].get("orp_dummy"))
        self.assertFalse(result["ai_diagnostics"]["sensor_drift_fault"])

    def test_bridge_client_static_sensor_overrides(self):
        """Verify that STM32BridgeClient properly applies static sensor values and toggles flags."""
        from bridge_client import STM32BridgeClient
        client = STM32BridgeClient(mode="mock")
        client.set_static_options(
            use_ph=True, ph_val=7.40,
            use_tds=True, tds_val=195.0,
            use_orp=True, orp_val=680.0
        )
        opts = client.get_static_options()
        self.assertTrue(opts["ph"]["use_static"])
        self.assertEqual(opts["ph"]["value"], 7.40)
        self.assertTrue(opts["tds"]["use_static"])
        self.assertEqual(opts["tds"]["value"], 195.0)

        telemetry = client.get_telemetry()
        self.assertAlmostEqual(telemetry["ph"], 7.40, places=1)
        self.assertTrue(telemetry["ph_dummy"])
        self.assertAlmostEqual(telemetry["tds_ppm"], 195.0, places=0)
        self.assertTrue(telemetry["tds_dummy"])
        self.assertAlmostEqual(telemetry["orp_mv"], 680.0, places=0)
        self.assertTrue(telemetry["orp_dummy"])

    def test_disconnected_temperature_and_spectral_probes(self):
        """Verify that when temperature (-127°C) and AS7341 (detected=False) are disconnected,
        WQI is not artificially penalized, classifications mark them offline, and no false alarms trigger."""
        mcu_data = {
            "temp_c": -127.0,
            "temp_dummy": True,
            "temp_connected": False,
            "ph": 7.35,
            "ph_dummy": True,
            "turbidity_ntu": 0.20,
            "tds_ppm": 180.0,
            "tds_dummy": True,
            "orp_mv": 675.0,
            "orp_dummy": True,
            "spectral": {
                "f1": 0, "f2": 0, "f3": 0, "f4": 0,
                "f5": 0, "f6": 0, "f7": 0, "f8": 0,
                "clear": 0, "nir": 0,
                "algae_ndai": 0.0,
                "cdom_index": 0.0,
                "detected": False
            }
        }
        vision_data = {
            "clarity_percent": 98.0,
            "discoloration_delta_e": 0.5,
            "tint_classification": "Clear",
            "particulate_count": 0,
            "surface_sheen_detected": False,
            "camera_detected": True
        }

        result = self.engine.evaluate(mcu_data, vision_data)

        self.assertEqual(result["safety_level"], "SAFE")
        self.assertGreaterEqual(result["wqi"], 95.0)
        self.assertFalse(result["lorawan_alert_required"])
        self.assertEqual(result["hazard_code"], 0x00)

        # Check 3-pillar classifications
        c = result["classifications"]
        self.assertEqual(c["as7341"]["status"], "OFFLINE")
        self.assertEqual(c["as7341"]["title"], "Not Connected")
        self.assertIn("not connected", c["sensors"]["summary"])
        self.assertFalse(c["sensors"]["temp_connected"])

    def test_clean_water_unpatterned_container_ambient_temperature(self):
        """Tests that clean water at 31.1C ambient temp in an unpatterned container without a printed grid evaluates Safe with WQI >= 95%."""
        mcu_data = {
            "temp_c": 31.1,
            "ph": 7.35,
            "turbidity_ntu": 0.0,
            "tds_ppm": 180.0,
            "orp_mv": 680.0,
            "spectral": {
                "algae_ndai": -0.001,
                "cdom_index": 0.0
            }
        }
        # Low camera Laplacian clarity because water is smooth without a printed optical grid
        vision_data = {
            "clarity_percent": 2.5,
            "discoloration_delta_e": 0.8,
            "tint_classification": "Clear",
            "particulate_count": 0,
            "surface_sheen_detected": False,
            "camera_detected": True
        }

        result = self.engine.evaluate(mcu_data, vision_data)

        self.assertEqual(result["safety_level"], "SAFE")
        self.assertGreaterEqual(result["wqi"], 95.0)
        self.assertFalse(result["lorawan_alert_required"])
        self.assertEqual(len(result["active_hazards"]), 0)
        self.assertGreaterEqual(result["vision_readings"]["clarity_percent"], 95.0)
        self.assertLess(result["ai_diagnostics"]["anomaly_score"], 0.15)
        self.assertEqual(result["ai_diagnostics"]["predicted_threat"], "CLEAN_POTABLE_WATER")

if __name__ == "__main__":
    unittest.main()



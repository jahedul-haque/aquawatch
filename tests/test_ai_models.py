"""
Unit Tests for Edge AI Vision Classifier & Multi-Modal Anomaly Model
"""

import unittest
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mpu_vision_service"))

from vision_ai_classifier import VisionAIClassifier
from sensor_anomaly_model import SensorAnomalyModel
from vision_inspector import WaterVisionInspector

class TestAIModels(unittest.TestCase):
    def setUp(self):
        self.vision_ai = VisionAIClassifier()
        self.sensor_ai = SensorAnomalyModel()
        self.inspector = WaterVisionInspector(camera_index=-1)

    # 1. Vision AI Inference Tests
    def test_vision_ai_clean_water(self):
        frame = self.inspector.capture_frame(simulation_condition="clear")
        res = self.vision_ai.classify(frame)

        self.assertEqual(res["top_classification"], "Clean_Potable")
        self.assertLess(res["optical_anomaly_score"], 0.45)
        self.assertGreater(res["confidence_percent"], 50.0)

    def test_vision_ai_hydrocarbon_sheen(self):
        frame = self.inspector.capture_frame(simulation_condition="sheen")
        res = self.vision_ai.classify(frame)

        self.assertEqual(res["top_classification"], "Hydrocarbon_Sheen")
        self.assertGreater(res["optical_anomaly_score"], 0.60)

    def test_vision_ai_suspended_sediment(self):
        frame = self.inspector.capture_frame(simulation_condition="turbid")
        res = self.vision_ai.classify(frame)

        self.assertIn(res["top_classification"], ["Suspended_Sediment", "Chemical_Discoloration"])
        self.assertGreater(res["optical_anomaly_score"], 0.60)

    # 2. Multi-Modal Anomaly Model Tests
    def test_sensor_ai_clean_baseline(self):
        mcu = {"temp_c": 18.2, "ph": 7.36, "turbidity_ntu": 0.38, "tds_ppm": 182.0, "orp_mv": 682.0}
        vision = {"clarity_percent": 96.0, "particulate_count": 1}
        vision_ai = {"optical_anomaly_score": 0.05, "top_classification": "Clean_Potable"}

        res = self.sensor_ai.predict(mcu, vision, vision_ai)

        self.assertLess(res["ai_anomaly_score"], 0.35)
        self.assertEqual(res["predicted_threat"], "CLEAN_POTABLE_WATER")
        self.assertFalse(res["sensor_drift_fault"])
        self.assertFalse(res["critical_alert_active"])

    def test_sensor_ai_probe_drift_rejection(self):
        # Only ORP has failed/drifted to 280mV, but pH, Turbidity, TDS, Temp and Vision are 100% clean!
        mcu = {"temp_c": 18.0, "ph": 7.35, "turbidity_ntu": 0.35, "tds_ppm": 180.0, "orp_mv": 280.0} # Single probe fault
        vision = {"clarity_percent": 96.0, "particulate_count": 1}
        vision_ai = {"optical_anomaly_score": 0.04, "top_classification": "Clean_Potable"}

        res = self.sensor_ai.predict(mcu, vision, vision_ai)

        # AI must recognize this as a single sensor probe drift/fouling, NOT declare water contamination!
        self.assertTrue(res["sensor_drift_fault"])
        self.assertEqual(res["drift_channel"], "orp_mv")
        self.assertIn("SENSOR_FAULT_DRIFT", res["predicted_threat"])
        self.assertLess(res["ai_anomaly_score"], 0.40) # Dampened score prevents false alarm
        self.assertFalse(res["critical_alert_active"])

    def test_sensor_ai_early_predictive_warning(self):
        # Correlated multi-parameter drift: pH slightly low (6.65), TDS slightly high (290), ORP slightly decaying (600)
        # None of these breach individual municipal hard limits (6.5, 300, 580)
        # But together, they indicate an early contamination shift!
        mcu = {"temp_c": 21.0, "ph": 6.62, "turbidity_ntu": 0.95, "tds_ppm": 295.0, "orp_mv": 590.0}
        vision = {"clarity_percent": 86.0, "particulate_count": 8}
        vision_ai = {"optical_anomaly_score": 0.35, "top_classification": "Clean_Potable"}

        res = self.sensor_ai.predict(mcu, vision, vision_ai)

        self.assertGreaterEqual(res["ai_anomaly_score"], 0.50)
        self.assertFalse(res["sensor_drift_fault"])

    def test_sensor_ai_critical_contamination(self):
        # Severe contamination: Acid spill
        mcu = {"temp_c": 22.0, "ph": 4.20, "turbidity_ntu": 2.5, "tds_ppm": 700.0, "orp_mv": 750.0}
        vision = {"clarity_percent": 82.0, "particulate_count": 5}
        vision_ai = {"optical_anomaly_score": 0.45, "top_classification": "Chemical_Discoloration"}

        res = self.sensor_ai.predict(mcu, vision, vision_ai)

        self.assertGreater(res["ai_anomaly_score"], 0.75)
        self.assertTrue(res["critical_alert_active"])
        self.assertEqual(res["predicted_threat"], "INDUSTRIAL_ACID_INFLUX")

    # 3. Calibration & One-Shot Prototype Learning Tests
    def test_calibration_manager_and_prototype_learning(self):
        import tempfile
        from calibration_manager import CalibrationManager

        with tempfile.TemporaryDirectory() as tmpdir:
            calib_file = os.path.join(tmpdir, "test_calib.json")
            mgr = CalibrationManager(config_path=calib_file)

            # Test learning a sample
            dummy_features = [170.0, 130.0, 126.0, 680.0, 0.0, 0.0]
            mcu_data = {"turbidity_ntu": 0.25, "spectral": {"f1": 100, "f2": 200, "clear": 1500, "nir": 100, "algae_ndai": -0.05, "cdom_index": 0.5}}
            vision_metrics = {"clarity_percent": 95.0, "laplacian_variance": 680.0, "discoloration_delta_e": 2.1}

            prof = mgr.learn_sample("Clean_Potable", dummy_features, mcu_data, vision_metrics)
            self.assertEqual(prof["category"], "Clean_Potable")
            self.assertEqual(prof["turbidity_ntu"], 0.25)
            self.assertTrue(os.path.exists(calib_file))

            # Test summary
            summary = mgr.get_summary()
            self.assertTrue(summary["is_calibrated"])
            self.assertEqual(summary["profiles_count"], 1)
            self.assertIn("Clean_Potable", summary["profiles"])

            # Test prototype extraction
            prototypes = mgr.get_prototype_vectors()
            self.assertIn("Clean_Potable", prototypes)
            self.assertEqual(len(prototypes["Clean_Potable"]), 6)

            # Apply prototype to Vision AI
            self.vision_ai.set_prototypes(prototypes)
            self.assertIn("Clean_Potable", self.vision_ai.prototypes)

            # Setting clean baseline on inspector
            self.inspector.set_clean_baseline([170.0, 130.0, 126.0], 680.0)
            self.assertEqual(self.inspector.baseline_var, 680.0)

            # Reset factory
            mgr.reset_factory()
            self.assertEqual(len(mgr.profiles), 0)
            self.vision_ai.reset_prototypes()
            self.assertEqual(len(self.vision_ai.prototypes), 0)
            self.inspector.reset_factory_baseline()
            self.assertEqual(self.inspector.baseline_var, 750.0)

if __name__ == "__main__":
    unittest.main()

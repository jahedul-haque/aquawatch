"""
Unit Tests for Computer Vision Pipeline on QRB2210
"""

import unittest
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mpu_vision_service"))

from vision_inspector import WaterVisionInspector

class TestVisionInspector(unittest.TestCase):
    def setUp(self):
        # Initialize in test mode (no physical camera required)
        self.inspector = WaterVisionInspector(camera_index=-1)

    def test_clear_water_frame(self):
        frame = self.inspector.capture_frame(simulation_condition="clear")
        metrics, annotated = self.inspector.analyze_frame(frame)

        self.assertGreater(metrics["clarity_percent"], 50.0)
        self.assertLess(metrics["particulate_count"], 15)
        self.assertFalse(metrics["surface_sheen_detected"])
        self.assertIsNotNone(annotated)
        self.assertEqual(annotated.shape, frame.shape)

    def test_turbid_water_frame(self):
        frame = self.inspector.capture_frame(simulation_condition="turbid")
        metrics, annotated = self.inspector.analyze_frame(frame)

        # Turbid frame should have significantly more detected particulate blobs
        self.assertGreater(metrics["particulate_count"], 10)
        self.assertIsNotNone(annotated)

    def test_surface_sheen_detection(self):
        frame = self.inspector.capture_frame(simulation_condition="sheen")
        metrics, annotated = self.inspector.analyze_frame(frame)

        self.assertTrue(metrics["surface_sheen_detected"])
        self.assertGreater(metrics["sheen_intensity"], 35.0)

    def test_rust_discoloration_detection(self):
        frame = self.inspector.capture_frame(simulation_condition="rust")
        metrics, annotated = self.inspector.analyze_frame(frame)

        self.assertGreater(metrics["discoloration_delta_e"], 12.0)
        self.assertEqual(metrics["tint_classification"], "Rust / Iron Influx")

if __name__ == "__main__":
    unittest.main()

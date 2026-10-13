"""
Unit Tests for SDCardManager 1-Minute Sampling & Circular Storage
"""

import unittest
import sys
import os
import shutil
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mpu_vision_service"))

from sdcard_manager import SDCardManager

class TestSDCardManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_sdcard_tmp"))
        os.makedirs(self.test_dir, exist_ok=True)
        self.manager = SDCardManager(target_mount=self.test_dir, max_storage_gb=1.0)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_sample(self):
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        telemetry = {
            "wqi": 92.5,
            "safety_level": "SAFE",
            "sensor_readings": {"ph": 7.35, "turbidity_ntu": 0.42}
        }

        full_path, filename = self.manager.save_sample(frame, telemetry)

        self.assertTrue(os.path.exists(full_path))
        self.assertTrue(filename.endswith(".jpg"))

        # Check companion JSON
        json_path = full_path.replace(".jpg", ".json")
        self.assertTrue(os.path.exists(json_path))

        status = self.manager.get_status()
        self.assertGreaterEqual(status["total_samples_saved"], 1)
        self.assertEqual(status["last_sample_filename"], filename)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["status_text"], "Mounted")

    def test_disabled_via_constructor(self):
        """Verifies that when logging is disabled, no files are written to disk."""
        disabled_manager = SDCardManager(target_mount=self.test_dir, enabled=False)
        self.assertFalse(disabled_manager.is_enabled())

        frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        telemetry = {"wqi": 90.0, "safety_level": "SAFE"}

        full_path, filename = disabled_manager.save_sample(frame, telemetry)
        self.assertEqual(full_path, "")
        self.assertEqual(filename, "")

        # Assert no files created in samples folder
        samples_dir = os.path.join(self.test_dir, "samples")
        if os.path.exists(samples_dir):
            self.assertEqual(len(os.listdir(samples_dir)), 0)

        status = disabled_manager.get_status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["status_text"], "Disabled (Config)")
        self.assertEqual(status["total_samples_saved"], 0)

    def test_dynamic_enable_disable_toggle(self):
        """Verifies that SDCardManager can dynamically toggle logging at runtime."""
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
        telemetry = {"wqi": 95.0, "safety_level": "SAFE"}

        # 1. Enabled initially
        p1, f1 = self.manager.save_sample(frame, telemetry)
        self.assertTrue(os.path.exists(p1))
        self.assertEqual(self.manager.get_status()["total_samples_saved"], 1)

        # 2. Disable dynamically
        self.manager.set_enabled(False)
        self.assertFalse(self.manager.is_enabled())
        p2, f2 = self.manager.save_sample(frame, telemetry)
        self.assertEqual(p2, "")
        self.assertEqual(f2, "")
        self.assertEqual(self.manager.get_status()["total_samples_saved"], 1)

        # 3. Re-enable dynamically
        self.manager.set_enabled(True)
        self.assertTrue(self.manager.is_enabled())
        p3, f3 = self.manager.save_sample(frame, telemetry)
        self.assertTrue(os.path.exists(p3))
        self.assertEqual(self.manager.get_status()["total_samples_saved"], 2)

    def test_config_file_loading_and_persistence(self):
        """Verifies that SDCardManager loads from config file and can persist changes."""
        import json
        cfg_file = os.path.join(self.test_dir, "custom_config.json")
        initial_cfg = {
            "sdcard_storage": {
                "enabled": False,
                "target_mount": self.test_dir,
                "max_storage_gb": 2.0,
                "save_companion_json": False
            }
        }
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(initial_cfg, f)

        cfg_manager = SDCardManager(config_path=cfg_file)
        self.assertFalse(cfg_manager.is_enabled())
        self.assertFalse(cfg_manager.save_companion_json)

        # Toggle and persist to config
        cfg_manager.set_enabled(True, persist=True)
        self.assertTrue(cfg_manager.is_enabled())

        # Re-read file from disk to verify persistence
        with open(cfg_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertTrue(persisted["sdcard_storage"]["enabled"])

if __name__ == "__main__":
    unittest.main()

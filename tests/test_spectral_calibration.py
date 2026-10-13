import unittest
import numpy as np
from contamination_engine import ContaminationEngine, HAZARD_CODES
from calibration_manager import CalibrationManager
from sensor_anomaly_model import SensorAnomalyModel

class TestSpectralCalibration(unittest.TestCase):
    def setUp(self):
        self.calib = CalibrationManager(config_path='H:/Projects/AquaWatch/applab/config/test_calib.json')
        self.calib.reset_factory()
        self.engine = ContaminationEngine()
        self.engine.set_spectral_baseline(self.calib.get_spectral_baseline())

    def tearDown(self):
        self.calib.reset_factory()

    def test_clear_water_under_white_led_not_algae(self):
        mcu_data = {
            'temp_c': 22.0,
            'ph': 7.35,
            'turbidity_ntu': 0.35,
            'tds_ppm': 160.0,
            'orp_mv': 670.0,
            'spectral': {
                'f1': 450, 'f2': 520, 'f3': 650, 'f4': 820,
                'f5': 1200, 'f6': 1050, 'f7': 680, 'f8': 420,
                'clear': 3200, 'nir': 80,
                'algae_ndai': 0.481,
                'cdom_index': 0.400,
                'detected': True
            }
        }
        vision_data = {
            'clarity_percent': 96.0,
            'particulate_count': 1,
            'discoloration_delta_e': 0.5,
            'tint_classification': 'Clear',
            'surface_sheen_detected': False,
            'camera_detected': True
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        hazard_codes = [h['code'] for h in assessment['active_hazards']]

        self.assertNotIn('HAZARD_ALGAL_BLOOM', hazard_codes,
                         'Clear water must NOT trigger HAZARD_ALGAL_BLOOM even if raw NDAI is +0.481')
        self.assertEqual(assessment['safety_level'], 'SAFE')
        self.assertFalse(assessment['lorawan_alert_required'])

        as7341_info = assessment['classifications']['as7341']
        self.assertEqual(as7341_info['title'], 'Clean')
        self.assertEqual(as7341_info['status'], 'SAFE')
        self.assertAlmostEqual(as7341_info['delta_ndai'], 0.001, places=2)

    def test_one_shot_calibration_clean_potable(self):
        mcu_data = {
            'temp_c': 21.0,
            'ph': 7.40,
            'turbidity_ntu': 0.30,
            'tds_ppm': 150.0,
            'orp_mv': 680.0,
            'spectral': {
                'f1': 460, 'f2': 530, 'f3': 670, 'f4': 840,
                'f5': 1250, 'f6': 1100, 'f7': 700, 'f8': 430,
                'clear': 3300, 'nir': 85,
                'algae_ndai': 0.488,
                'cdom_index': 0.410,
                'detected': True
            }
        }
        vision_metrics = {
            'clarity_percent': 98.0,
            'laplacian_variance': 780.0,
            'discoloration_delta_e': 0.2
        }
        visual_features = [182.0, 128.0, 128.0, 780.0, 0.0, 15.0]

        profile = self.calib.learn_sample('Clean_Potable', visual_features, mcu_data, vision_metrics)
        self.assertTrue(self.calib.get_spectral_baseline()['is_calibrated'])
        self.assertEqual(self.calib.get_spectral_baseline()['baseline_ndai'], 0.488)

        self.engine.set_spectral_baseline(self.calib.get_spectral_baseline())
        vision_data = {
            'clarity_percent': 98.0, 'particulate_count': 0,
            'discoloration_delta_e': 0.2, 'tint_classification': 'Clear',
            'surface_sheen_detected': False, 'camera_detected': True
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        as7341_info = assessment['classifications']['as7341']
        self.assertEqual(as7341_info['title'], 'Clean')
        self.assertAlmostEqual(as7341_info['delta_ndai'], 0.000, places=3)
        self.assertNotIn('HAZARD_ALGAL_BLOOM', [h['code'] for h in assessment['active_hazards']])

    def test_algal_bloom_detected_after_calibration(self):
        self.engine.set_spectral_baseline({'baseline_ndai': 0.488, 'baseline_cdom': 0.410, 'is_calibrated': True})

        mcu_data = {
            'temp_c': 24.5,
            'ph': 8.10,
            'turbidity_ntu': 4.80,
            'tds_ppm': 240.0,
            'orp_mv': 590.0,
            'spectral': {
                'f1': 600, 'f2': 650, 'f3': 950, 'f4': 1400,
                'f5': 2800, 'f6': 1600, 'f7': 1100, 'f8': 450,
                'clear': 4200, 'nir': 1850,
                'algae_ndai': 0.723,
                'cdom_index': 0.455,
                'detected': True
            }
        }
        vision_data = {
            'clarity_percent': 65.0,
            'particulate_count': 12,
            'discoloration_delta_e': 8.5,
            'tint_classification': 'Algae / Organic Tint',
            'surface_sheen_detected': False,
            'camera_detected': True
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        hazard_codes = [h['code'] for h in assessment['active_hazards']]

        self.assertIn('HAZARD_ALGAL_BLOOM', hazard_codes)
        self.assertEqual(assessment['hazard_code'], HAZARD_CODES['ALGAL_BLOOM'])
        self.assertTrue(assessment['lorawan_alert_required'])

        as7341_info = assessment['classifications']['as7341']
        self.assertEqual(as7341_info['title'], 'Algae Detected')
        self.assertAlmostEqual(as7341_info['delta_ndai'], 0.723 - 0.488, places=2)

    def test_white_paper_under_white_led_not_organic_matter(self):
        """Validates that clean white paper / clear water under AS7341 white LED phosphor
        (which naturally produces raw CDOM ~ +0.66) does NOT trigger Organic Matter false positive."""
        mcu_data = {
            'temp_c': 21.5,
            'ph': 7.40,
            'turbidity_ntu': 0.25,
            'tds_ppm': 150.0,
            'orp_mv': 675.0,
            'spectral': {
                'f1': 240, 'f2': 450, 'f3': 600, 'f4': 800,
                'f5': 1200, 'f6': 1150, 'f7': 700, 'f8': 420,
                'clear': 3400, 'nir': 90,
                'algae_ndai': 0.481,
                'cdom_index': 0.655,
                'delta_ndai': 0.001,
                'delta_cdom': 0.015,
                'detected': True
            }
        }
        vision_data = {
            'clarity_percent': 98.0,
            'particulate_count': 0,
            'discoloration_delta_e': 0.3,
            'tint_classification': 'Clear',
            'surface_sheen_detected': False,
            'camera_detected': True
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        as7341_info = assessment['classifications']['as7341']

        self.assertEqual(as7341_info['title'], 'Clean')
        self.assertEqual(as7341_info['status'], 'SAFE')
        self.assertNotIn('HAZARD_SEWAGE_INGRESS', [h['code'] for h in assessment['active_hazards']])

    def test_genuine_organic_matter_detected(self):
        """Validates that true dissolved organics / sewage with strong violet absorption
        and elevated turbidity properly triggers Organic Matter classification."""
        mcu_data = {
            'temp_c': 23.0,
            'ph': 6.60,
            'turbidity_ntu': 5.50,
            'tds_ppm': 650.0,
            'orp_mv': 310.0,
            'spectral': {
                'f1': 60, 'f2': 150, 'f3': 300, 'f4': 500,
                'f5': 900, 'f6': 1800, 'f7': 1600, 'f8': 1500,
                'clear': 3800, 'nir': 1200,
                'algae_ndai': -0.25,
                'cdom_index': 0.935,
                'delta_cdom': 0.295,
                'detected': True
            }
        }
        vision_data = {
            'clarity_percent': 45.0,
            'particulate_count': 18,
            'discoloration_delta_e': 12.0,
            'tint_classification': 'Sewage / Black Sludge',
            'surface_sheen_detected': False,
            'camera_detected': True
        }

        assessment = self.engine.evaluate(mcu_data, vision_data)
        as7341_info = assessment['classifications']['as7341']

        self.assertEqual(as7341_info['title'], 'Organic Matter')
        self.assertEqual(as7341_info['status'], 'CRITICAL')

if __name__ == '__main__':
    unittest.main()

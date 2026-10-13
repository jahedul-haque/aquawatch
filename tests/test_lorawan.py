"""
Unit Tests for LoRaWAN 15-Byte Binary Encoder & Decoder
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mpu_vision_service"))

from lorawan_service import LoRaWANService

class TestLoRaWAN(unittest.TestCase):
    def setUp(self):
        self.service = LoRaWANService(mock=True)

    def test_normal_heartbeat_payload(self):
        assessment = {
            "wqi": 92.0,
            "hazard_code": 0x00,
            "lorawan_alert_required": False,
            "sensor_readings": {
                "ph": 7.35,
                "turbidity_ntu": 0.4,
                "tds_ppm": 185.0,
                "orp_mv": 680.0,
                "temp_c": 21.5
            },
            "vision_readings": {
                "clarity_percent": 95.0,
                "particulate_count": 2,
                "surface_sheen_detected": False,
                "discoloration_delta_e": 2.0
            }
        }

        payload = self.service.build_binary_payload(assessment)
        self.assertEqual(len(payload), 15)

        decoded = LoRaWANService.decode_payload(payload)
        self.assertFalse(decoded["alert_flag"])
        self.assertEqual(decoded["hazard_code"], 0x00)
        self.assertEqual(decoded["wqi"], 92)
        self.assertAlmostEqual(decoded["ph"], 7.35, places=2)
        self.assertAlmostEqual(decoded["turbidity_ntu"], 0.4, places=1)
        self.assertEqual(decoded["tds_ppm"], 185)
        self.assertEqual(decoded["orp_mv"], 680)
        self.assertAlmostEqual(decoded["temp_c"], 21.5, places=1)
        self.assertEqual(decoded["clarity_percent"], 95)
        self.assertEqual(decoded["particulate_count"], 2)
        self.assertFalse(decoded["surface_sheen"])
        self.assertFalse(decoded["discoloration_anomaly"])

    def test_emergency_alert_payload_sewage(self):
        assessment = {
            "wqi": 28.0,
            "hazard_code": 0x04, # Sewage Ingress
            "lorawan_alert_required": True,
            "sensor_readings": {
                "ph": 6.30,
                "turbidity_ntu": 8.5,
                "tds_ppm": 850.0,
                "orp_mv": -120.0, # Anaerobic negative ORP
                "temp_c": 24.0
            },
            "vision_readings": {
                "clarity_percent": 30.0,
                "particulate_count": 45,
                "surface_sheen_detected": False,
                "discoloration_delta_e": 16.0 # Discolored
            }
        }

        payload = self.service.build_binary_payload(assessment)
        self.assertEqual(len(payload), 15)

        # Byte 0 must have bit 7 set (0x80 | 0x04 = 0x84)
        self.assertEqual(payload[0], 0x84)

        decoded = LoRaWANService.decode_payload(payload)
        self.assertTrue(decoded["alert_flag"])
        self.assertEqual(decoded["hazard_code"], 0x04)
        self.assertEqual(decoded["wqi"], 28)
        self.assertAlmostEqual(decoded["ph"], 6.30, places=2)
        self.assertAlmostEqual(decoded["turbidity_ntu"], 8.5, places=1)
        self.assertEqual(decoded["tds_ppm"], 850)
        self.assertEqual(decoded["orp_mv"], -120)
        self.assertTrue(decoded["discoloration_anomaly"])
        self.assertFalse(decoded["surface_sheen"])

    def test_emergency_alert_payload_sheen(self):
        assessment = {
            "wqi": 35.0,
            "hazard_code": 0x06, # Hydrocarbon Sheen
            "lorawan_alert_required": True,
            "sensor_readings": {
                "ph": 7.20,
                "turbidity_ntu": 1.2,
                "tds_ppm": 210.0,
                "orp_mv": 650.0,
                "temp_c": 20.0
            },
            "vision_readings": {
                "clarity_percent": 85.0,
                "particulate_count": 3,
                "surface_sheen_detected": True, # Sheen detected!
                "discoloration_delta_e": 4.0
            }
        }

        payload = self.service.build_binary_payload(assessment)
        self.assertEqual(len(payload), 15)

        decoded = LoRaWANService.decode_payload(payload)
        self.assertTrue(decoded["alert_flag"])
        self.assertEqual(decoded["hazard_code"], 0x06)
        self.assertTrue(decoded["surface_sheen"])

    def test_ebyte_e78_dtrx_command_formatting(self):
        """Validates that Ebyte E78-900M22S AT+DTRX commands are formatted correctly per ASR6505 manual."""
        hex_payload = "805E02E6000400B902A300D75F0200"
        
        # Test emergency confirmed alert on Port 15
        cmd_emergency = LoRaWANService.format_ebyte_dtrx_command(hex_payload, f_port=15, confirmed=True)
        self.assertEqual(cmd_emergency, "AT+DTRX=1,15,15,805E02E6000400B902A300D75F0200")
        
        # Test routine unconfirmed heartbeat on Port 10
        cmd_heartbeat = LoRaWANService.format_ebyte_dtrx_command(hex_payload, f_port=10, confirmed=False)
        self.assertEqual(cmd_heartbeat, "AT+DTRX=0,10,15,805E02E6000400B902A300D75F0200")

    def test_ebyte_e78_status_metadata(self):
        """Validates that get_lorawan_status returns Ebyte E78-900M22S and IN865 parameters."""
        status = self.service.get_lorawan_status()
        self.assertIn("Ebyte E78-900M22S", status["modem_model"])
        self.assertEqual(status["tx_power_dbm"], 22)
        self.assertIn("ASR6505", status["soc"])
        self.assertIn("IN865", status["region"])
        self.assertIn("AT+DTRX", status["command_syntax"])
        self.assertEqual(status["dev_eui"], "70B3D57ED006A1B2")
        self.assertIsNotNone(status.get("last_uplink"))

    def test_deveui_retrieval(self):
        """Validates that DevEUI is properly loaded and exposed."""
        deveui = self.service.get_deveui()
        self.assertEqual(len(deveui), 16)
        self.assertEqual(deveui, "70B3D57ED006A1B2")

    def test_last_uplink_record_structure(self):
        """Validates that the last transmitted message record is populated and formatted."""
        last = self.service.last_uplink_record
        self.assertIsNotNone(last)
        self.assertIn("payload_hex", last)
        self.assertIn("payload_hex_spaced", last)
        self.assertIn("summary", last)
        self.assertIn("decoded", last)
        self.assertEqual(last["f_port"], 10)
        self.assertEqual(last["bytes_length"], 15)

    def test_manual_send_now(self):
        """Validates that send_uplink_now dispatches an uplink immediately."""
        test_assessment = {
            "wqi": 95,
            "hazard_code": 0,
            "lorawan_alert_required": False,
            "sensor_readings": {"ph": 7.4, "turbidity_ntu": 0.2, "tds_ppm": 200, "orp_mv": 650, "temp_c": 22.0},
            "vision_readings": {"clarity_percent": 98, "particulate_count": 1, "surface_sheen_detected": False, "discoloration_delta_e": 1.0}
        }
        rec = self.service.send_uplink_now(test_assessment)
        self.assertEqual(rec["status"], "DELIVERED")
        self.assertEqual(rec["wqi"], 95)
        self.assertIn("payload_hex_spaced", rec)
        self.assertEqual(self.service.last_uplink_record["payload_hex"], rec["payload_hex"])

    def test_node_not_found_when_no_hardware(self):
        """Validates that if physical modem is absent, node_found is False and no values are assumed."""
        unconnected_service = LoRaWANService(port="NONEXISTENT_PORT_COM99", mock=False)
        self.assertFalse(unconnected_service.node_found)
        self.assertFalse(unconnected_service.connected)
        self.assertIsNone(unconnected_service.get_deveui())
        self.assertIsNone(unconnected_service.get_appskey())
        self.assertIsNone(unconnected_service.last_uplink_record)
        
        status = unconnected_service.get_lorawan_status()
        self.assertFalse(status["node_found"])
        self.assertFalse(status["connected"])
        self.assertIsNone(status["dev_eui"])
        self.assertIsNone(status["appskey"])
        self.assertEqual(status["region"], "Not connected")
        self.assertEqual(status["modem_model"], "Not detected")

        # DevEUI set attempt must fail when node is not found
        ok, msg = unconnected_service.set_deveui("0123456789ABCDEF")
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

        # Uplink send must report failure without assuming delivery
        rec = unconnected_service.send_uplink_now({"wqi": 90})
        self.assertEqual(rec["status"], "NODE_NOT_FOUND")

    def test_deveui_validation_format(self):
        """Validates that set_deveui strictly enforces 16-hex character formatting."""
        ok, msg = self.service.set_deveui("TOO_SHORT")
        self.assertFalse(ok)
        self.assertIn("16", msg)

        ok, msg = self.service.set_deveui("0123456789ABCDEF")
        self.assertTrue(ok)
        self.assertEqual(self.service.get_deveui(), "0123456789ABCDEF")

if __name__ == "__main__":
    unittest.main()

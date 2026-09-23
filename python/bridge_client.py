"""
Arduino UNO Q Inter-Processor Communication (IPC) Bridge Client
Connects the Qualcomm QRB2210 (Debian Linux MPU) with the STM32U585 MCU.

Synchronizes sensor telemetry and forwards alert flags to MCU.
"""

import json
import logging
import os
import random
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("BridgeClient")

class STM32BridgeClient:
    def __init__(self, mode: str = "auto", port: str = "/dev/ttyACM0", baudrate: int = 115200):
        self.mode = mode
        self.port = port
        self.baudrate = baudrate
        self.connected = False
        self.rpc_bridge = None
        self.serial_conn = None

        # Static sensor configuration (Safe BIS IS 10500 baselines when physical probes omitted)
        self.use_static_ph = True
        self.static_ph_value = 7.35
        self.use_static_tds = True
        self.static_tds_value = 180.0
        self.use_static_orp = True
        self.static_orp_value = 675.0

        self._load_static_config()
        
        # State for mock / simulation
        self._sim_temp = 21.5
        self._sim_ph = 7.35
        self._sim_turbidity = 0.45
        self._sim_tds = 180.0
        self._sim_orp = 675.0
        self._sim_sample_count = 0
        self._sim_alert = False
        self._sim_hazard_code = 0
        self._sim_scenario = "normal"
        
        self.connect()

    def _load_static_config(self):
        """Loads static baseline settings from config/thresholds.json if present."""
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "thresholds.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                s_opts = cfg.get("static_sensor_options", {})
                if "ph" in s_opts:
                    self.use_static_ph = s_opts["ph"].get("use_static", self.use_static_ph)
                    self.static_ph_value = float(s_opts["ph"].get("static_value", self.static_ph_value))
                if "tds" in s_opts:
                    self.use_static_tds = s_opts["tds"].get("use_static", self.use_static_tds)
                    self.static_tds_value = float(s_opts["tds"].get("static_value", self.static_tds_value))
                if "orp" in s_opts:
                    self.use_static_orp = s_opts["orp"].get("use_static", self.use_static_orp)
                    self.static_orp_value = float(s_opts["orp"].get("static_value", self.static_orp_value))
            except Exception as e:
                logger.debug(f"Could not load static sensor config: {e}")

    def connect(self):
        """Attempts to initialize communication through RPC, Serial, or fallback to Mock."""
        if self.mode in ("rpc", "auto"):
            # 1. Official Arduino App Lab Bridge (arduino.app_utils)
            try:
                from arduino.app_utils import Bridge  # type: ignore
                self.rpc_bridge = Bridge
                self.mode = "rpc"
                self.connected = True
                logger.info("Connected to STM32 MCU via Arduino App Lab Bridge RPC.")
                return
            except (ImportError, Exception) as e:
                logger.debug(f"arduino.app_utils Bridge not available: {e}")

            # 2. Direct Arduino RouterBridge (arduino.router_bridge)
            try:
                from arduino.router_bridge import Bridge as RouterBridge  # type: ignore
                self.rpc_bridge = RouterBridge()
                self.rpc_bridge.connect()
                self.mode = "rpc"
                self.connected = True
                logger.info("Connected to STM32 MCU via Arduino RouterBridge.")
                return
            except (ImportError, Exception) as e:
                logger.debug(f"arduino.router_bridge not available: {e}")

            # 3. Legacy standalone module name
            try:
                import arduino_router_bridge  # type: ignore
                self.rpc_bridge = arduino_router_bridge.Bridge()
                self.rpc_bridge.begin()
                self.mode = "rpc"
                self.connected = True
                logger.info("Connected to STM32 MCU via legacy arduino_router_bridge RPC.")
                return
            except (ImportError, Exception) as e:
                logger.debug(f"RouterBridge RPC not available: {e}")

        if self.mode in ("serial", "auto"):
            try:
                import serial
                self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1.0)
                time.sleep(1.5)
                self.mode = "serial"
                self.connected = True
                logger.info(f"Connected to STM32 MCU via Serial ({self.port}).")
                return
            except (ImportError, Exception) as e:
                logger.debug(f"Serial connection not available on {self.port}: {e}")

        logger.info("No physical STM32 MCU detected. Operating in high-fidelity SIMULATION mode.")
        self.mode = "mock"
        self.connected = True

    def get_telemetry(self) -> Dict[str, Any]:
        """Queries the STM32 MCU for the latest 5-sensor package or simulated scenario."""
        # If an injected test scenario is active, override with high-fidelity simulated emergency data
        if self._sim_scenario != "normal":
            return self._generate_simulated_telemetry()

        data = None
        if self.mode == "rpc" and self.rpc_bridge:
            try:
                raw = self.rpc_bridge.call("get_telemetry", "")
                if isinstance(raw, str):
                    data = json.loads(raw)
                elif isinstance(raw, dict):
                    data = raw
            except Exception as e:
                logger.error(f"RPC get_telemetry failed: {e}")

        elif self.mode == "serial" and self.serial_conn:
            try:
                self.serial_conn.write(b"GET\n")
                line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)
            except Exception as e:
                logger.error(f"Serial get_telemetry failed: {e}")

        if data is None:
            # If in mock mode, periodically check if the RPC bridge has become available
            if self.mode == "mock" and (self._sim_sample_count % 10 == 0):
                self.mode = "auto"
                self.connect()
                if self.mode == "rpc" and self.rpc_bridge:
                    try:
                        raw = self.rpc_bridge.call("get_telemetry", "")
                        if isinstance(raw, str):
                            data = json.loads(raw)
                        elif isinstance(raw, dict):
                            data = raw
                    except Exception:
                        self.mode = "mock"

        if data is None:
            data = self._generate_simulated_telemetry()

        # Enforce static baseline overrides if configured
        if self.use_static_ph:
            data["ph"] = self.static_ph_value
            data["ph_dummy"] = True
        elif "ph_dummy" not in data:
            data["ph_dummy"] = False

        if self.use_static_tds:
            data["tds_ppm"] = self.static_tds_value
            data["tds_dummy"] = True
        elif "tds_dummy" not in data:
            data["tds_dummy"] = False

        if self.use_static_orp:
            data["orp_mv"] = self.static_orp_value
            data["orp_dummy"] = True
        elif "orp_dummy" not in data:
            data["orp_dummy"] = False

        # Ensure spectral data is present
        if "spectral" not in data:
            data["spectral"] = self._generate_simulated_spectral()

        return data

    def get_spectral_data(self) -> Dict[str, Any]:
        """Returns the latest 10-channel AS7341 spectral readings and computed indices."""
        telemetry = self.get_telemetry()
        return telemetry.get("spectral", self._generate_simulated_spectral())

    def trigger_sample(self) -> bool:
        """Signals STM32 MCU to initiate 1-second pre-warm & optical sample immediately."""
        if self.mode == "rpc" and self.rpc_bridge:
            try:
                self.rpc_bridge.call("trigger_sample", "")
                logger.info("Triggered on-demand sample via Bridge RPC.")
                return True
            except Exception as e:
                logger.debug(f"RPC trigger_sample unavailable: {e}")
        elif self.mode == "serial" and self.serial_conn:
            try:
                self.serial_conn.write(b"SAMPLE_NOW\n")
                logger.info("Triggered on-demand sample via Serial.")
                return True
            except Exception as e:
                logger.debug(f"Serial trigger_sample failed: {e}")
        return False

    def set_spectral_led(self, state: bool) -> bool:
        """Turns the AS7341 flow-cell illumination LED on or off via Bridge RPC or Serial."""
        val = "1" if state else "0"
        if self.mode == "rpc" and self.rpc_bridge:
            try:
                self.rpc_bridge.call("set_spectral_led", val)
                logger.info(f"Set AS7341 LED: {val} via RPC.")
                return True
            except Exception as e:
                logger.debug(f"RPC set_spectral_led unavailable: {e}")
        elif self.mode == "serial" and self.serial_conn:
            try:
                self.serial_conn.write(f"SET_SPECTRAL_LED:{val}\n".encode('utf-8'))
                logger.info(f"Set AS7341 LED: {val} via Serial.")
                return True
            except Exception as e:
                logger.debug(f"Serial set_spectral_led failed: {e}")
        return False

    def notify_mcu_alert(self, alert_flag: bool, hazard_code: int):
        """Notifies STM32 of detected contamination state for onboard LED/telemetry sync."""
        self._sim_alert = alert_flag
        self._sim_hazard_code = hazard_code

        payload = f"{1 if alert_flag else 0}:{hazard_code}"
        if self.mode == "rpc" and self.rpc_bridge:
            try:
                self.rpc_bridge.call("set_alert_state", payload)
            except Exception as e:
                logger.error(f"RPC notify_mcu_alert failed: {e}")
        elif self.mode == "serial" and self.serial_conn:
            try:
                self.serial_conn.write(f"ALERT:{payload}\n".encode('utf-8'))
            except Exception as e:
                logger.error(f"Serial notify_mcu_alert failed: {e}")

    def send_lora_at(self, cmd: str) -> str:
        """Sends AT command to LoRa module connected on Arduino pins D0/D1 (Serial1)."""
        if self.mode == "rpc" and self.rpc_bridge:
            try:
                resp = self.rpc_bridge.call("send_lora_at", cmd)
                return str(resp).strip() if resp is not None else ""
            except Exception as e:
                logger.debug(f"RPC send_lora_at failed: {e}")
        elif self.mode == "serial" and self.serial_conn:
            try:
                self.serial_conn.write(f"LORA_AT:{cmd}\n".encode('utf-8'))
                deadline = time.time() + 1.2
                while time.time() < deadline:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    if line.startswith("LORA_RESP:"):
                        return line[10:].strip()
                return ""
            except Exception as e:
                logger.debug(f"Serial send_lora_at failed: {e}")
        elif self.mode == "mock":
            cmd_upper = cmd.strip().upper()
            if cmd_upper == "AT":
                return "OK"
            elif "CGMM" in cmd_upper:
                return "+CGMM=6501\nASR6501:~#"
            elif "CDEVEUI" in cmd_upper:
                return "+CDEVEUI=00A604E1D50EE9C2\nOK"
            elif "CAPPSKEY" in cmd_upper or "APPSKEY" in cmd_upper:
                return "+CAPPSKEY=EF6D6E2503F57AE2FA151CDA87455F18\nOK"
            elif "CSTATUS" in cmd_upper:
                return "+CSTATUS=04\nOK"
            elif "CSQ" in cmd_upper:
                return "+CSQ=26,-68,9.5\nOK"
            elif "CJOIN?" in cmd_upper:
                return "+CJOIN:OK (1,0)\nASR6501:~#"
            elif "CJOIN" in cmd_upper or "JOIN" in cmd_upper:
                return "+CJOIN:OK\nASR6501:~#"
            elif "DTRX" in cmd_upper or "SEND" in cmd_upper or "DTX" in cmd_upper:
                return "OK+SENT:15\nASR6501:~#"
            elif "HELP" in cmd_upper:
                return "ASR6501 AT Commands:\n  AT\n  AT+CGMM?\n  AT+CDEVEUI?\n  AT+CJOIN\n  AT+CJOIN?\n  AT+CSTATUS?\n  AT+CSQ?\n  AT+DTRX=..."
            return "OK\nASR6501:~#"
        return ""

    def set_lora_baud(self, baud: int) -> bool:
        """Sets baud rate on Arduino Serial1 (pins D0/D1)."""
        if self.mode == "rpc" and self.rpc_bridge:
            try:
                resp = self.rpc_bridge.call("set_lora_baud", str(baud))
                return "OK" in str(resp)
            except Exception as e:
                logger.debug(f"RPC set_lora_baud failed: {e}")
        elif self.mode == "serial" and self.serial_conn:
            try:
                self.serial_conn.write(f"SET_LORA_BAUD:{baud}\n".encode('utf-8'))
                deadline = time.time() + 1.0
                while time.time() < deadline:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    if "OK:LORA_BAUD_SET" in line:
                        return True
            except Exception:
                pass
        return False


    def set_static_options(self, use_ph: Optional[bool] = None, ph_val: Optional[float] = None,
                           use_tds: Optional[bool] = None, tds_val: Optional[float] = None,
                           use_orp: Optional[bool] = None, orp_val: Optional[float] = None):
        """Allows enabling/disabling static mode and setting custom static baseline values."""
        if use_ph is not None: self.use_static_ph = use_ph
        if ph_val is not None: self.static_ph_value = float(ph_val)
        if use_tds is not None: self.use_static_tds = use_tds
        if tds_val is not None: self.static_tds_value = float(tds_val)
        if use_orp is not None: self.use_static_orp = use_orp
        if orp_val is not None: self.static_orp_value = float(orp_val)

        logger.info(f"Updated static options: pH={self.static_ph_value} (active={self.use_static_ph}), "
                    f"TDS={self.static_tds_value} (active={self.use_static_tds}), "
                    f"ORP={self.static_orp_value} (active={self.use_static_orp})")

    def get_static_options(self) -> Dict[str, Any]:
        """Returns the current static baseline sensor configuration."""
        return {
            "ph": {"use_static": self.use_static_ph, "value": self.static_ph_value},
            "tds": {"use_static": self.use_static_tds, "value": self.static_tds_value},
            "orp": {"use_static": self.use_static_orp, "value": self.static_orp_value}
        }

    def set_simulation_scenario(self, scenario: str):
        """Allows injecting water quality events in mock mode for testing/demo."""
        valid_scenarios = [
            "normal", "acid_spill", "sewage", "pipe_burst", 
            "disinfection_loss", "alkaline_shock", "algal_bloom", "chemical_dye", "sheen"
        ]
        if scenario in valid_scenarios:
            self._sim_scenario = scenario
            logger.info(f"Simulation scenario set to: {scenario}")

    def _generate_simulated_spectral(self) -> Dict[str, Any]:
        """Generates realistic 10-channel AS7341 spectral curves for water types."""
        jitter = lambda scale: random.gauss(0, scale)

        if self._sim_scenario == "algal_bloom":
            # Chlorophyll-a: strong 555nm reflection (F5), deep 680nm absorption (F8)
            f1, f2, f3, f4, f5, f6, f7, f8, clr, nir = 850, 620, 1100, 1550, 3800, 1950, 1400, 720, 5200, 1650
        elif self._sim_scenario == "sewage":
            # Dissolved organics / CDOM: severe violet/blue absorption (F1, F2), yellow intact (F6)
            f1, f2, f3, f4, f5, f6, f7, f8, clr, nir = 80, 180, 520, 800, 1100, 1800, 1720, 1750, 3100, 2200
        elif self._sim_scenario == "chemical_dye":
            # Textile / industrial dye effluent (strong red/orange hue)
            f1, f2, f3, f4, f5, f6, f7, f8, clr, nir = 1400, 1500, 1600, 920, 580, 1100, 2950, 3250, 4200, 1150
        elif self._sim_scenario == "pipe_burst":
            # Mud / silt sediment: broadband attenuation, high NIR backscatter
            f1, f2, f3, f4, f5, f6, f7, f8, clr, nir = 420, 500, 580, 690, 820, 950, 1080, 1200, 1950, 3850
        if self._sim_scenario == "normal":
            return {
                "f1": 0, "f2": 0, "f3": 0, "f4": 0,
                "f5": 0, "f6": 0, "f7": 0, "f8": 0,
                "clear": 0, "nir": 0,
                "algae_ndai": 0.0,
                "cdom_index": 0.0,
                "detected": False
            }

        # Inject realistic sensor ADC noise for active test scenarios
        f1 = max(10, int(f1 + jitter(12)))
        f2 = max(10, int(f2 + jitter(12)))
        f3 = max(10, int(f3 + jitter(12)))
        f4 = max(10, int(f4 + jitter(12)))
        f5 = max(10, int(f5 + jitter(12)))
        f6 = max(10, int(f6 + jitter(12)))
        f7 = max(10, int(f7 + jitter(12)))
        f8 = max(10, int(f8 + jitter(12)))
        clr = max(50, int(clr + jitter(30)))
        nir = max(10, int(nir + jitter(12)))

        denom_a = float(f5 + f8)
        algae_ndai = round((float(f5 - f8)) / denom_a, 3) if denom_a > 10.0 else 0.0
        denom_c = float(f6 + f1)
        cdom_index = round((float(f6 - f1)) / denom_c, 3) if denom_c > 10.0 else 0.0
        delta_ndai = round(algae_ndai - 0.48, 3) if algae_ndai > 0.30 else 0.0
        delta_cdom = round(cdom_index - 0.64, 3) if cdom_index > 0.40 else 0.0

        return {
            "f1": f1, "f2": f2, "f3": f3, "f4": f4,
            "f5": f5, "f6": f6, "f7": f7, "f8": f8,
            "clear": clr, "nir": nir,
            "algae_ndai": algae_ndai,
            "cdom_index": cdom_index,
            "delta_ndai": delta_ndai,
            "delta_cdom": delta_cdom,
            "detected": (self._sim_scenario != "normal")
        }


    def _generate_simulated_telemetry(self) -> Dict[str, Any]:
        self._sim_sample_count += 1
        jitter = lambda scale: random.gauss(0, scale)

        if self._sim_scenario == "normal":
            target_ph, target_turb, target_tds, target_orp, target_temp = 7.35, 0.35, 180.0, 675.0, 21.0
        elif self._sim_scenario == "acid_spill":
            target_ph, target_turb, target_tds, target_orp, target_temp = 4.80, 1.20, 650.0, 720.0, 23.0
        elif self._sim_scenario == "sewage":
            target_ph, target_turb, target_tds, target_orp, target_temp = 6.40, 8.50, 850.0, 180.0, 24.5
        elif self._sim_scenario == "pipe_burst":
            target_ph, target_turb, target_tds, target_orp, target_temp = 7.20, 18.0, 420.0, 580.0, 20.5
        elif self._sim_scenario == "disinfection_loss":
            target_ph, target_turb, target_tds, target_orp, target_temp = 7.50, 0.50, 190.0, 420.0, 22.0
        elif self._sim_scenario == "alkaline_shock":
            target_ph, target_turb, target_tds, target_orp, target_temp = 9.80, 2.10, 720.0, 510.0, 22.5
        elif self._sim_scenario == "algal_bloom":
            target_ph, target_turb, target_tds, target_orp, target_temp = 8.40, 3.80, 240.0, 520.0, 26.0
        elif self._sim_scenario == "chemical_dye":
            target_ph, target_turb, target_tds, target_orp, target_temp = 6.90, 1.80, 410.0, 610.0, 21.5
        else:
            target_ph, target_turb, target_tds, target_orp, target_temp = 7.0, 0.5, 200.0, 650.0, 20.0

        if self._sim_scenario != "normal":
            # For injected emergency testing, jump immediately to scenario values
            self._sim_ph = target_ph
            self._sim_turbidity = target_turb
            self._sim_tds = target_tds
            self._sim_orp = target_orp
            self._sim_temp = target_temp

            out_ph = round(max(0.0, min(14.0, target_ph + jitter(0.01))), 2)
            out_turb = round(max(0.0, target_turb + abs(jitter(0.03))), 2)
            out_tds = round(max(0.0, target_tds + jitter(1.5)), 1)
            out_orp = round(target_orp + jitter(2.0), 1)
            out_temp = round(target_temp + jitter(0.05), 2)

            return {
                "temp_c": out_temp,
                "ph": out_ph,
                "ph_dummy": False,
                "turbidity_ntu": out_turb,
                "tds_ppm": out_tds,
                "tds_dummy": False,
                "orp_mv": out_orp,
                "orp_dummy": False,
                "spectral": self._generate_simulated_spectral(),
                "alert": self._sim_alert,
                "hazard_code": self._sim_hazard_code,
                "samples": self._sim_sample_count,
                "uptime_ms": int(time.time() * 1000)
            }

        self._sim_ph += 0.1 * (target_ph - self._sim_ph) + jitter(0.02)
        self._sim_turbidity += 0.1 * (target_turb - self._sim_turbidity) + abs(jitter(0.04))
        self._sim_tds += 0.1 * (target_tds - self._sim_tds) + jitter(2.0)
        self._sim_orp += 0.1 * (target_orp - self._sim_orp) + jitter(3.0)
        self._sim_temp += 0.05 * (target_temp - self._sim_temp) + jitter(0.05)

        out_ph = round(self.static_ph_value + jitter(0.005), 2) if self.use_static_ph else round(max(0.0, min(14.0, self._sim_ph)), 2)
        out_tds = round(max(0.0, self.static_tds_value + jitter(0.2)), 1) if self.use_static_tds else round(max(0.0, self._sim_tds), 1)
        out_orp = round(self.static_orp_value + jitter(0.5), 1) if self.use_static_orp else round(self._sim_orp, 1)

        return {
            "temp_c": -127.0,
            "temp_dummy": True,
            "temp_connected": False,
            "ph": out_ph,
            "ph_dummy": self.use_static_ph,
            "turbidity_ntu": round(max(0.0, self._sim_turbidity), 2),
            "tds_ppm": out_tds,
            "tds_dummy": self.use_static_tds,
            "orp_mv": out_orp,
            "orp_dummy": self.use_static_orp,
            "spectral": self._generate_simulated_spectral(),
            "alert": self._sim_alert,
            "hazard_code": self._sim_hazard_code,
            "samples": self._sim_sample_count,
            "uptime_ms": int(time.time() * 1000)
        }


"""
AquaWatch: Edge-AI LoRaWAN Water Quality Monitoring for Rural India
Fuses real-time physical-chemical sensor telemetry (STM32 MCU with AZDM01 Turbidity)
with optical computer vision metrics and Edge AI inference (QRB2210 MPU)
to compute a composite Water Quality Index (WQI), AI anomaly probability,
and diagnose contamination hazards according to BIS IS 10500:2012 and Jal Jeevan Mission standards.
"""

import json
import logging
from typing import Dict, Any, List, Tuple, Optional
import numpy as np

from vision_ai_classifier import VisionAIClassifier
from sensor_anomaly_model import SensorAnomalyModel

logger = logging.getLogger("ContaminationEngine")

HAZARD_CODES = {
    "NONE": 0x00,
    "DISINFECTION_LOSS": 0x01,
    "ACID_CONTAMINATION": 0x02,
    "CAUSTIC_ALKALINE": 0x03,
    "SEWAGE_INGRESS": 0x04,
    "SEDIMENT_PIPE_BURST": 0x05,
    "HYDROCARBON_SHEEN": 0x06,
    "HIGH_SALINITY_TDS": 0x07,
    "GENERAL_DEGRADATION": 0x08,
    "AI_PREDICTIVE_ANOMALY": 0x09,
    "ALGAL_BLOOM": 0x0A,
    "CHEMICAL_DYE": 0x0B
}


class ContaminationEngine:
    def __init__(self, config_path: str = None):
        self.weights = {
            "ph": 0.20,
            "turbidity": 0.20,
            "orp": 0.20,
            "tds": 0.15,
            "clarity": 0.15,
            "temp": 0.10
        }
        self.vision_ai = VisionAIClassifier()
        self.sensor_anomaly = SensorAnomalyModel()
        self.last_hazard_code = 0x00
        self.spectral_baseline: Dict[str, Any] = {
            "baseline_ndai": 0.11,
            "baseline_cdom": 0.75,
            "clear_ref": 59855.0,
            "vis_sum_ref": 114284.0,
            "is_calibrated": False
        }

    def set_spectral_baseline(self, baseline: Dict[str, Any]):
        """Sets the clean water spectral baseline for AS7341."""
        if isinstance(baseline, dict):
            self.spectral_baseline = baseline
            logger.info(f"ContaminationEngine updated spectral baseline: NDAI={baseline.get('baseline_ndai')}, Calibrated={baseline.get('is_calibrated')}")


    def evaluate(self, mcu_data: Dict[str, Any], vision_data: Dict[str, Any],
                 raw_frame: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """
        Fuses MCU sensor telemetry with vision analytics and Edge AI models.
        """
        temp_c = mcu_data.get("temp_c", 20.0)
        ph = mcu_data.get("ph", 7.0)
        turb_ntu = mcu_data.get("turbidity_ntu", 0.5)
        tds_ppm = mcu_data.get("tds_ppm", 150.0)
        orp_mv = mcu_data.get("orp_mv", 650.0)

        clarity_pct = vision_data.get("clarity_percent", 95.0)
        delta_e = vision_data.get("discoloration_delta_e", 0.0)
        tint = vision_data.get("tint_classification", "Clear")
        particulates = vision_data.get("particulate_count", 0)
        sheen = vision_data.get("surface_sheen_detected", False)

        camera_detected = vision_data.get("camera_detected", True)

                # 0. Compute baseline-compensated spectral indices (delta_ndai, delta_cdom)
        if "spectral" in mcu_data and isinstance(mcu_data["spectral"], dict):
            spec = mcu_data["spectral"]
            raw_ndai = float(spec.get("algae_ndai", 0.0))
            raw_cdom = float(spec.get("cdom_index", 0.0))
            is_calib = bool(self.spectral_baseline.get("is_calibrated", False))
            base_ndai = float(self.spectral_baseline.get("baseline_ndai", 0.11)) if is_calib else 0.11
            base_cdom = float(self.spectral_baseline.get("baseline_cdom", 0.75)) if is_calib else 0.75

            delta_ndai = round(max(0.0, raw_ndai - base_ndai), 3) if raw_ndai > 0.12 else 0.0
            delta_cdom = round(max(0.0, raw_cdom - base_cdom), 3) if raw_cdom > 0.75 else 0.0

            spec["delta_ndai"] = delta_ndai
            spec["delta_cdom"] = delta_cdom
            spec["baseline_ndai"] = base_ndai
            spec["baseline_cdom"] = base_cdom
            spec["spectral_calibrated"] = is_calib


        # 1. Run Vision AI Inference if physical frame available
        if not camera_detected:
            vision_ai_result = {
                "top_classification": "Camera_Offline",
                "confidence_percent": 100.0,
                "optical_anomaly_score": 0.0,
                "class_probabilities": {"Camera_Offline": 1.0}
            }
            clarity_pct = 95.0 # Neutral safe baseline when optical camera is disconnected
            particulates = 0
            sheen = False
        elif raw_frame is not None:
            vision_ai_result = self.vision_ai.classify(raw_frame)
            # Physical turbidity corroboration:
            # If the physical 940nm sensor measures clean water (turb_ntu <= 0.5 NTU),
            # the absence of optical grid edges in an unpatterned container must not be
            # misdiagnosed as Suspended_Sediment
            if turb_ntu <= 0.5 and vision_ai_result.get("top_classification") == "Suspended_Sediment":
                vision_ai_result["top_classification"] = "Clean_Potable"
                vision_ai_result["optical_anomaly_score"] = min(0.10, vision_ai_result.get("optical_anomaly_score", 0.10))
                if "class_probabilities" in vision_ai_result:
                    probs = vision_ai_result["class_probabilities"]
                    probs["Clean_Potable"] = probs.get("Suspended_Sediment", 0.90)
                    probs["Suspended_Sediment"] = 0.01
        else:
            # Synthetic feature fallback from vision_data
            opt_score = 0.85 if sheen else (0.75 if delta_e > 12.0 else (0.60 if clarity_pct < 60.0 else 0.05))
            v_class = "Hydrocarbon_Sheen" if sheen else ("Chemical_Discoloration" if delta_e > 12.0 else ("Suspended_Sediment" if turb_ntu > 5.0 else "Clean_Potable"))
            vision_ai_result = {
                "top_classification": v_class,
                "confidence_percent": 88.0,
                "optical_anomaly_score": opt_score,
                "class_probabilities": {v_class: 0.88, "Clean_Potable": 0.12}
            }

        # Corroborate visual clarity and particulates with physical turbidity:
        # If the physical 940nm photoelectric sensor measures clean water (turb_ntu <= 0.5 NTU)
        # and Vision AI classifies Clean_Potable, optical chamber wall reflections or absence of high-contrast
        # calibration grid must not falsely crush the visual clarity metric.
        effective_particles = particulates
        if turb_ntu <= 0.5 and (vision_ai_result.get("top_classification") == "Clean_Potable"):
            effective_particles = min(particulates, int(turb_ntu * 20) + 3)
            clarity_pct = max(clarity_pct, max(95.0, 100.0 - (turb_ntu * 10.0)))
            vision_data["clarity_percent"] = clarity_pct
            if "optical_anomaly_score" in vision_ai_result:
                vision_ai_result["optical_anomaly_score"] = min(vision_ai_result["optical_anomaly_score"], 0.10)
        elif turb_ntu <= 1.0 and (vision_ai_result.get("top_classification") == "Clean_Potable"):
            clarity_pct = max(clarity_pct, 90.0)
            vision_data["clarity_percent"] = clarity_pct

        # 2. Run Multi-Modal Sensor Anomaly Inference
        anomaly_ai_result = self.sensor_anomaly.predict(mcu_data, vision_data, vision_ai_result)

        # 3. Calculate deterministic sub-indices
        q_ph = self._subindex_ph(ph)
        q_turb = self._subindex_turbidity(turb_ntu)
        q_orp = self._subindex_orp(orp_mv)
        q_tds = self._subindex_tds(tds_ppm)
        q_clarity = self._subindex_clarity(clarity_pct, effective_particles)
        q_temp = self._subindex_temp(temp_c)

        wqi = (
            q_ph * self.weights["ph"] +
            q_turb * self.weights["turbidity"] +
            q_orp * self.weights["orp"] +
            q_tds * self.weights["tds"] +
            q_clarity * self.weights["clarity"] +
            q_temp * self.weights["temp"]
        )
        
        if sheen:
            wqi = min(wqi, 35.0)

        # Penalize WQI proportionally by AI anomaly score if genuine contamination
        if not anomaly_ai_result.get("sensor_drift_fault", False):
            raw_anom = anomaly_ai_result.get("ai_anomaly_score", anomaly_ai_result.get("anomaly_score", 0.0))
            if raw_anom > 0.15:
                ai_penalty = ((raw_anom - 0.15) / 0.85) * 30.0
                wqi = max(5.0, wqi - ai_penalty)

        wqi = round(max(0.0, min(100.0, wqi)), 1)

        # 4. Diagnose specific municipal contamination hazard patterns
        hazards, safety_level, hazard_code, alert_needed = self._diagnose_hazards(
            temp_c, ph, turb_ntu, tds_ppm, orp_mv,
            clarity_pct, delta_e, tint, particulates, sheen, wqi,
            anomaly_ai_result, vision_ai_result, mcu_data
        )

        self.last_hazard_code = hazard_code

        # 5. Status summary
        if safety_level == "CRITICAL":
            status_text = "CRITICAL CONTAMINATION: Urgent LoRaWAN Alert Dispatched"
        elif safety_level == "WARNING":
            status_text = "WARNING: Water Quality Anomaly Detected"
        elif safety_level == "CAUTION":
            status_text = "CAUTION: Sensor Drift or Minor Variance"
        else:
            status_text = "NORMAL: Potable Water Meeting BIS IS 10500 Standards"

        # 6. Generate 3-Pillar Clean Classifications
        classifications = self._build_three_pillar_classifications(
            vision_ai_result, vision_data, mcu_data, safety_level
        )

        return {
            "wqi": wqi,
            "safety_level": safety_level,
            "status_text": status_text,
            "active_hazards": hazards,
            "hazard_code": hazard_code,
            "lorawan_alert_required": alert_needed,
            "classifications": classifications,
            "ai_diagnostics": {
                "anomaly_score": anomaly_ai_result["ai_anomaly_score"],
                "confidence_percent": anomaly_ai_result["ai_confidence_percent"],
                "predicted_threat": anomaly_ai_result["predicted_threat"],
                "early_warning_active": anomaly_ai_result["early_warning_active"],
                "sensor_drift_fault": anomaly_ai_result["sensor_drift_fault"],
                "drift_channel": anomaly_ai_result["drift_channel"],
                "vision_ai_class": vision_ai_result["top_classification"],
                "vision_confidence": vision_ai_result["confidence_percent"],
                "optical_anomaly_score": vision_ai_result["optical_anomaly_score"]
            },
            "sub_indices": {
                "ph": round(q_ph, 1),
                "turbidity": round(q_turb, 1),
                "orp": round(q_orp, 1),
                "tds": round(q_tds, 1),
                "clarity": round(q_clarity, 1),
                "temperature": round(q_temp, 1)
            },
            "sensor_readings": mcu_data,
            "spectral_readings": mcu_data.get("spectral", {}),
            "vision_readings": vision_data
        }

    def _build_three_pillar_classifications(self, vision_ai: Dict[str, Any], vision_data: Dict[str, Any],
                                           mcu_data: Dict[str, Any], safety_level: str) -> Dict[str, Any]:
        """Generates clear, hand-written-style 3-pillar classifications: Camera, Physical Sensors, and AS7341."""
        v_class = vision_ai.get("top_classification", "Clean_Potable")
        v_conf = vision_ai.get("confidence_percent", 95.0)
        clarity = vision_data.get("clarity_percent", 100.0)
        sheen = vision_data.get("surface_sheen_detected", False)
        cam_detected = vision_data.get("camera_detected", True)

        # 1. Camera Classification
        if not cam_detected:
            cam_info = {
                "title": "Not Connected",
                "status": "OFFLINE",
                "confidence": "N/A",
                "summary": "Camera not connected"
            }
        elif v_class == "Clean_Potable":
            cam_info = {
                "title": "Clean Water",
                "status": "SAFE",
                "confidence": f"{v_conf:.1f}%",
                "summary": "Clear water, no visible impurities"
            }
        elif v_class == "Hydrocarbon_Sheen" or sheen:
            cam_info = {
                "title": "Oil Sheen",
                "status": "CRITICAL",
                "confidence": f"{v_conf:.1f}%",
                "summary": "Oil / fuel sheen detected on water surface"
            }
        elif v_class == "Suspended_Sediment":
            cam_info = {
                "title": "Sediment / Murky",
                "status": "WARNING",
                "confidence": f"{v_conf:.1f}%",
                "summary": "Murky water with suspended sediment particles"
            }
        elif v_class == "Algae_Biofilm":
            cam_info = {
                "title": "Algae",
                "status": "WARNING",
                "confidence": f"{v_conf:.1f}%",
                "summary": "Greenish water, possible algae detected"
            }
        else:
            cam_info = {
                "title": v_class.replace("_", " "),
                "status": "WARNING",
                "confidence": f"{v_conf:.1f}%",
                "summary": "Discoloration or visual anomaly detected"
            }

        # 2. Physical Sensor Classification
        turb = float(mcu_data.get("turbidity_ntu", 0.0))
        temp = float(mcu_data.get("temp_c", -127.0))
        temp_dummy = bool(mcu_data.get("temp_dummy", False)) or not bool(mcu_data.get("temp_connected", True)) or temp <= -50.0 or temp == 85.0
        temp_conn = not temp_dummy

        if turb <= 1.0:
            sensor_status = "SAFE"
            sensor_title = "Normal"
            sensor_desc = f"Normal readings. Turbidity {turb:.2f} NTU" + (f", Temp {temp:.1f}°C." if temp_conn else ". (Temp probe not connected).")
        elif turb <= 5.0:
            sensor_status = "CAUTION"
            sensor_title = "Slightly Turbid"
            sensor_desc = f"Turbidity {turb:.2f} NTU slightly elevated" + (f", Temp {temp:.1f}°C." if temp_conn else ". (Temp probe not connected).")
        else:
            sensor_status = "WARNING"
            sensor_title = "High Turbidity"
            sensor_desc = f"Turbidity {turb:.2f} NTU exceeds drinking water threshold."

        sensor_info = {
            "title": sensor_title,
            "status": sensor_status,
            "summary": sensor_desc,
            "turbidity_ntu": turb,
            "temp_c": temp if temp_conn else None,
            "temp_connected": temp_conn
        }

                # 3. AS7341 Multi-Spectral Classification (Relative to NDAI & CDOM Thresholds)
        spec = mcu_data.get("spectral", {})
        spec_detected = bool(spec.get("detected", False)) and any(spec.get(f"f{i}", 0) > 0 for i in range(1, 9))
        if not spec_detected:
            spectral_info = {
                "title": "Not Connected",
                "status": "OFFLINE",
                "badge": "Not Connected",
                "summary": "AS7341 spectrometer not connected or offline.",
                "connected": False
            }
        else:
            raw_ndai = float(spec.get("algae_ndai", 0.0))
            raw_cdom = float(spec.get("cdom_index", 0.0))
            delta_ndai = float(spec.get("delta_ndai", 0.0))
            delta_cdom = float(spec.get("delta_cdom", 0.0))
            base_ndai = float(self.spectral_baseline.get("baseline_ndai", 0.11))
            base_cdom = float(self.spectral_baseline.get("baseline_cdom", 0.75))
            is_calibrated = bool(self.spectral_baseline.get("is_calibrated", False))

            # Thresholds:
            # - Algae NDAI Threshold = 0.60 (Clean baseline ~ 0.11)
            # - CDOM Index Threshold = 0.85 (Clean baseline ~ 0.75 - 0.78)
            ndai_threshold = 0.60
            cdom_threshold = 0.85

            if raw_ndai >= ndai_threshold:
                spec_title = f"NDAI High ({raw_ndai:.2f})"
                spec_status = "CRITICAL"
                spec_desc = f"NDAI High ({raw_ndai:+.2f}) exceeds threshold ({ndai_threshold:.2f}) - Algae / chlorophyll signature detected."
            elif raw_cdom >= cdom_threshold:
                spec_title = f"CDOM High ({raw_cdom:.2f})"
                spec_status = "CRITICAL"
                spec_desc = f"CDOM High ({raw_cdom:+.2f}) exceeds threshold ({cdom_threshold:.2f}) - Dissolved organic matter detected."
            elif raw_ndai >= 0.38:
                spec_title = f"NDAI High ({raw_ndai:.2f})"
                spec_status = "WARNING"
                spec_desc = f"NDAI High ({raw_ndai:+.2f}) is close to threshold ({ndai_threshold:.2f}) - Elevated algae / green signature."
            elif raw_cdom >= 0.81:
                spec_title = f"CDOM High ({raw_cdom:.2f})"
                spec_status = "WARNING"
                spec_desc = f"CDOM High ({raw_cdom:+.2f}) is close to threshold ({cdom_threshold:.2f}) - Elevated organic matter."
            elif raw_ndai >= 0.22:
                spec_title = f"NDAI Medium ({raw_ndai:.2f})"
                spec_status = "WARNING"
                spec_desc = f"NDAI Medium ({raw_ndai:+.2f}) is moderately elevated (Threshold: {ndai_threshold:.2f})."
            elif raw_cdom >= 0.79:
                spec_title = f"CDOM Medium ({raw_cdom:.2f})"
                spec_status = "WARNING"
                spec_desc = f"CDOM Medium ({raw_cdom:+.2f}) is moderately elevated (Threshold: {cdom_threshold:.2f})."
            elif raw_ndai >= 0.16:
                spec_title = f"NDAI Low ({raw_ndai:.2f})"
                spec_status = "SAFE"
                spec_desc = f"NDAI Low ({raw_ndai:+.2f}) is well below threshold ({ndai_threshold:.2f}). Within safe limits."
            else:
                spec_status = "SAFE"
                spec_title = "Clean"
                spec_desc = f"Normal optical spectrum (NDAI: {raw_ndai:+.2f}/{ndai_threshold:.2f}, CDOM: {raw_cdom:+.2f}/{cdom_threshold:.2f}). Clear baseline verified."

            spectral_info = {
                "title": spec_title,
                "status": spec_status,
                "summary": spec_desc,
                "algae_ndai": raw_ndai,
                "cdom_index": raw_cdom,
                "delta_ndai": delta_ndai,
                "delta_cdom": delta_cdom,
                "baseline_ndai": base_ndai,
                "baseline_cdom": base_cdom,
                "is_calibrated": is_calibrated,
                "connected": True
            }


        cam_info["description"] = cam_info["summary"]
        cam_info["badge"] = cam_info["status"]
        cam_info["confidence_pct"] = round(v_conf, 1)

        sensor_info["description"] = sensor_info["summary"]
        sensor_info["badge"] = sensor_info["status"]
        sensor_info["active_probes"] = "Turbidity & Temp Active" if temp_conn else "Turbidity Active (Temp Not Connected)"

        spectral_info["description"] = spectral_info["summary"]
        if "badge" not in spectral_info:
            spectral_info["badge"] = spectral_info["status"]
        if "algae_ndai" in spectral_info:
            spectral_info["ndai"] = spectral_info["algae_ndai"]
            spectral_info["cdom"] = spectral_info["cdom_index"]

        return {
            "camera": cam_info,
            "sensors": sensor_info,
            "as7341": spectral_info
        }


    def _subindex_ph(self, ph: float) -> float:
        if 6.8 <= ph <= 7.8: return 100.0
        elif 6.5 <= ph < 6.8 or 7.8 < ph <= 8.5: return 85.0
        elif 6.0 <= ph < 6.5 or 8.5 < ph <= 9.0: return 50.0
        elif 5.0 <= ph < 6.0 or 9.0 < ph <= 10.0: return 20.0
        else: return 0.0

    def _subindex_turbidity(self, ntu: float) -> float:
        if ntu <= 1.0: return 100.0
        elif ntu <= 2.5: return 85.0
        elif ntu <= 5.0: return 70.0
        elif ntu <= 10.0: return 40.0
        else: return 5.0

    def _subindex_orp(self, orp: float) -> float:
        if orp >= 650.0: return 100.0
        elif orp >= 600.0: return 85.0
        elif orp >= 500.0: return 60.0
        elif orp >= 400.0: return 35.0
        elif orp >= 250.0: return 15.0
        else: return 0.0

    def _subindex_tds(self, tds: float) -> float:
        if tds <= 300.0: return 100.0
        elif tds <= 500.0: return 90.0
        elif tds <= 800.0: return 70.0
        elif tds <= 1200.0: return 40.0
        else: return 5.0

    def _subindex_clarity(self, clarity_pct: float, particle_count: int) -> float:
        score = clarity_pct
        if particle_count > 10:
            score -= (particle_count - 10) * 1.5
        return max(0.0, min(100.0, score))

    def _subindex_temp(self, temp: float) -> float:
        if temp <= -50.0 or temp == 85.0:
            return 100.0  # Neutral subindex if temperature sensor is disconnected
        if 10.0 <= temp <= 32.0: return 100.0
        elif 5.0 <= temp < 10.0 or 32.0 < temp <= 36.0: return 90.0
        elif 36.0 < temp <= 40.0: return 75.0
        else: return 40.0

    def _diagnose_hazards(self, temp, ph, turb, tds, orp, clarity, delta_e, tint, particles, sheen, wqi,
                          anomaly_ai: Dict[str, Any], vision_ai: Dict[str, Any],
                          mcu_data: Optional[Dict[str, Any]] = None
                          ) -> Tuple[List[Dict[str, str]], str, int, bool]:
        hazards = []
        alert_needed = False
        level = "SAFE"
        hazard_code = HAZARD_CODES["NONE"]

        spectral = mcu_data.get("spectral", {}) if mcu_data else {}
        algae_ndai = float(spectral.get("algae_ndai", 0.0))
        cdom_index = float(spectral.get("cdom_index", 0.0))

        # Check for Sensor Drift / Biofouling False Positive Rejection
        if anomaly_ai.get("sensor_drift_fault", False):
            ch = anomaly_ai.get("drift_channel", "UNKNOWN").upper()
            hazards.append({
                "code": "DIAGNOSTIC_PROBE_DRIFT",
                "severity": "CAUTION",
                "message": f"AI Diagnostic: Sensor probe drift/scaling detected on {ch}. Water optics & other probes normal.",
                "action": "Schedule probe cleaning & recalibration. No public alarm needed."
            })
            level = "CAUTION"
            return hazards, level, hazard_code, False

        # 1. Industrial Chemical Spills
        if ph < 6.0:
            hazards.append({
                "code": "HAZARD_ACID_CONTAMINATION",
                "severity": "CRITICAL",
                "message": f"Severe Acidic Influx (pH {ph:.2f}). Pipe leaching & toxic risk.",
                "action": "LoRaWAN Critical Alert -> Municipal Water Authority"
            })
            alert_needed = True
            level = "CRITICAL"
            hazard_code = HAZARD_CODES["ACID_CONTAMINATION"]
        elif ph > 9.0:
            hazards.append({
                "code": "HAZARD_CAUSTIC_ALKALINE",
                "severity": "CRITICAL",
                "message": f"Severe Alkaline/Caustic Spurt (pH {ph:.2f}). Chemical spill suspected.",
                "action": "LoRaWAN Critical Alert -> Environmental Protection"
            })
            alert_needed = True
            level = "CRITICAL"
            hazard_code = HAZARD_CODES["CAUSTIC_ALKALINE"]

        # 2. Organic / Sewage Contamination (incorporating AS7341 CDOM Index)
        is_sewage_conditions = (orp < 350.0 and (turb > 4.0 or particles > 20 or delta_e > 10.0 or vision_ai.get("top_classification") == "Suspended_Sediment"))
        is_cdom_sewage = (cdom_index > 0.40 and (orp < 450.0 or turb > 3.0))
        if is_sewage_conditions or is_cdom_sewage:
            hazards.append({
                "code": "HAZARD_SEWAGE_INGRESS",
                "severity": "CRITICAL",
                "message": f"Biological Sewage Ingress (ORP {orp:.0f}mV, Turbidity {turb:.1f}NTU, CDOM {cdom_index:.2f}). High pathogen risk.",
                "action": "LoRaWAN Urgent Alert -> Water Treatment Plant Operator"
            })
            alert_needed = True
            level = "CRITICAL"
            hazard_code = HAZARD_CODES["SEWAGE_INGRESS"]

        # 3. Disinfection Breakdown / Chlorine Depletion
        elif orp < 580.0 and turb <= 3.0:
            hazards.append({
                "code": "HAZARD_DISINFECTION_LOSS",
                "severity": "WARNING",
                "message": f"Disinfection residual lost (ORP {orp:.0f}mV < 650mV min). Microbial risk.",
                "action": "LoRaWAN Warning -> Treatment Dosing Controller"
            })
            if level != "CRITICAL":
                level = "WARNING"
                hazard_code = HAZARD_CODES["DISINFECTION_LOSS"]
                alert_needed = True


        # 4. Pipe Burst / Physical Sediment Ingress
        if (turb > 8.0 or particles > 40) and level != "CRITICAL":
            hazards.append({
                "code": "HAZARD_SEDIMENT_PIPE_BURST",
                "severity": "WARNING",
                "message": f"Turbidity / Sediment Spike ({turb:.1f} NTU, {particles} particles). Pipe scour or burst.",
                "action": "LoRaWAN Warning -> Distribution Network Maintenance"
            })
            if level != "CRITICAL":
                level = "WARNING"
                hazard_code = HAZARD_CODES["SEDIMENT_PIPE_BURST"]
                alert_needed = True

        # 5. Petroleum / Hydrocarbon Oil Slicks
        if sheen or vision_ai.get("top_classification") == "Hydrocarbon_Sheen":
            hazards.append({
                "code": "HAZARD_HYDROCARBON_SHEEN",
                "severity": "CRITICAL",
                "message": "Surface hydrocarbon film detected by optical camera & Vision AI.",
                "action": "LoRaWAN Critical Alert -> Surface Runoff Containment"
            })
            alert_needed = True
            level = "CRITICAL"
            hazard_code = HAZARD_CODES["HYDROCARBON_SHEEN"]

        # 6. Algal Bloom / Micro-algae Proliferation (AS7341 Multi-Spectral NDAI)
        delta_ndai = float(spectral.get("delta_ndai", 0.0)) if "delta_ndai" in spectral else (algae_ndai - float(self.spectral_baseline.get("baseline_ndai", 0.48)))
        is_spec_calib = bool(self.spectral_baseline.get("is_calibrated", False))

        if algae_ndai <= 0.15:
            spectral_algae = False
        elif is_spec_calib:
            spectral_algae = (delta_ndai >= 0.12)
        else:
            spectral_algae = (algae_ndai >= 0.60) or (delta_ndai >= 0.12)

        # Multi-sensor corroboration:
        # A genuine biological algal bloom cannot exist without physical water effects:
        # turbidity >= 1.5 NTU, or particulates >= 6, or Vision AI classifies Algae_Biofilm,
        # or negative a* color shift (green tint), or extreme spectral delta (>= 0.30)
        has_physical_algae_evidence = (
            turb >= 1.5 or
            particles >= 6 or
            vision_ai.get("top_classification") == "Algae_Biofilm" or
            tint == "Algae / Organic Tint" or
            delta_ndai >= 0.30 or
            algae_ndai >= 0.70
        )

        # Pristine clean water protection: clear water never triggers algae bloom alert
        is_pristine_water = (turb <= 1.0 and clarity >= 90.0 and delta_e <= 3.5 and vision_ai.get("top_classification") == "Clean_Potable")

        if spectral_algae and has_physical_algae_evidence and not (is_pristine_water and delta_ndai < 0.25):
            sev = "CRITICAL" if (delta_ndai >= 0.30 or turb >= 5.0 or algae_ndai >= 0.70) else "WARNING"
            hazards.append({
                "code": "HAZARD_ALGAL_BLOOM",
                "severity": sev,
                "message": f"AS7341 Multi-Spectral Algal Bloom Detection (NDAI: +{algae_ndai:.2f}, Δ:{delta_ndai:+.2f}). High cyanobacteria / chlorophyll-a risk.",
                "action": "LoRaWAN Alert -> Chlorination dosing & intake filtration"
            })
            alert_needed = True
            level = "CRITICAL" if sev == "CRITICAL" else level
            if level != "CRITICAL":
                level = sev
            hazard_code = HAZARD_CODES["ALGAL_BLOOM"]



        # 7. Chemical Dye / Industrial Effluent (AS7341 Spectral Fingerprinting)
        f7 = spectral.get("f7", 0)
        f8 = spectral.get("f8", 0)
        f5 = spectral.get("f5", 0)
        if (f7 > 2500 or f8 > 2800) and f5 < 1200 and turb < 3.0:
            hazards.append({
                "code": "HAZARD_CHEMICAL_DYE",
                "severity": "CRITICAL",
                "message": "AS7341 Optical Spectral Fingerprint indicates industrial textile/chemical dye discharge.",
                "action": "LoRaWAN Critical Alert -> Pollution Control Board"
            })
            alert_needed = True
            level = "CRITICAL"
            hazard_code = HAZARD_CODES["CHEMICAL_DYE"]

        # 8. AI Early Predictive Warning (Correlated multi-parameter degradation)
        if anomaly_ai.get("early_warning_active", False) and level == "SAFE":
            hazards.append({
                "code": "AI_PREDICTIVE_WARNING",
                "severity": "WARNING",
                "message": f"Edge AI detected correlated multi-parameter deviation (Threat: {anomaly_ai['predicted_threat']}).",
                "action": "Dispatch early maintenance check before thresholds fail."
            })
            level = "WARNING"
            hazard_code = HAZARD_CODES["AI_PREDICTIVE_ANOMALY"]
            alert_needed = True

        # 9. AI Critical Anomaly Trigger
        elif anomaly_ai.get("critical_alert_active", False) and level != "CRITICAL":
            anom_val = anomaly_ai.get("ai_anomaly_score", anomaly_ai.get("anomaly_score", 0.0))
            hazards.append({
                "code": "AI_CRITICAL_ANOMALY",
                "severity": "CRITICAL",
                "message": f"Edge AI Anomaly Score {anom_val * 100:.1f}% indicates severe contamination pattern.",
                "action": "Immediate emergency verification & transmission."
            })
            level = "CRITICAL"
            hazard_code = HAZARD_CODES["AI_PREDICTIVE_ANOMALY"]
            alert_needed = True

        # 10. High Dissolved Solids
        if tds > 1000.0 and level == "SAFE":
            hazards.append({
                "code": "HAZARD_HIGH_SALINITY_TDS",
                "severity": "CAUTION",
                "message": f"High Total Dissolved Solids ({tds:.0f} ppm).",
                "action": "Log in routine telemetry uplink."
            })
            level = "CAUTION"
            hazard_code = HAZARD_CODES["HIGH_SALINITY_TDS"]

        return hazards, level, hazard_code, alert_needed



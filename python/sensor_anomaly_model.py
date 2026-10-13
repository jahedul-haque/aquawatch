"""
Multi-Modal Edge ML Anomaly Detection Model for AquaGuard
Fuses 5 physical-chemical sensor telemetry channels with optical vision metrics
to perform multi-variate predictive contamination detection and sensor fault diagnosis.
"""

import numpy as np
from typing import Dict, Any, Tuple, Optional

class SensorAnomalyModel:
    FEATURE_NAMES = [
        "temperature_c",
        "ph",
        "turbidity_ntu",
        "tds_ppm",
        "orp_mv",
        "clarity_percent",
        "particulate_count",
        "optical_anomaly_score",
        "algae_ndai",
        "cdom_index"
    ]

    def __init__(self):
        # Municipal Potable Baseline Distribution (Mean vector µ)
        self.mu = np.array([
            24.0,    # Temp (°C) - adapted for tropical/ambient drinking water (18-32°C nominal)
            7.35,    # pH
            0.40,    # Turbidity (NTU)
            180.0,   # TDS (ppm)
            680.0,   # ORP (mV)
            95.0,    # Clarity (%)
            2.0,     # Particulates
            0.08,    # Optical Anomaly Score
            0.02,    # AS7341 Algae NDAI
            0.04     # AS7341 CDOM Index
        ], dtype=np.float32)

        # Baseline Standard Deviations (Sigma vector σ)
        self.sigma = np.array([
            6.0,     # Temp (°C)
            0.35,    # pH
            0.50,    # Turbidity
            50.0,    # TDS
            40.0,    # ORP
            5.0,     # Clarity
            3.0,     # Particulates
            0.08,    # Optical Anomaly Score
            0.06,    # AS7341 Algae NDAI
            0.07     # AS7341 CDOM Index
        ], dtype=np.float32)

        # Feature Weights for Contamination Sensitivity (sum = 1.0)
        self.weights_with_spectral = np.array([
            0.05,    # Temp
            0.15,    # pH
            0.15,    # Turbidity
            0.10,    # TDS
            0.15,    # ORP
            0.10,    # Clarity
            0.05,    # Particulates
            0.05,    # Optical Anomaly
            0.10,    # Algae NDAI
            0.10     # CDOM Index
        ], dtype=np.float32)

        self.weights_legacy = np.array([
            0.05,    # Temp
            0.20,    # pH
            0.20,    # Turbidity
            0.15,    # TDS
            0.20,    # ORP
            0.10,    # Clarity
            0.05,    # Particulates
            0.05,    # Optical Anomaly
            0.00,    # Algae NDAI (inactive in legacy mode)
            0.00     # CDOM Index (inactive in legacy mode)
        ], dtype=np.float32)

        self.weights = self.weights_with_spectral

    def extract_vector(self, mcu_data: Dict[str, Any], vision_data: Dict[str, Any], vision_ai: Dict[str, Any]) -> np.ndarray:
        spectral = mcu_data.get("spectral", {})
        temp_raw = float(mcu_data.get("temp_c", 18.0))
        # DS18B20 disconnected signal (-127.0C) or unconverted power-on (85.0C)
        temp_val = float(self.mu[0]) if (temp_raw <= -50.0 or temp_raw == 85.0) else temp_raw

        cam_active = bool(vision_data.get("camera_detected", True))
        clarity_val = float(vision_data.get("clarity_percent", 95.0)) if cam_active else float(self.mu[5])
        particle_val = float(vision_data.get("particulate_count", 2)) if cam_active else float(self.mu[6])
        opt_anomaly_val = float(vision_ai.get("optical_anomaly_score", 0.08)) if cam_active else 0.0

        if "delta_ndai" in spectral:
            ndai_feature = max(0.0, float(spectral.get("delta_ndai", 0.0)))
        else:
            raw_ndai = float(spectral.get("algae_ndai", 0.02))
            ndai_feature = max(0.0, raw_ndai - 0.48) if raw_ndai > 0.30 else max(0.0, raw_ndai)

        if "delta_cdom" in spectral:
            cdom_feature = max(0.0, float(spectral.get("delta_cdom", 0.0)))
        else:
            raw_cdom = float(spectral.get("cdom_index", 0.04))
            cdom_feature = max(0.0, raw_cdom - 0.42) if raw_cdom > 0.30 else max(0.0, raw_cdom)

        return np.array([
            temp_val,
            float(mcu_data.get("ph", 7.35)),
            float(mcu_data.get("turbidity_ntu", 0.40)),
            float(mcu_data.get("tds_ppm", 180.0)),
            float(mcu_data.get("orp_mv", 680.0)),
            clarity_val,
            particle_val,
            opt_anomaly_val,
            ndai_feature,
            cdom_feature
        ], dtype=np.float32)

    def predict(self, mcu_data: Dict[str, Any], vision_data: Dict[str, Any], vision_ai: Dict[str, Any]) -> Dict[str, Any]:

        x = self.extract_vector(mcu_data, vision_data, vision_ai)
        temp, ph, turb, tds, orp, clarity, particles, opt_anomaly, algae_ndai, cdom_index = x
        
        # 1. Normalized Z-scores
        z_scores = (x - self.mu) / self.sigma
        
        # One-sided penalty adaptation: features where lower/higher is strictly cleaner
        # (e.g. ultra-clear water, 0 NTU, or negative/zero CDOM/NDAI is pure water, not an anomaly)
        z_effective = z_scores.copy()
        if turb < self.mu[2]: z_effective[2] = 0.0 # Turbidity cleaner than baseline
        if clarity > self.mu[5]: z_effective[5] = 0.0 # Clarity clearer than baseline
        if particles < self.mu[6]: z_effective[6] = 0.0 # Fewer particles than baseline
        if opt_anomaly < self.mu[7]: z_effective[7] = 0.0 # Lower optical anomaly
        if algae_ndai <= 0.0: z_effective[8] = 0.0 # No algal chlorophyll
        if cdom_index <= 0.0: z_effective[9] = 0.0 # No dissolved organic matter

        # Corroborate camera particulates and clarity with physical turbidity:
        # If physical photoelectric turbidity confirms clear water (turb <= 0.5 NTU)
        # and Vision AI confirms Clean_Potable texture, camera edge reflections or smooth background
        # are not a contamination anomaly
        if turb <= 0.5 and (vision_ai.get("top_classification") == "Clean_Potable"):
            z_effective[5] = 0.0  # Zero out clarity penalty
            z_effective[6] = min(z_effective[6], 0.5)  # Cap particulate penalty
            z_effective[7] = 0.0  # Zero out optical anomaly penalty

        abs_z = np.abs(z_effective)

        # 2. Weighted Distance
        active_weights = self.weights_with_spectral if ("spectral" in mcu_data) else self.weights_legacy
        weighted_sq_dist = np.sum(active_weights * (z_effective ** 2))
        dist = float(np.sqrt(weighted_sq_dist))

        # 3. Continuous AI Anomaly Score (0.0 to 1.0)
        anomaly_score = float(1.0 / (1.0 + np.exp(-1.5 * (dist - 2.0))))
        anomaly_score = max(0.0, min(1.0, anomaly_score))

        # 4. Sensor Drift vs True Contamination Discrimination
        # Disinfection depletion (400 <= ORP <= 580 mV) is a REAL water hazard, NOT probe drift!
        is_disinfection_loss = (400.0 <= orp <= 580.0 and turb <= 2.0)
        
        anomalous_channels = [self.FEATURE_NAMES[i] for i in range(len(self.FEATURE_NAMES)) if abs_z[i] > 3.0]
        num_anomalous = len(anomalous_channels)

        sensor_drift_detected = False
        drift_channel = None

        # Physical sensor probes subject to fouling/scaling
        PROBE_CHANNELS = ["ph", "orp_mv", "turbidity_ntu", "tds_ppm", "temperature_c"]
        if num_anomalous == 1 and not is_disinfection_loss and (anomalous_channels[0] in PROBE_CHANNELS):
            drift_channel = anomalous_channels[0]
            other_z = [abs_z[i] for i in range(len(abs_z)) if self.FEATURE_NAMES[i] != drift_channel]
            # Single probe is severely off, but all other features are normal
            if max(other_z) < 2.0:
                sensor_drift_detected = True
                anomaly_score = min(anomaly_score, 0.35)

        # 5. Threat classification
        threat_type = self._classify_threat(x, abs_z, vision_ai, sensor_drift_detected, drift_channel, is_disinfection_loss, mcu_data)

        # 6. Confidence score
        confidence = float(min(99.0, max(50.0, 50.0 + (abs(anomaly_score - 0.5) * 98.0))))

        early_warning = (anomaly_score >= 0.55 and anomaly_score < 0.75 and not sensor_drift_detected)
        critical_alert = (anomaly_score >= 0.75 and not sensor_drift_detected)

        return {
            "ai_anomaly_score": round(anomaly_score, 3),
            "anomaly_score": round(anomaly_score, 3),
            "ai_confidence_percent": round(confidence, 1),
            "predicted_threat": threat_type,
            "early_warning_active": early_warning,
            "critical_alert_active": critical_alert,
            "sensor_drift_fault": sensor_drift_detected,
            "drift_channel": drift_channel,
            "anomalous_channels": anomalous_channels,
            "z_scores": {self.FEATURE_NAMES[i]: round(float(z_scores[i]), 2) for i in range(len(self.FEATURE_NAMES))}
        }


    def _classify_threat(self, x: np.ndarray, z: np.ndarray, vision_ai: Dict[str, Any],
                         is_drift: bool, drift_ch: str, is_disinfection_loss: bool,
                         mcu_data: Optional[Dict[str, Any]] = None) -> str:
        if is_drift:
            return f"SENSOR_FAULT_DRIFT ({drift_ch.upper()})"

        temp, ph, turb, tds, orp, clarity, particles, opt_anomaly, algae_ndai, cdom_index = x
        v_class = vision_ai.get("top_classification", "Clean_Potable")

        # Algal Bloom (High Green reflection F5, Red absorption F8 above clean baseline)
        if algae_ndai > 0.18:
            return "ALGAL_BLOOM_EUTROPHICATION"


        # Organic CDOM Sewage Runoff (High UV/Violet absorption F1)
        if cdom_index > 0.40 and (orp < 500.0 or turb > 2.5):
            return "ORGANIC_CDOM_SEWAGE_INGRESS"

        # Disinfection Loss
        if is_disinfection_loss:
            return "CHLORINATION_DISINFECTION_LOSS"

        # Hydrocarbon / Oil Sheen
        if v_class == "Hydrocarbon_Sheen" or (opt_anomaly > 0.70 and turb < 3.0):
            return "PETROLEUM_HYDROCARBON_SHEEN"

        # Sewage Ingress
        if orp < 400.0 and (turb > 3.0 or particles > 15):
            return "BIOLOGICAL_SEWAGE_CONTAMINATION"

        # Acid Spill
        if ph < 6.2:
            return "INDUSTRIAL_ACID_INFLUX"

        # Alkaline Spill
        if ph > 8.8:
            return "CAUSTIC_ALKALINE_SPILL"

        # Sediment / Pipe Scour
        if turb > 5.0 or particles > 25 or v_class == "Suspended_Sediment":
            return "SUSPENDED_SEDIMENT_PIPE_BURST"

        # Chemical Dye / Industrial Effluent
        if mcu_data:
            spec = mcu_data.get("spectral", {})
            f7 = spec.get("f7", 0)
            f8 = spec.get("f8", 0)
            f5 = spec.get("f5", 0)
            if (f7 > 2500 or f8 > 2800) and f5 < 1200 and turb < 3.0:
                return "INDUSTRIAL_CHEMICAL_DYE"

        # Correlated multi-parameter degradation (requires 2 or more parameters showing anomalous shift)
        num_elevated = sum(1 for zi in [abs(z[1]), abs(z[2]), abs(z[3]), abs(z[4]), abs(z[8]), abs(z[9])] if zi > 1.5)
        if num_elevated >= 2:
            return "CORRELATED_WATER_DEGRADATION"

        return "CLEAN_POTABLE_WATER"


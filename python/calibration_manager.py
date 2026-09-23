"""
Calibration and One-Shot Exemplar Prototype Manager for AquaWatch
Qualcomm QRB2210 (Debian Linux)

Enables users to calibrate the optical and sensor baseline using real water samples
(e.g., teaching the system what their local clean tap water looks like, or training
on specific local contamination samples using One-Shot Prototype Learning).
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger("CalibrationManager")

class CalibrationManager:
    DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "calibration_profiles.json")

    CATEGORIES = {
        "Clean_Potable": "Clean Potable Water (Baseline Zero)",
        "Suspended_Sediment": "High Turbidity / Muddy Water",
        "Algae_Biofilm": "Algae / Green Water",
        "Chemical_Discoloration": "Chemical / Discolored Water",
        "Hydrocarbon_Sheen": "Oil / Surface Sheen"
    }

    # Factory baseline reference in CIE-Lab color space and sharpness
    FACTORY_CLEAN_LAB = [183.0, 128.0, 128.0]
    FACTORY_CLEAN_VAR = 750.0

    # Factory baseline reference for AS7341 under white LED in clear potable water
    # White LED phosphor produces ~2.8x more 555nm than 680nm (NDAI ~ +0.48) and ~4.6x more 590nm than 415nm (CDOM ~ +0.64)
    FACTORY_SPECTRAL_BASELINE = {
        "baseline_ndai": 0.48,
        "baseline_cdom": 0.64,
        "f5_ref": 1200.0,
        "f8_ref": 420.0,
        "f6_ref": 1100.0,
        "f1_ref": 240.0,
        "f5_f8_ratio": 2.85,
        "f6_f1_ratio": 4.58,
        "is_calibrated": False
    }

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.profiles: Dict[str, Any] = {}
        self.load()

    def load(self):
        """Loads persistent calibration profiles from JSON file if available."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.profiles = json.load(f)
                logger.info(f"Loaded {len(self.profiles)} calibration profiles from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load calibration profiles: {e}")
                self.profiles = {}
        else:
            self.profiles = {}

    def save(self):
        """Persists current calibration profiles to disk."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.profiles, f, indent=2)
            logger.info(f"Saved {len(self.profiles)} calibration profiles to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save calibration profiles: {e}")

    def learn_sample(self, category: str, visual_features: List[float],
                     mcu_data: Dict[str, Any], vision_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stores the current sample as a one-shot exemplar prototype for the selected category.
        If category is Clean_Potable, also recalibrates the baseline color (L*a*b*),
        sharpness variance, and AS7341 spectral baseline so clean water reads as 100% clarity,
        0 delta-E, and 0 delta-NDAI.
        """
        if category not in self.CATEGORIES:
            raise ValueError(f"Unknown category '{category}'. Supported: {list(self.CATEGORIES.keys())}")

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        spec = mcu_data.get("spectral", {})
        turb = float(mcu_data.get("turbidity_ntu", 0.0))

        f1 = float(spec.get("f1", 0))
        f2 = float(spec.get("f2", 0))
        f3 = float(spec.get("f3", 0))
        f4 = float(spec.get("f4", 0))
        f5 = float(spec.get("f5", 0))
        f6 = float(spec.get("f6", 0))
        f7 = float(spec.get("f7", 0))
        f8 = float(spec.get("f8", 0))
        clr = float(spec.get("clear", 0))
        nir = float(spec.get("nir", 0))

        raw_ndai = float(spec.get("algae_ndai", 0.0))
        if raw_ndai == 0.0 and (f5 + f8) > 10.0:
            raw_ndai = (f5 - f8) / (f5 + f8)
        raw_cdom = float(spec.get("cdom_index", 0.0))
        if raw_cdom == 0.0 and (f6 + f1) > 10.0:
            raw_cdom = (f6 - f1) / (f6 + f1)

        profile = {
            "category": category,
            "label": self.CATEGORIES[category],
            "timestamp": timestamp,
            "visual_features": [round(float(x), 2) for x in visual_features],
            "turbidity_ntu": round(turb, 2),
            "clarity_percent": round(float(vision_metrics.get("clarity_percent", 100.0)), 1),
            "laplacian_variance": round(float(vision_metrics.get("laplacian_variance", self.FACTORY_CLEAN_VAR)), 2),
            "discoloration_delta_e": round(float(vision_metrics.get("discoloration_delta_e", 0.0)), 2),
            "spectral": {
                "f1": int(f1),
                "f2": int(f2),
                "f3": int(f3),
                "f4": int(f4),
                "f5": int(f5),
                "f6": int(f6),
                "f7": int(f7),
                "f8": int(f8),
                "clear": int(clr),
                "nir": int(nir),
                "algae_ndai": round(raw_ndai, 3),
                "cdom_index": round(raw_cdom, 3),
                "baseline_ndai": round(raw_ndai, 3),
                "baseline_cdom": round(raw_cdom, 3),
                "f5_f8_ratio": round(f5 / max(1.0, f8), 3) if f8 > 0 else 2.85,
                "f6_f1_ratio": round(f6 / max(1.0, f1), 3) if f1 > 0 else 2.45
            }
        }

        self.profiles[category] = profile
        self.save()
        logger.info(f"One-shot learned exemplar prototype for '{category}' at {timestamp}")
        return profile

    def reset_factory(self):
        """Clears all user calibration profiles and restores factory baseline."""
        self.profiles = {}
        if os.path.exists(self.config_path):
            try:
                os.remove(self.config_path)
            except Exception as e:
                logger.error(f"Error removing {self.config_path}: {e}")
        logger.info("Calibration profiles reset to factory defaults.")

    def get_clean_baseline(self) -> Optional[Dict[str, Any]]:
        """Returns the learned Clean_Potable profile if present."""
        return self.profiles.get("Clean_Potable")

    def get_spectral_baseline(self) -> Dict[str, Any]:
        """Returns the clean water spectral baseline for AS7341 (either calibrated or factory default)."""
        clean = self.get_clean_baseline()
        if clean and "spectral" in clean:
            s = clean["spectral"]
            f5 = float(s.get("f5", 0))
            f8 = float(s.get("f8", 0))
            f6 = float(s.get("f6", 0))
            f1 = float(s.get("f1", 0))
            raw_ndai = float(s.get("algae_ndai", 0.0))
            raw_cdom = float(s.get("cdom_index", 0.0))
            
            # If sensor recorded readings during clean calibration
            if f5 > 0 or f8 > 0 or abs(raw_ndai) > 0.001:
                return {
                    "baseline_ndai": round(raw_ndai, 3),
                    "baseline_cdom": round(raw_cdom, 3),
                    "f5_ref": max(1.0, f5),
                    "f8_ref": max(1.0, f8),
                    "f6_ref": max(1.0, f6),
                    "f1_ref": max(1.0, f1),
                    "f5_f8_ratio": round(f5 / max(1.0, f8), 3) if f8 > 0 else 2.85,
                    "f6_f1_ratio": round(f6 / max(1.0, f1), 3) if f1 > 0 else 2.45,
                    "timestamp": clean.get("timestamp", ""),
                    "is_calibrated": True
                }
        
        return dict(self.FACTORY_SPECTRAL_BASELINE)

    def get_prototype_vectors(self) -> Dict[str, List[float]]:
        """Returns visual feature prototype vectors for all calibrated categories."""
        return {
            cat: prof["visual_features"]
            for cat, prof in self.profiles.items()
            if "visual_features" in prof and len(prof["visual_features"]) == 6
        }

    def get_summary(self) -> Dict[str, Any]:
        """Provides status summary for web dashboard and diagnostics."""
        clean = self.get_clean_baseline()
        is_clean_calibrated = clean is not None
        spec_base = self.get_spectral_baseline()
        
        status_label = "Factory Default"
        if is_clean_calibrated:
            status_label = f"Calibrated Clean ({clean.get('timestamp', '')})"
        elif len(self.profiles) > 0:
            status_label = f"{len(self.profiles)} Profiles Learned"

        return {
            "is_calibrated": len(self.profiles) > 0,
            "status_label": status_label,
            "clean_calibrated": is_clean_calibrated,
            "spectral_calibrated": spec_base.get("is_calibrated", False),
            "spectral_baseline": spec_base,
            "learned_categories": list(self.profiles.keys()),
            "profiles_count": len(self.profiles),
            "categories": list(self.CATEGORIES.keys()),
            "categories_labels": self.CATEGORIES,
            "profiles": {
                cat: {
                    "label": prof.get("label"),
                    "timestamp": prof.get("timestamp"),
                    "clarity": prof.get("clarity_percent"),
                    "turbidity": prof.get("turbidity_ntu")
                }
                for cat, prof in self.profiles.items()
            }
        }


"""
Edge Vision AI Classifier for Qualcomm QRB2210 (Debian Linux)
Performs on-device visual water contamination classification and anomaly scoring
on flow-cell camera frames.

Classifies into 5 contamination categories:
1. Clean_Potable
2. Suspended_Sediment
3. Algae_Biofilm
4. Chemical_Discoloration
5. Hydrocarbon_Sheen
"""

import cv2
import numpy as np
from typing import Dict, Any, Tuple

class VisionAIClassifier:
    CLASSES = [
        "Clean_Potable",
        "Suspended_Sediment",
        "Algae_Biofilm",
        "Chemical_Discoloration",
        "Hydrocarbon_Sheen"
    ]

    def __init__(self):
        # Baseline reference parameters for pure flow-cell chamber
        # [Mean L*, Mean a*, Mean b*, Spatial Gradient Var, High-Freq Energy, Sheen Sat Spread]
        self.clean_baseline = np.array([183.0, 128.0, 128.0, 750.0, 30.0, 0.0], dtype=np.float32)
        
        # One-shot exemplar prototypes {category_name: np.ndarray(6)}
        self.prototypes: Dict[str, np.ndarray] = {}
        
        # Per-feature standard deviation scales for normalized distance
        self.feature_sigmas = np.array([25.0, 10.0, 10.0, 350.0, 15.0, 30.0], dtype=np.float32)
        self.feature_weights = np.array([0.15, 0.25, 0.25, 0.20, 0.05, 0.10], dtype=np.float32)

    def set_clean_baseline(self, baseline: list):
        """Sets the calibrated clean water baseline features."""
        if len(baseline) >= 3:
            self.clean_baseline[0] = float(baseline[0])
            self.clean_baseline[1] = float(baseline[1])
            self.clean_baseline[2] = float(baseline[2])
        if len(baseline) >= 4:
            self.clean_baseline[3] = max(1.0, float(baseline[3]))

    def set_prototypes(self, prototypes: Dict[str, list]):
        """Sets calibrated one-shot exemplar prototype vectors."""
        self.prototypes = {
            k: np.array(v, dtype=np.float32)
            for k, v in prototypes.items()
            if len(v) == 6
        }
        if "Clean_Potable" in self.prototypes:
            self.set_clean_baseline(self.prototypes["Clean_Potable"].tolist())

    def reset_prototypes(self):
        """Resets all learned prototypes back to factory defaults."""
        self.prototypes = {}
        self.clean_baseline = np.array([183.0, 128.0, 128.0, 750.0, 30.0, 0.0], dtype=np.float32)

    def extract_visual_features(self, frame: np.ndarray) -> np.ndarray:
        """
        Extracts a compact 6-dimensional perceptual feature vector from the water frame.
        """
        h, w = frame.shape[:2]
        
        bulk_roi = frame[int(0.20 * h):int(0.85 * h), int(0.15 * w):int(0.85 * w)]
        surface_roi = frame[int(0.05 * h):int(0.22 * h), int(0.15 * w):int(0.85 * w)]

        # 1. Color Representation in CIE-Lab
        lab = cv2.cvtColor(bulk_roi, cv2.COLOR_BGR2LAB)
        mean_l, mean_a, mean_b = np.mean(lab, axis=(0, 1))

        # 2. Spatial Gradient Energy (Edge clarity through water)
        gray = cv2.cvtColor(bulk_roi, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_32F)
        grad_var = float(laplacian.var())

        # 3. High-Frequency Suspended Particulate Energy
        blur = cv2.GaussianBlur(gray, (15, 15), 0)
        high_pass = cv2.absdiff(gray, blur)
        particulate_energy = float(np.mean(high_pass))

        # 4. Surface Meniscus Thin-Film Chromatic Dispersion (Sheen)
        hsv_surf = cv2.cvtColor(surface_roi, cv2.COLOR_BGR2HSV)
        sat_spread = float(np.std(hsv_surf[:, :, 1])) + (float(np.mean(hsv_surf[:, :, 1])) * 0.5)

        return np.array([mean_l, mean_a, mean_b, grad_var, particulate_energy, sat_spread], dtype=np.float32)

    def classify(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Runs visual classification and anomaly scoring on the input water frame,
        blending baseline physical rules with one-shot calibrated exemplar prototypes.
        """
        features = self.extract_visual_features(frame)
        l, a, b, gvar, part, sheen = features

        ref_l, ref_a, ref_b, ref_gvar, ref_part, ref_sheen = self.clean_baseline
        delta_color = float(np.sqrt((a - ref_a)**2 + (b - ref_b)**2))

        # 1. Chemical Discoloration (Rust, industrial dyes, iron)
        chem_score = (delta_color / 4.0) if delta_color > 15.0 else 0.0

        # 2. Algae (Negative a* shift towards green relative to clean baseline)
        algae_shift_a = max(0.0, ((ref_a - 6.0) - a) / 3.0)
        algae_shift_b = max(0.0, (b - (ref_b + 4.0)) / 4.0)
        algae_score = algae_shift_a + algae_shift_b

        # 3. Hydrocarbon Sheen (Surface chromatic saturation, bulk water neutral)
        sheen_score = max(0.0, (sheen - 120.0) / 5.0) if (sheen > 125.0 and delta_color < 15.0) else 0.0

        # 4. Suspended Sediment (Blurred grid lines, low color delta)
        if ref_gvar >= 100.0:
            sediment_thresh = max(200.0, ref_gvar * 0.70)
            sediment_score = max(0.0, (sediment_thresh - gvar) / 75.0) if delta_color < 15.0 else 0.0
            gvar_too_low = gvar < (ref_gvar * 0.35)
        else:
            # Smooth unpatterned background: clean water naturally has low gvar
            sediment_score = 0.0
            gvar_too_low = False

        # 5. Clean Potable (Sharp grid lines or clear smooth water, neutral color relative to baseline, no surface sheen)
        if sheen > 125.0 or delta_color > 15.0 or gvar_too_low:
            clean_score = 0.0
        else:
            if ref_gvar >= 100.0:
                gvar_ratio = min(1.0, gvar / max(100.0, ref_gvar))
            else:
                rel_diff = abs(gvar - ref_gvar) / max(1.0, ref_gvar)
                gvar_ratio = max(0.0, 1.0 - (rel_diff * 0.2))
            clean_score = 6.0 + (gvar_ratio * 4.0)

        raw_scores = [clean_score, sediment_score, algae_score, chem_score, sheen_score]

        # 6. One-Shot Prototype Exemplar Similarity Boost
        nearest_cat = None
        min_proto_dist = 999.0
        one_shot_active = len(self.prototypes) > 0

        for idx, cat_name in enumerate(self.CLASSES):
            if cat_name in self.prototypes:
                proto = self.prototypes[cat_name]
                # Normalized weighted Euclidean distance in perceptual feature space
                diff_norm = (features - proto) / self.feature_sigmas
                dist = float(np.sqrt(np.sum(self.feature_weights * (diff_norm ** 2))))
                if dist < min_proto_dist:
                    min_proto_dist = dist
                    nearest_cat = cat_name
                # Exponential radial basis similarity boost
                boost = 8.0 * float(np.exp(-dist / 1.5))
                raw_scores[idx] += boost

        logits = np.array(raw_scores, dtype=np.float32)

        # Softmax probability distribution
        exp_logits = np.exp(logits - np.max(logits))
        probabilities = exp_logits / np.sum(exp_logits)

        best_idx = int(np.argmax(probabilities))
        top_class = self.CLASSES[best_idx]
        confidence = float(probabilities[best_idx])

        # Optical Anomaly Score (0.0 to 1.0)
        if top_class == "Clean_Potable":
            anomaly_score = max(0.02, min(0.25, 0.05 + (1.0 - (gvar / max(500.0, ref_gvar * 2.0))) * 0.15))
        else:
            anomaly_score = max(0.65, min(0.99, 0.65 + (confidence * 0.34)))

        return {
            "top_classification": top_class,
            "confidence_percent": round(confidence * 100.0, 1),
            "optical_anomaly_score": round(float(anomaly_score), 3),
            "class_probabilities": {
                name: round(float(prob), 3) for name, prob in zip(self.CLASSES, probabilities)
            },
            "feature_vector": [round(float(x), 2) for x in features],
            "one_shot_active": one_shot_active,
            "nearest_prototype": nearest_cat if one_shot_active else None,
            "prototype_distance": round(min_proto_dist, 3) if one_shot_active and min_proto_dist < 900.0 else None
        }

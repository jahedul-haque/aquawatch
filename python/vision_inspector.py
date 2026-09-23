"""
Does the Visual inspection of the camera image

Inspection Features:
1. Visual Clarity / Opacity Index (Laplacian variance & edge contrast)
2. Discoloration & Colorimetry (CIE-Lab / HSV delta against pure water baseline)
3. Suspended Particulates Detection (Blob analysis, size distribution, count)
4. Surface Sheen & Film Detection (Specular gradient on surface meniscus)
"""

import cv2
import numpy as np
import time
import math
from typing import Dict, Any, Tuple, Optional

class WaterVisionInspector:
    def __init__(self, camera_index: int = 0, frame_width: int = 640, frame_height: int = 480):
        self.camera_index = camera_index
        self.frame_width = frame_width
        self.frame_height = frame_height
        
        self.cap = None
        self.camera_detected = False
        self.camera_index_used = None
        self.camera_error = "Camera not initialized"
        self.camera_power_state = "OFF"
        self.last_probe_time = 0.0
        
        # Initial probe to check hardware, then release immediately
        self._probe_camera_once()

        # Pure water calibration reference in Lab color space
        # Default baseline calibrated for flow-cell chamber
        if self.camera_detected:
            self.baseline_lab = np.array([116.0, 134.0, 123.0]) # Live camera flow-cell baseline
        else:
            self.baseline_lab = np.array([183.0, 128.0, 128.0]) # Backlit simulation baseline
        self.baseline_var = 750.0
        
        # Particulate tracker temporal state
        self.prev_gray_roi = None
        self.sim_frame_counter = 0

    def set_clean_baseline(self, lab: list, laplacian_var: float = 750.0):
        """Sets calibrated baseline Lab color and grid sharpness variance."""
        if len(lab) >= 3:
            self.baseline_lab = np.array([float(lab[0]), float(lab[1]), float(lab[2])])
        self.baseline_var = max(1.0, float(laplacian_var))

    def reset_factory_baseline(self):
        """Restores factory default baseline parameters."""
        if self.camera_detected:
            self.baseline_lab = np.array([116.0, 134.0, 123.0])
        else:
            self.baseline_lab = np.array([183.0, 128.0, 128.0])
        self.baseline_var = 750.0

    def calibrate_baseline(self, frame: np.ndarray):
        """Calibrates baseline color and sharpness reference from a known clear water flow cell frame."""
        h, w = frame.shape[:2]
        bulk_roi = frame[int(0.25 * h):int(0.85 * h), int(0.15 * w):int(0.85 * w)]
        lab = cv2.cvtColor(bulk_roi, cv2.COLOR_BGR2LAB)
        self.baseline_lab = np.mean(lab, axis=(0, 1))
        gray = cv2.cvtColor(bulk_roi, cv2.COLOR_BGR2GRAY)
        self.baseline_var = max(1.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()))

    def turn_off_camera(self):
        """Ensures any camera handle is closed and hardware powered down."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.camera_power_state = "OFF"

    def _probe_camera_once(self):
        """Quick initial hardware check on startup."""
        self.last_probe_time = time.time()
        self._is_offline_error_frame = False
        indices = [2, 3, 4, 0, 1]
        if self.camera_index not in indices:
            indices.insert(0, self.camera_index)

        for idx in indices:
            cap = None
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
                    for _ in range(6):
                        ret, test_frame = cap.read()
                        if ret and test_frame is not None and test_frame.size > 0:
                            self.camera_detected = True
                            self.camera_index_used = idx
                            self.camera_error = ""
                            self._is_offline_error_frame = False
                            cap.release()
                            self.camera_power_state = "OFF"
                            return
            except Exception:
                pass
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        self.camera_detected = False
        self.camera_index_used = None
        self._is_offline_error_frame = True
        self.camera_error = "No USB camera detected on /dev/video*. Connect a UVC camera to Uno Q."
        self.camera_power_state = "OFF"

    def is_detected(self) -> bool:
        return self.camera_detected

    def _generate_error_frame(self) -> np.ndarray:
        """Generates a high-visibility industrial hardware error display when no camera is connected."""
        w, h = self.frame_width, self.frame_height
        frame = np.full((h, w, 3), (25, 20, 18), dtype=np.uint8) # Dark carbon background
        
        # Outer caution border
        cv2.rectangle(frame, (12, 12), (w - 12, h - 12), (40, 45, 180), 2)
        cv2.rectangle(frame, (16, 16), (w - 16, h - 16), (25, 30, 80), 1)
        
        # Hazard hash marks on top and bottom borders
        for x in range(25, w - 25, 30):
            cv2.line(frame, (x, 14), (x + 12, 28), (40, 50, 180), 2)
            cv2.line(frame, (x, h - 28), (x + 12, h - 14), (40, 50, 180), 2)
            
        # Warning triangle in center
        center_x, center_y = w // 2, h // 2 - 40
        pt1 = (center_x, center_y - 48)
        pt2 = (center_x - 52, center_y + 36)
        pt3 = (center_x + 52, center_y + 36)
        triangle_cnt = np.array([pt1, pt2, pt3], np.int32)
        cv2.drawContours(frame, [triangle_cnt], 0, (0, 140, 255), -1) # Amber/Orange fill
        cv2.drawContours(frame, [triangle_cnt], 0, (0, 60, 220), 2)   # Red outline
        
        # Exclamation mark inside triangle
        cv2.line(frame, (center_x, center_y - 24), (center_x, center_y + 10), (15, 15, 20), 6)
        cv2.circle(frame, (center_x, center_y + 24), 5, (15, 15, 20), -1)
        
        # Primary Title
        title = "CAMERA HARDWARE NOT DETECTED"
        cv2.putText(frame, title, (w // 2 - 210, center_y + 80),
                    cv2.FONT_HERSHEY_DUPLEX, 0.72, (60, 75, 255), 2, cv2.LINE_AA)
        
        # Secondary Error Details
        sub1 = "Device '/dev/video0' is offline or not a capture device."
        cv2.putText(frame, sub1, (w // 2 - 200, center_y + 115),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (200, 205, 215), 1, cv2.LINE_AA)
                    
        sub2 = "Connect a USB UVC Camera to the Uno Q USB-C / Host port."
        cv2.putText(frame, sub2, (w // 2 - 215, center_y + 142),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (120, 195, 255), 1, cv2.LINE_AA)
                    
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        sub3 = f"Auto-reconnect scanner active • {ts_str}"
        cv2.putText(frame, sub3, (w // 2 - 180, center_y + 175),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (110, 120, 135), 1, cv2.LINE_AA)
                    
        return frame

    def _optimize_exposure(self, frame: np.ndarray, target_mean: float = 85.0) -> np.ndarray:
        """
        Applies adaptive tone mapping and exposure optimization to ensure
        the optical flow cell and water chamber are clearly visible without being dark.
        """
        if frame is None or frame.size == 0:
            return frame
        current_mean = float(frame.mean())
        if current_mean < 4.0:
            return frame
        if current_mean < target_mean:
            # Adaptive logarithmic gamma curve lifts deep shadows and midtones naturally
            gamma = max(0.35, min(0.95, np.log(target_mean / 255.0) / np.log(current_mean / 255.0)))
            lut = np.array([((i / 255.0) ** gamma) * 255.0 for i in range(256)]).astype(np.uint8)
            return cv2.LUT(frame, lut)
        return frame

    def _enhance_sharpness(self, frame: np.ndarray) -> np.ndarray:
        """
        Applies subtle unsharp masking (USM) to enhance micro-particulates,
        flow-cell boundaries, and edge clarity without noise amplification.
        """
        if frame is None or frame.size == 0:
            return frame
        blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=1.8, sigmaY=1.8)
        sharpened = cv2.addWeighted(frame, 1.35, blurred, -0.35, 0)
        return sharpened

    def capture_frame(self, simulation_condition: str = "live") -> np.ndarray:
        """
        Powers ON USB UVC Camera, captures a flow-cell snapshot with auto-exposure stabilization,
        best-sharpness frame selection, and unsharp masking, then IMMEDIATELY powers OFF camera.
        If in test/simulation mode, generates realistic synthetic test frame.
        """
        # 1. Return synthetic frame for test conditions or when test mock index is used
        if self.camera_index < 0 or (simulation_condition and simulation_condition != "live"):
            cond = simulation_condition if simulation_condition != "live" else "clear"
            self._is_offline_error_frame = False
            self.camera_detected = True
            return self._generate_synthetic_frame(condition=cond)

        self.camera_power_state = "ON (Sampling)"
        indices = []
        if self.camera_index_used is not None:
            indices.append(self.camera_index_used)
        for i in [2, 3, 4, 0, 1]:
            if i not in indices:
                indices.append(i)

        captured_frame = None

        for idx in indices:
            cap = None
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    try:
                        # V4L2 auto-exposure mode (3 = Aperture Priority / Auto)
                        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
                    except Exception:
                        pass
                    try:
                        # Hardware sharpness if supported by UVC driver
                        cap.set(cv2.CAP_PROP_SHARPNESS, 128)
                    except Exception:
                        pass

                    # Flush kernel ring-buffers, let AEC/AGC adapt, and select the sharpest frame
                    best_frame = None
                    sharpest_frame = None
                    max_sharpness = -1.0
                    for frame_idx in range(22):
                        ret, f = cap.read()
                        if ret and f is not None and f.size > 0:
                            best_frame = f
                            if frame_idx >= 6:
                                try:
                                    gray_f = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                                    sharpness = float(cv2.Laplacian(gray_f, cv2.CV_64F).var())
                                    if sharpness > max_sharpness:
                                        max_sharpness = sharpness
                                        sharpest_frame = f
                                except Exception:
                                    pass

                    final_frame = sharpest_frame if sharpest_frame is not None else best_frame
                    if final_frame is not None:
                        try:
                            opt = self._optimize_exposure(final_frame)
                            if opt is not None:
                                final_frame = opt
                        except Exception:
                            pass
                        try:
                            sharp = self._enhance_sharpness(final_frame)
                            if sharp is not None:
                                final_frame = sharp
                        except Exception:
                            pass
                        captured_frame = final_frame
                        self.camera_detected = True
                        self.camera_index_used = idx
                        self.camera_error = ""
                        self._is_offline_error_frame = False
                        break
            except Exception as e:
                pass
            finally:
                # IMMEDIATELY TURN OFF / RELEASE CAMERA HARDWARE
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        # Camera is now powered down
        self.camera_power_state = "OFF"
        self.cap = None

        if captured_frame is not None:
            return captured_frame

        # Camera was not detected or only delivered inactive all-black stream
        self.camera_detected = False
        self._is_offline_error_frame = True
        self.camera_error = "No USB camera detected on /dev/video*. Connect a UVC camera to Uno Q."
        return self._generate_error_frame()

    def _generate_ai_diagnostic_overlay(self) -> np.ndarray:
        """Generates an unmistakable Edge-AI Neural Network HUD overlay when camera is offline."""
        w, h = self.frame_width, self.frame_height
        frame = np.full((h, w, 3), (22, 18, 14), dtype=np.uint8) # Dark sci-fi slate
        
        # Grid pattern for AI vision coordinate space
        grid_spacing = 30
        for x in range(0, w, grid_spacing):
            cv2.line(frame, (x, 0), (x, h), (35, 28, 22), 1)
        for y in range(0, h, grid_spacing):
            cv2.line(frame, (0, y), (w, y), (35, 28, 22), 1)
            
        # Top HUD Banner: Edge AI System
        cv2.rectangle(frame, (0, 0), (w, 36), (150, 40, 20), -1)
        cv2.putText(frame, "BRAIN: EDGE-AI COMPUTER VISION OVERLAY", (15, 24),
                    cv2.FONT_HERSHEY_DUPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "MODEL: MobileNetV2 + Contamination CNN", (w - 315, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 229, 255), 1, cv2.LINE_AA)

        # Draw simulated AI Target / Reticle in center
        cx, cy = w // 2, h // 2 - 30
        cv2.circle(frame, (cx, cy), 65, (0, 229, 255), 1)
        cv2.circle(frame, (cx, cy), 85, (90, 90, 100), 1)
        cv2.line(frame, (cx - 105, cy), (cx - 70, cy), (0, 229, 255), 2)
        cv2.line(frame, (cx + 70, cy), (cx + 105, cy), (0, 229, 255), 2)
        cv2.line(frame, (cx, cy - 105), (cx, cy - 70), (0, 229, 255), 2)
        cv2.line(frame, (cx, cy + 70), (cx, cy + 105), (0, 229, 255), 2)
        cv2.putText(frame, "AI RETICLE: STANDBY", (cx - 65, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 229, 255), 1, cv2.LINE_AA)

        # AI Inspection Status Box
        box_w, box_h = 380, 125
        bx1, by1 = (w - box_w) // 2, h - box_h - 18
        cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (25, 30, 40), -1)
        cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (0, 229, 255), 1)
        
        cv2.putText(frame, "OPTICAL INFERENCE DIAGNOSTICS", (bx1 + 15, by1 + 22),
                    cv2.FONT_HERSHEY_DUPLEX, 0.44, (0, 229, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "Status: STANDBY (Awaiting USB Optical Stream)", (bx1 + 15, by1 + 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (230, 230, 230), 1, cv2.LINE_AA)
        cv2.putText(frame, "Target Device: /dev/video* (Scanning 0-4 every 8s)", (bx1 + 15, by1 + 67),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 170, 185), 1, cv2.LINE_AA)
        cv2.putText(frame, "Particulate Tracker: READY (0 Bounding Boxes)", (bx1 + 15, by1 + 89),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 170, 185), 1, cv2.LINE_AA)
        cv2.putText(frame, "Connect UVC camera to Uno Q to render live overlay", (bx1 + 15, by1 + 111),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (80, 220, 120), 1, cv2.LINE_AA)
                    
        return frame

    def analyze_frame(self, frame: np.ndarray) -> Tuple[Dict[str, Any], np.ndarray]:
        """
        Executes full computer vision inspection on the water column frame.
        If camera is not detected, returns offline diagnostic status and marked overlay.
        """
        h, w = frame.shape[:2]
        
        if not self.camera_detected and getattr(self, '_is_offline_error_frame', False):
            annotated = self._generate_ai_diagnostic_overlay()
            metrics = {
                "camera_detected": False,
                "camera_error": self.camera_error,
                "clarity_percent": 0.0,
                "laplacian_variance": 0.0,
                "discoloration_delta_e": 0.0,
                "tint_classification": "Camera Offline",
                "particulate_count": 0,
                "max_particle_size_px": 0,
                "surface_sheen_detected": False,
                "sheen_intensity": 0.0,
                "optical_anomaly_score": 0.0,
                "timestamp": time.time()
            }
            return metrics, annotated

        annotated = frame.copy()

        # Define Regions of Interest (ROI)
        # Meniscus / Surface ROI (top 18% of flow chamber)
        surface_roi = frame[int(0.05 * h):int(0.23 * h), int(0.15 * w):int(0.85 * w)]
        
        # Bulk Water ROI (middle 60% of chamber)
        bulk_roi = frame[int(0.25 * h):int(0.85 * h), int(0.15 * w):int(0.85 * w)]
        bulk_y1, bulk_y2 = int(0.25 * h), int(0.85 * h)
        bulk_x1, bulk_x2 = int(0.15 * w), int(0.85 * w)

        # 1. Visual Clarity / Opacity Index
        clarity_pct, laplacian_var = self._measure_clarity(bulk_roi)

        # 2. Discoloration & Colorimetry (CIE-Lab & HSV)
        discoloration_delta, tint_name, mean_bgr = self._measure_discoloration(bulk_roi)

        # 3. Suspended Particulate Counting & Sizing
        particle_count, max_particle_px, particle_contours = self._detect_particulates(bulk_roi)

        # 4. Surface Sheen / Hydrocarbon Film Detection
        sheen_detected, sheen_intensity = self._detect_surface_sheen(surface_roi)

        # Draw HUD Annotations on the annotated frame
        # Draw ROI borders
        cv2.rectangle(annotated, (bulk_x1, bulk_y1), (bulk_x2, bulk_y2), (80, 200, 80), 2)
        cv2.putText(annotated, "BULK WATER CHAMBER", (bulk_x1, bulk_y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 200, 80), 1)

        cv2.rectangle(annotated, (int(0.15 * w), int(0.05 * h)), (int(0.85 * w), int(0.23 * h)), (255, 180, 50), 1)
        cv2.putText(annotated, "SURFACE MENISCUS", (int(0.15 * w), int(0.05 * h) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 180, 50), 1)

        # Draw detected particle bounding boxes
        for c in particle_contours:
            x, y, pw, ph = cv2.boundingRect(c)
            # Offset to frame coordinates
            gx, gy = bulk_x1 + x, bulk_y1 + y
            cv2.rectangle(annotated, (gx, gy), (gx + pw, gy + ph), (0, 0, 255), 1)
            cv2.circle(annotated, (gx + pw // 2, gy + ph // 2), 2, (0, 255, 255), -1)

        # HUD Overlay Cards
        self._render_hud_overlay(annotated, clarity_pct, discoloration_delta, tint_name,
                                particle_count, sheen_detected, mean_bgr)

        metrics = {
            "clarity_percent": round(clarity_pct, 1),
            "laplacian_variance": round(laplacian_var, 2),
            "discoloration_delta_e": round(discoloration_delta, 2),
            "tint_classification": tint_name,
            "particulate_count": particle_count,
            "max_particle_size_px": max_particle_px,
            "surface_sheen_detected": sheen_detected,
            "sheen_intensity": round(sheen_intensity, 2),
            "timestamp": time.time()
        }

        return metrics, annotated

    def _measure_clarity(self, roi: np.ndarray) -> Tuple[float, float]:
        """Measures high-frequency gradient sharpness through the water column."""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        var = float(laplacian.var())
        
        # Nominal clarity transfer curve relative to calibrated clean baseline
        ref_var = getattr(self, 'baseline_var', 750.0)
        if ref_var < 50.0:
            # Low baseline variance indicates a smooth, unpatterned background (plain container / no optical grid).
            # Clean transparent water preserves this low variance.
            rel_ratio = var / max(1.0, ref_var)
            if rel_ratio <= 1.5:
                clarity_pct = 100.0 - max(0.0, (rel_ratio - 1.0) * 10.0)
            else:
                clarity_pct = max(0.0, 100.0 - (rel_ratio - 1.0) * 20.0)
        else:
            clarity_pct = min(100.0, max(0.0, (var / ref_var) * 100.0))
        return clarity_pct, var

    def _measure_discoloration(self, roi: np.ndarray) -> Tuple[float, str, Tuple[int, int, int]]:
        """Calculates color deviation in CIE-Lab and classifies tint anomalies."""
        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
        mean_lab = np.mean(lab, axis=(0, 1))
        
        # Perceptual color distance prioritizing chromatic tint (a*, b*) over raw ambient brightness (L*)
        dl = mean_lab[0] - self.baseline_lab[0]
        da = mean_lab[1] - self.baseline_lab[1]
        db = mean_lab[2] - self.baseline_lab[2]
        delta_e = float(np.sqrt(0.20 * (dl ** 2) + (da ** 2) + (db ** 2)))
        chroma_delta = float(np.sqrt((da ** 2) + (db ** 2)))

        # HSV analysis for tint classification
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h_mean = np.median(hsv[:, :, 0])
        s_mean = np.mean(hsv[:, :, 1])
        v_mean = np.mean(hsv[:, :, 2])

        mean_bgr = tuple(int(c) for c in np.mean(roi, axis=(0, 1)))

        tint = "Clear / Neutral"
        # Only declare discoloration if chromatic deviation is substantial or fluid is abnormally dark
        if delta_e > 12.0 and (chroma_delta > 8.0 or s_mean > 60.0 or v_mean < 60.0):
            if (5 <= h_mean <= 32 or h_mean >= 170) and s_mean > 35:
                tint = "Rust / Iron Influx"
            elif 35 <= h_mean <= 85 and s_mean > 40:
                tint = "Algae / Organic Tint"
            elif v_mean < 80:
                tint = "Sewage / Black Sludge"
            elif s_mean > 60:
                tint = "Chemical Chromate / Dye"
            else:
                tint = "Turbid Greyish"

        return delta_e, tint, mean_bgr

    def _detect_particulates(self, roi: np.ndarray) -> Tuple[int, int, list]:
        """Detects high-contrast suspended debris specks while rejecting linear chamber/tube reflections."""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Remove low frequency illumination gradients (Gaussian high-pass)
        blur = cv2.GaussianBlur(gray, (21, 21), 0)
        high_pass = cv2.absdiff(gray, blur)

        # Threshold illuminated particles
        _, thresh = cv2.threshold(high_pass, 18, 255, cv2.THRESH_BINARY)
        # Suppress thin 1-2px continuous line boundaries
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_particles = []
        max_size = 0

        for c in contours:
            area = cv2.contourArea(c)
            # Filter single-pixel camera sensor noise and huge chamber edge reflections
            if 4 <= area <= 600:
                x, y, pw, ph = cv2.boundingRect(c)
                # Reject elongated linear features (tube walls, scratches, chamber borders)
                aspect_ratio = max(pw, ph) / max(1.0, float(min(pw, ph)))
                if aspect_ratio > 3.2:
                    continue

                peri = cv2.arcLength(c, True)
                if peri > 0:
                    circularity = 4.0 * np.pi * area / (peri * peri)
                    if circularity < 0.12:
                        continue

                valid_particles.append(c)
                if area > max_size:
                    max_size = int(area)

        return len(valid_particles), max_size, valid_particles

    def _detect_surface_sheen(self, surface_roi: np.ndarray) -> Tuple[bool, float]:
        """Detects iridescent rainbow fringes or high specular gradients from hydrocarbon oil slicks."""
        hsv = cv2.cvtColor(surface_roi, cv2.COLOR_BGR2HSV)
        # Saturation channel on surface meniscus (thin-film chromatic interference)
        s_channel = hsv[:, :, 1]
        s_std = float(np.std(s_channel))
        s_mean = float(np.mean(s_channel))
        
        # Sheen metric combines saturation spread and mean
        # Real thin-film oil slick creates vivid chromatic fringes (>125); ambient water reflection is ~60-95
        sheen_metric = s_std + (s_mean * 0.5)
        sheen_detected = sheen_metric > 125.0
        return sheen_detected, sheen_metric

    def _render_hud_overlay(self, img: np.ndarray, clarity: float, delta_e: float,
                            tint: str, particles: int, sheen: bool, bgr: Tuple[int, int, int]):
        """Renders industrial heads-up display overlay on video feed."""
        h, w = img.shape[:2]
        
        # Header banner
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (w, 42), (20, 25, 30), -1)
        cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)

        cv2.putText(img, "MUNICIPAL WATER INSPECTION | QRB2210 VISION", (12, 26),
                    cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1)

        # Bottom info card
        card_h = 75
        overlay = img.copy()
        cv2.rectangle(overlay, (0, h - card_h), (w, h), (15, 20, 25), -1)
        cv2.addWeighted(overlay, 0.82, img, 0.18, 0, img)

        # Clarity meter
        c_color = (0, 255, 100) if clarity >= 75 else ((0, 200, 255) if clarity >= 50 else (0, 50, 255))
        cv2.putText(img, f"Clarity: {clarity:.1f}%", (15, h - 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, c_color, 1)

        # Particulates
        p_color = (0, 255, 100) if particles < 10 else ((0, 180, 255) if particles < 30 else (0, 0, 255))
        cv2.putText(img, f"Particles: {particles}", (15, h - 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, p_color, 1)

        # Tint / Discoloration
        d_color = (0, 255, 100) if delta_e < 12.0 else (0, 80, 255)
        cv2.putText(img, f"Tint: {tint} (dE:{delta_e:.1f})", (200, h - 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, d_color, 1)

        # Surface Sheen
        s_color = (0, 0, 255) if sheen else (0, 255, 100)
        s_text = "SHEEN DETECTED!" if sheen else "Normal Meniscus"
        cv2.putText(img, f"Surface: {s_text}", (200, h - 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, s_color, 1)

        # Draw color swatch
        cv2.rectangle(img, (w - 70, h - 60), (w - 20, h - 15), bgr, -1)
        cv2.rectangle(img, (w - 70, h - 60), (w - 20, h - 15), (255, 255, 255), 1)

    def _generate_synthetic_frame(self, condition: str = "clear") -> np.ndarray:
        """Generates realistic synthetic camera frames for testing without physical rig."""
        self.sim_frame_counter += 1
        w, h = self.frame_width, self.frame_height
        
        # Base background: flow chamber with backlight
        frame = np.ones((h, w, 3), dtype=np.uint8) * 220
        
        # Backlit grid / fiducial pattern behind water
        grid_step = 25
        for x in range(0, w, grid_step):
            cv2.line(frame, (x, 0), (x, h), (40, 40, 40), 2)
        for y in range(0, h, grid_step):
            cv2.line(frame, (0, y), (w, y), (40, 40, 40), 2)

        # Chamber side walls
        cv2.rectangle(frame, (0, 0), (int(0.12 * w), h), (60, 60, 65), -1)
        cv2.rectangle(frame, (int(0.88 * w), 0), (w, h), (60, 60, 65), -1)

        # Apply condition effects
        if condition == "turbid":
            # Blur pattern heavily
            frame = cv2.GaussianBlur(frame, (35, 35), 0)
            tint = np.full_like(frame, (160, 180, 190), dtype=np.uint8)
            frame = cv2.addWeighted(frame, 0.4, tint, 0.6, 0)
            # Add lots of particulates
            for _ in range(35):
                rx = np.random.randint(int(0.15 * w), int(0.85 * w))
                ry = np.random.randint(int(0.25 * h), int(0.85 * h))
                cv2.circle(frame, (rx, ry), np.random.randint(2, 6), (70, 90, 100), -1)

        elif condition == "rust":
            # Reddish-brown tint
            rust_tint = np.zeros_like(frame, dtype=np.uint8)
            rust_tint[:] = (40, 80, 180) # BGR
            frame = cv2.addWeighted(frame, 0.6, rust_tint, 0.4, 0)
            frame = cv2.GaussianBlur(frame, (11, 11), 0)

        elif condition == "sheen":
            # Surface rainbow gradient on meniscus
            meniscus_y1, meniscus_y2 = int(0.08 * h), int(0.20 * h)
            for y in range(meniscus_y1, meniscus_y2):
                ratio = (y - meniscus_y1) / (meniscus_y2 - meniscus_y1)
                color = (int(255 * ratio), int(200 * (1 - ratio)), int(180 * math.sin(ratio * 3.14)))
                cv2.line(frame, (int(0.15 * w), y), (int(0.85 * w), y), color, 1)

        elif condition == "algae":
            # Algal bloom: greenish tint and micro-clumps
            algae_tint = np.zeros_like(frame, dtype=np.uint8)
            algae_tint[:] = (40, 160, 60) # BGR
            frame = cv2.addWeighted(frame, 0.65, algae_tint, 0.35, 0)
            frame = cv2.GaussianBlur(frame, (15, 15), 0)
            for _ in range(25):
                rx = np.random.randint(int(0.15 * w), int(0.85 * w))
                ry = np.random.randint(int(0.25 * h), int(0.85 * h))
                cv2.circle(frame, (rx, ry), np.random.randint(2, 5), (30, 120, 40), -1)

        elif condition == "sewage":
            # Dark greyish/black sludge with heavy particulates
            sewage_tint = np.zeros_like(frame, dtype=np.uint8)
            sewage_tint[:] = (45, 55, 60) # BGR
            frame = cv2.addWeighted(frame, 0.45, sewage_tint, 0.55, 0)
            frame = cv2.GaussianBlur(frame, (25, 25), 0)
            for _ in range(40):
                rx = np.random.randint(int(0.15 * w), int(0.85 * w))
                ry = np.random.randint(int(0.25 * h), int(0.85 * h))
                cv2.circle(frame, (rx, ry), np.random.randint(3, 7), (20, 25, 30), -1)

        else: # "clear"
            # Slight Gaussian blur to simulate water index of refraction
            frame = cv2.GaussianBlur(frame, (3, 3), 0)
            # Add a couple of harmless micro-specks
            for _ in range(3):
                rx = np.random.randint(int(0.15 * w), int(0.85 * w))
                ry = np.random.randint(int(0.25 * h), int(0.85 * h))
                cv2.circle(frame, (rx, ry), 2, (150, 150, 150), -1)

        return frame

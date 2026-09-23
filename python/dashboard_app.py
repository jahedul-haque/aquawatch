"""
UI based on FastAPI, get the sample , run count down timer, get sample automatically after 10 mins
"""

import asyncio
import cv2
import json
import logging
import os
import threading
import time
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bridge_client import STM32BridgeClient
from vision_inspector import WaterVisionInspector
from contamination_engine import ContaminationEngine
from lorawan_service import LoRaWANService
from sdcard_manager import SDCardManager
from calibration_manager import CalibrationManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WaterMonitorServer")

app = FastAPI(title="AquaWatch: Edge-AI LoRaWAN Rural Water Monitor")

# Subsystem Instances
bridge = STM32BridgeClient(mode="auto")
vision = WaterVisionInspector(camera_index=0)
engine = ContaminationEngine()
lorawan = LoRaWANService()
lorawan.set_bridge_client(bridge)
if not lorawan.node_found:
    lorawan.probe_modem()
sdcard = SDCardManager()
calib_manager = CalibrationManager()

# Apply saved calibration on startup if available
clean_base = calib_manager.get_clean_baseline()
if clean_base and "visual_features" in clean_base:
    feat = clean_base["visual_features"]
    if len(feat) >= 4:
        vision.set_clean_baseline(feat[0:3], feat[3])
engine.vision_ai.set_prototypes(calib_manager.get_prototype_vectors())
engine.set_spectral_baseline(calib_manager.get_spectral_baseline())


# Shared State
state_lock = threading.RLock()
current_assessment: Dict[str, Any] = {}
latest_raw_bytes: Optional[bytes] = None
latest_annotated_bytes: Optional[bytes] = None
latest_snapshot_path: str = ""
SAMPLE_INTERVAL_SEC = 600
seconds_to_next_sample = SAMPLE_INTERVAL_SEC
force_sample_event = threading.Event()
simulated_vision_condition = "live"

class ScenarioCommand(BaseModel):
    scenario: str

def execute_sampling_cycle():
    """Performs the full 10-minute sampling, Edge AI analysis, SD card write, and LoRaWAN dispatch."""
    global current_assessment, latest_raw_bytes, latest_annotated_bytes, latest_snapshot_path

    logger.info("--> Executing 10-minute water quality sampling cycle...")
    
    # 1. Trigger sample on STM32 (initiates 1.0s pre-warm & illuminates AS7341 flow-cell LED)
    bridge.trigger_sample()

    # Allow 0.3s for AS7341 illumination LED to reach full optical output
    time.sleep(0.3)

    # 2. Capture high-res camera frame while flow-cell is illuminated
    raw_frame = vision.capture_frame(simulation_condition=simulated_vision_condition)
    vision_metrics, annotated_frame = vision.analyze_frame(raw_frame)

    # 3. Allow STM32 to complete spectral capture and turn off LED automatically
    # STM32 pre-warm is 1.0s, spectral capture is ~0.6s.
    # Python already spent ~0.3s + ~0.5s camera capture (~0.8s).
    # Sleeping 0.9s ensures STM32 has safely finished spectral reading, shut off LED, and updated telemetry.
    time.sleep(0.9)

    # 4. Query fresh sensor readings from STM32 MCU
    mcu_telemetry = bridge.get_telemetry()

    # 4. Execute Edge AI & Contamination Evaluation
    assessment = engine.evaluate(mcu_telemetry, vision_metrics, raw_frame=raw_frame)

    # 5. Save raw camera snapshot to SD Card (if enabled in config)
    full_path, filename = sdcard.save_sample(raw_frame, assessment)
    assessment["sdcard"] = sdcard.get_status()
    assessment["sdcard"]["current_image_filename"] = filename if filename else "logging_disabled"

    # Camera hardware status & power state (turned OFF after sampling)
    assessment["camera"] = {
        "detected": vision.camera_detected,
        "device": f"/dev/video{vision.camera_index_used}" if vision.camera_detected else "/dev/video0",
        "error": vision.camera_error,
        "power_state": vision.camera_power_state,
        "resolution": f"{vision.frame_width}x{vision.frame_height}"
    }

    # 6. LoRaWAN Alert / Heartbeat Evaluation
    if not lorawan.node_found:
        lorawan.probe_modem()
    lora_record = lorawan.process_and_transmit(assessment)
    assessment["lorawan"] = lorawan.get_lorawan_status()
    if lora_record:
        assessment["last_uplink"] = lora_record
    elif lorawan.last_uplink_record:
        assessment["last_uplink"] = lorawan.last_uplink_record
    else:
        assessment["last_uplink"] = None

    # 7. Synchronize alert state to STM32 MCU (LED indicator strobe)
    alert_active = assessment.get("lorawan_alert_required", False)
    hazard_code = assessment.get("hazard_code", 0)
    bridge.notify_mcu_alert(alert_active, hazard_code)

    # 7b. Explicit Sensor Inventory & Connection Status
    temp_val = float(mcu_telemetry.get("temp_c", -127.0))
    temp_dummy = bool(mcu_telemetry.get("temp_dummy", False)) or not bool(mcu_telemetry.get("temp_connected", True)) or temp_val <= -50.0 or temp_val == 85.0
    temp_conn = not temp_dummy
    turb_val = float(mcu_telemetry.get("turbidity_ntu", 0.0))
    turb_conn = True  # Physical turbidity sensor active
    ph_conn = not bool(mcu_telemetry.get("ph_dummy", True))
    orp_conn = not bool(mcu_telemetry.get("orp_dummy", True))
    tds_conn = not bool(mcu_telemetry.get("tds_dummy", True))
    spec_data = mcu_telemetry.get("spectral", {})
    spec_conn = bool(spec_data.get("detected", False)) and any(spec_data.get(f"f{i}", 0) > 0 for i in range(1, 9))

    assessment["sensor_inventory"] = {
        "temperature": {
            "name": "Water Temperature",
            "probe": "DS18B20",
            "connected": temp_conn,
            "display": f"{temp_val:.1f} °C" if temp_conn else "Not connected",
            "value": temp_val if temp_conn else None,
            "unit": "°C"
        },
        "turbidity": {
            "name": "Turbidity",
            "probe": "ASAIR AZDM01 940nm IR",
            "connected": turb_conn,
            "display": f"{turb_val:.2f} NTU" if turb_conn else "Not connected",
            "value": turb_val if turb_conn else None,
            "unit": "NTU"
        },
        "ph": {
            "name": "pH Probe",
            "probe": "Analog Glass Electrode",
            "connected": ph_conn,
            "display": f"{mcu_telemetry.get('ph', 7.0):.2f}" if ph_conn else "Not connected",
            "value": mcu_telemetry.get("ph") if ph_conn else None,
            "unit": "pH"
        },
        "orp": {
            "name": "ORP Redox Probe",
            "probe": "Analog Platinum Electrode",
            "connected": orp_conn,
            "display": f"{mcu_telemetry.get('orp_mv', 0):.0f} mV" if orp_conn else "Not connected",
            "value": mcu_telemetry.get("orp_mv") if orp_conn else None,
            "unit": "mV"
        },
        "tds": {
            "name": "TDS Probe",
            "probe": "Conductivity Probe",
            "connected": tds_conn,
            "display": f"{mcu_telemetry.get('tds_ppm', 0):.0f} ppm" if tds_conn else "Not connected",
            "value": mcu_telemetry.get("tds_ppm") if tds_conn else None,
            "unit": "ppm"
        },
        "spectral": {
            "name": "Spectrometer",
            "probe": "AS7341 10-Channel VIS/NIR",
            "connected": spec_conn,
            "display": "Connected" if spec_conn else "Not connected",
            "value": "Active" if spec_conn else None,
            "channels": {
                "f1_415": int(spec_data.get("f1", 0)) if spec_conn else 0,
                "f2_445": int(spec_data.get("f2", 0)) if spec_conn else 0,
                "f3_480": int(spec_data.get("f3", 0)) if spec_conn else 0,
                "f4_515": int(spec_data.get("f4", 0)) if spec_conn else 0,
                "f5_555": int(spec_data.get("f5", 0)) if spec_conn else 0,
                "f6_590": int(spec_data.get("f6", 0)) if spec_conn else 0,
                "f7_630": int(spec_data.get("f7", 0)) if spec_conn else 0,
                "f8_680": int(spec_data.get("f8", 0)) if spec_conn else 0,
                "clear": int(spec_data.get("clear", 0)) if spec_conn else 0,
                "nir": int(spec_data.get("nir", 0)) if spec_conn else 0
            },
            "algae_ndai": spec_data.get("algae_ndai", 0.0) if spec_conn else 0.0,
            "cdom_index": spec_data.get("cdom_index", 0.0) if spec_conn else 0.0,
            "delta_ndai": spec_data.get("delta_ndai", 0.0) if spec_conn else 0.0,
            "delta_cdom": spec_data.get("delta_cdom", 0.0) if spec_conn else 0.0,
            "baseline_ndai": spec_data.get("baseline_ndai", 0.48) if spec_conn else 0.48,
            "calibrated": spec_data.get("spectral_calibrated", False) if spec_conn else False
        },

        "camera": {
            "name": "Optical Camera",
            "probe": "USB Flow-Cell UVC",
            "connected": vision.camera_detected,
            "display": "Connected" if vision.camera_detected else "Not connected"
        }
    }

    # 7c. Calibration & One-Shot Learning Status
    assessment["calibration"] = calib_manager.get_summary()

    # 8. Encode both Raw camera JPEG and Annotated CV JPEG
    ret_raw, jpeg_raw = cv2.imencode('.jpg', raw_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    ret_ann, jpeg_ann = cv2.imencode('.jpg', annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

    with state_lock:
        current_assessment = assessment
        latest_snapshot_path = full_path
        latest_raw_bytes = jpeg_raw.tobytes() if ret_raw else None
        latest_annotated_bytes = jpeg_ann.tobytes() if ret_ann else None

    logger.info(f"--> Sample complete: WQI={assessment.get('wqi')} | Status={assessment.get('safety_level')}")

def periodic_timer_loop():
    """Controls the 10-minute interval timer and countdown."""
    global seconds_to_next_sample
    
    # Initial immediate sample on boot
    execute_sampling_cycle()

    while True:
        seconds_to_next_sample = SAMPLE_INTERVAL_SEC
        while seconds_to_next_sample > 0:
            if force_sample_event.is_set():
                force_sample_event.clear()
                break
            time.sleep(1.0)
            seconds_to_next_sample -= 1

        execute_sampling_cycle()

# Start background timer thread
threading.Thread(target=periodic_timer_loop, daemon=True).start()

def _ensure_image_bytes(annotated: bool = False) -> bytes:
    """Generates immediate frame bytes if not yet initialized, preventing 404s."""
    global latest_raw_bytes, latest_annotated_bytes
    frame = vision.capture_frame(simulation_condition=simulated_vision_condition)
    metrics, ann = vision.analyze_frame(frame)
    ret_r, j_r = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    ret_a, j_a = cv2.imencode('.jpg', ann, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    with state_lock:
        if not latest_raw_bytes and ret_r:
            latest_raw_bytes = j_r.tobytes()
        if not latest_annotated_bytes and ret_a:
            latest_annotated_bytes = j_a.tobytes()
    if annotated and ret_a:
        return j_a.tobytes()
    return j_r.tobytes() if ret_r else b""

# API Endpoints
@app.get("/api/status")
def get_status():
    with state_lock:
        if not current_assessment:
            execute_sampling_cycle()
        res = current_assessment.copy()
    res["seconds_until_next_sample"] = seconds_to_next_sample
    if "lorawan" not in res:
        res["lorawan"] = lorawan.get_lorawan_status()
    if "calibration" not in res:
        res["calibration"] = calib_manager.get_summary()
    if "camera" not in res:
        res["camera"] = {
            "detected": vision.camera_detected,
            "device": f"/dev/video{vision.camera_index_used}" if vision.camera_detected else "/dev/video0",
            "error": vision.camera_error,
            "power_state": vision.camera_power_state,
            "resolution": f"{vision.frame_width}x{vision.frame_height}"
        }
    return res

@app.get("/api/camera/status")
def get_camera_status():
    """Returns direct diagnostic information about the optical camera hardware."""
    return {
        "detected": vision.camera_detected,
        "device": f"/dev/video{vision.camera_index_used}" if vision.camera_detected else "/dev/video0",
        "error": vision.camera_error,
        "power_state": vision.camera_power_state,
        "resolution": f"{vision.frame_width}x{vision.frame_height}"
    }

@app.post("/api/sample_now")
def sample_now():
    """Triggers an on-demand sample immediately."""
    force_sample_event.set()
    return {"status": "sampling_triggered"}

@app.get("/api/raw_image")
@app.get("/api/camera_snapshot")
def get_raw_image():
    """Serves the pure raw camera image (or explicit error frame if camera disconnected)."""
    with state_lock:
        data = latest_raw_bytes
    if not data:
        data = _ensure_image_bytes(annotated=False)
    if data:
        return Response(content=data, media_type="image/jpeg")
    return Response(status_code=500)

@app.get("/api/annotated_image")
def get_annotated_image():
    """Serves the Edge AI annotated image overlay (or error frame if camera disconnected)."""
    with state_lock:
        data = latest_annotated_bytes
    if not data:
        data = _ensure_image_bytes(annotated=True)
    if data:
        return Response(content=data, media_type="image/jpeg")
    return Response(status_code=500)

@app.get("/api/latest_image")
def get_latest_image(view: str = "raw"):
    """Serves the latest camera snapshot (default: raw image)."""
    with state_lock:
        if view == "annotated":
            data = latest_annotated_bytes or latest_raw_bytes
        else:
            data = latest_raw_bytes or latest_annotated_bytes
    if not data:
        data = _ensure_image_bytes(annotated=(view == "annotated"))
    if data:
        return Response(content=data, media_type="image/jpeg")
    return Response(status_code=500)

class SetDevEuiRequest(BaseModel):
    deveui: str

@app.post("/api/lorawan/test_uplink")
@app.post("/api/lorawan/send_now")
def trigger_test_uplink():
    if not lorawan.node_found:
        return Response(content=json.dumps({
            "status": "error",
            "message": "LoRa node not found. Please attach hardware modem to serial port."
        }), status_code=400, media_type="application/json")
    with state_lock:
        data = current_assessment.copy()
    record = lorawan.send_uplink_now(data, confirmed=False, f_port=10)
    with state_lock:
        if "lorawan" in current_assessment:
            current_assessment["lorawan"]["last_uplink"] = record
            current_assessment["lorawan"]["last_payload_hex"] = record.get("payload_hex", "")
        current_assessment["last_uplink"] = record
    return {"status": "ok", "uplink": record}

@app.get("/api/lorawan/status")
def get_lorawan_status():
    return lorawan.get_lorawan_status()

@app.get("/api/lorawan/deveui")
def get_lorawan_deveui():
    return {"dev_eui": lorawan.get_deveui(), "node_found": lorawan.node_found}

@app.post("/api/lorawan/deveui")
def set_lorawan_deveui(req: SetDevEuiRequest):
    success, msg = lorawan.set_deveui(req.deveui)
    if not success:
        return Response(content=json.dumps({"status": "error", "message": msg}),
                        status_code=400, media_type="application/json")
    with state_lock:
        if "lorawan" in current_assessment:
            current_assessment["lorawan"] = lorawan.get_lorawan_status()
    return {"status": "ok", "message": msg, "dev_eui": lorawan.get_deveui()}

@app.get("/api/lorawan/appskey")
def get_lorawan_appskey():
    return {"appskey": lorawan.get_appskey(), "node_found": lorawan.node_found}

@app.post("/api/lorawan/scan")
def scan_lorawan_node():
    found = lorawan.probe_modem()
    with state_lock:
        if "lorawan" in current_assessment:
            current_assessment["lorawan"] = lorawan.get_lorawan_status()
    msg = f"LoRaWAN node detected on {lorawan.serial_port}" if found else "LoRa node not found on any serial port"
    return {"status": "ok" if found else "error", "node_found": found, "message": msg, "lorawan": lorawan.get_lorawan_status()}

class ATCommandRequest(BaseModel):
    command: Optional[str] = None
    cmd: Optional[str] = None

@app.get("/api/lorawan/at")
def send_raw_at_command(cmd: str = "AT"):
    """Sends arbitrary AT command directly to LoRa module and returns response."""
    cleaned_cmd = cmd.strip() if cmd else "AT"
    resp = bridge.send_lora_at(cleaned_cmd)
    return {"command": cleaned_cmd, "response": resp, "status": "ok" if resp else "no_response"}

@app.post("/api/lorawan/at")
def send_raw_at_command_post(req: ATCommandRequest):
    """Sends arbitrary AT command directly to LoRa module via POST JSON and returns response."""
    cmd_str = (req.command or req.cmd or "AT").strip()
    resp = bridge.send_lora_at(cmd_str)
    return {"command": cmd_str, "response": resp, "status": "ok" if resp else "no_response"}

@app.post("/api/lorawan/raw_at")
def send_raw_at_command_alias(req: ATCommandRequest):
    """Alias for POST /api/lorawan/at."""
    return send_raw_at_command_post(req)

@app.get("/api/lorawan/join")
@app.post("/api/lorawan/join")
def trigger_lorawan_join():
    """Attempts OTAA network join with nearby LoRaWAN gateway using AT+CJOIN."""
    result = lorawan.join_network()
    with state_lock:
        if "lorawan" in current_assessment:
            current_assessment["lorawan"] = lorawan.get_lorawan_status()
    return result

class CalibrateRequest(BaseModel):
    category: str

@app.post("/api/calibrate")
def calibrate_sample(req: CalibrateRequest):
    cat = req.category
    if cat not in calib_manager.CATEGORIES:
        return Response(content=json.dumps({"error": f"Invalid category {cat}"}), status_code=400, media_type="application/json")
    
    # Capture fresh frame and telemetry
    raw_frame = vision.capture_frame(simulation_condition=simulated_vision_condition)
    v_metrics, _ = vision.analyze_frame(raw_frame)
    raw_features = engine.vision_ai.extract_visual_features(raw_frame).tolist()
    mcu_telemetry = bridge.get_telemetry()

    # Learn sample
    profile = calib_manager.learn_sample(cat, raw_features, mcu_telemetry, v_metrics)

    # If Clean_Potable was learned, update vision baseline & spectral baseline
    if cat == "Clean_Potable":
        l, a, b = raw_features[0:3]
        gvar = raw_features[3]
        vision.set_clean_baseline([l, a, b], gvar)
        engine.set_spectral_baseline(calib_manager.get_spectral_baseline())

    # Update AI classifier prototypes
    engine.vision_ai.set_prototypes(calib_manager.get_prototype_vectors())

    # Re-evaluate sampling cycle immediately with new calibration
    execute_sampling_cycle()

    return {
        "status": "ok",
        "message": f"Successfully calibrated {calib_manager.CATEGORIES[cat]}",
        "profile": profile,
        "calibration": calib_manager.get_summary()
    }

@app.post("/api/calibrate/reset")
def reset_calibration():
    calib_manager.reset_factory()
    vision.reset_factory_baseline()
    engine.vision_ai.reset_prototypes()
    engine.set_spectral_baseline(calib_manager.get_spectral_baseline())
    execute_sampling_cycle()
    return {
        "status": "ok",
        "message": "Reset to factory calibration defaults",
        "calibration": calib_manager.get_summary()
    }


@app.get("/api/calibrate/status")
def get_calibration_status():
    return calib_manager.get_summary()

@app.get("/api/spectral")
def get_spectral_data():
    """Returns the latest 10-channel AS7341 spectral transmission readings and optical indices."""
    with state_lock:
        data = current_assessment.get("spectral_readings", {})
    if not data:
        data = bridge.get_spectral_data()
    return data

@app.post("/api/simulate/scenario")
def set_simulation(cmd: ScenarioCommand):
    global simulated_vision_condition
    s = cmd.scenario
    bridge.set_simulation_scenario(s)
    if s == "sheen":
        simulated_vision_condition = "sheen"
    elif s == "sewage":
        simulated_vision_condition = "sewage"
    elif s == "pipe_burst":
        simulated_vision_condition = "turbid"
    elif s == "algal_bloom":
        simulated_vision_condition = "algae"
    elif s in ("chemical_dye", "rust"):
        simulated_vision_condition = "rust"
    elif s in ("acid_spill", "disinfection_loss", "alkaline_shock"):
        simulated_vision_condition = "clear"
    else: # normal
        simulated_vision_condition = "live"

    # Immediately execute sampling cycle with the new scenario
    execute_sampling_cycle()
    return {"status": "ok", "applied_scenario": s}


class StaticSensorsConfig(BaseModel):
    use_static_ph: Optional[bool] = None
    static_ph_value: Optional[float] = None
    use_static_tds: Optional[bool] = None
    static_tds_value: Optional[float] = None
    use_static_orp: Optional[bool] = None
    static_orp_value: Optional[float] = None

@app.get("/api/static_sensors")
def get_static_sensors():
    """Returns current static baseline configuration for pH, TDS, and ORP."""
    return bridge.get_static_options()

@app.post("/api/static_sensors")
def update_static_sensors(config: StaticSensorsConfig):
    """Updates static baseline values and triggers an immediate re-evaluation."""
    bridge.set_static_options(
        use_ph=config.use_static_ph,
        ph_val=config.static_ph_value,
        use_tds=config.use_static_tds,
        tds_val=config.static_tds_value,
        use_orp=config.use_static_orp,
        orp_val=config.static_orp_value
    )
    force_sample_event.set()
    return {"status": "ok", "config": bridge.get_static_options()}

class SDCardConfigModel(BaseModel):
    enabled: bool
    persist: Optional[bool] = True

@app.get("/api/config/sdcard")
def get_sdcard_config():
    """Returns current SD card storage configuration and status."""
    return {
        "enabled": sdcard.is_enabled(),
        "status": sdcard.get_status()
    }

@app.post("/api/config/sdcard")
def update_sdcard_config(config: SDCardConfigModel):
    """Enables or disables SD card image logging dynamically."""
    sdcard.set_enabled(config.enabled, persist=config.persist if config.persist is not None else True)
    return {
        "status": "ok",
        "enabled": sdcard.is_enabled(),
        "sdcard": sdcard.get_status()
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            with state_lock:
                data = current_assessment.copy()
            data["seconds_until_next_sample"] = seconds_to_next_sample
            await websocket.send_json(data)
            await asyncio.sleep(1.0) # 1 Hz updates for live countdown
    except Exception:
        pass

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))

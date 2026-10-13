"""
AquaWatch: Edge-AI LoRaWAN Rural Water Quality Monitor
Arduino App Lab Entry Point (Qualcomm QRB2210 Linux)

Compliant with Arduino App Lab specification:
- python/main.py entry point
- Ends with App.run()
- Inter-core communication via Bridge
"""

import sys
import os
import threading
import logging
import uvicorn

# Ensure both current directory and python/ subfolder are on sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)
python_sub_dir = os.path.join(root_dir, "python")
if os.path.isdir(python_sub_dir):
    sys.path.insert(0, python_sub_dir)

logger = logging.getLogger("AquaWatchApp")

# Optional import of Arduino App Lab utilities
try:
    from arduino.app_utils import App, Bridge
    HAS_APP_LAB = True
except ImportError:
    HAS_APP_LAB = False

from dashboard_app import app

def start_web_server(host: str = "0.0.0.0", port: int = 8000):
    """Launches the SCADA Web Dashboard and API service."""
    uvicorn.run(app, host=host, port=port, log_level="info")

def main():
    print(f"================================================================")
    print(f" AQUAWATCH: Rural India Water Quality Monitoring App")
    print(f" Framework: Arduino App Lab (Qualcomm QRB2210 + STM32U585)")
    print(f" Web Dashboard & SCADA API: http://0.0.0.0:8000")
    print(f" Live Stream Video: http://0.0.0.0:8000/video_feed")
    print(f"================================================================")

    # Start FastAPI SCADA server in a daemon thread
    server_thread = threading.Thread(target=start_web_server, daemon=True)
    server_thread.start()

    if HAS_APP_LAB:
        # Mandatory call for all Arduino App Lab applications
        logger.info("Starting Arduino App Lab runtime loop...")
        App.run()
    else:
        # Standalone execution fallback (e.g. running via CLI or systemd)
        logger.info("Running in standalone server mode...")
        server_thread.join()

if __name__ == "__main__":
    main()


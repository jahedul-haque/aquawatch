/**
 * AquaWatch - Water Quality Monitor Client
 */

let ws = null;
let secondsRemaining = 600;
let timerInterval = null;
let lastImageTimestamp = 0;
let lastTelemetryTime = Date.now();
let lastSampleCount = -1;

function renderCountdown(secs) {
    const el = document.getElementById('countdownVal');
    if (!el) return;
    if (secs <= 0) {
        el.textContent = "Sampling...";
    } else if (secs >= 60) {
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        el.textContent = `${m}m ${s < 10 ? '0' : ''}${s}s`;
    } else {
        el.textContent = `${secs}s`;
    }
}

function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
        if (secondsRemaining > 0) {
            secondsRemaining--;
        }
        renderCountdown(secondsRemaining);
    }, 1000);
}

function refreshCameraImage() {
    const t = Date.now();
    const img = document.getElementById('rawCameraImg');
    if (img) {
        img.src = `/api/camera_snapshot?t=${t}`;
    }

    const timeEl = document.getElementById('lastSampleTime');
    if (timeEl) {
        const d = new Date();
        timeEl.textContent = d.toTimeString().split(' ')[0];
    }
    lastImageTimestamp = t;
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            lastTelemetryTime = Date.now();
            updateDashboard(data);
        } catch (err) {
            console.error("Failed to parse telemetry:", err);
        }
    };

    ws.onclose = () => {
        setTimeout(connectWebSocket, 2000);
    };
}

// Fallback polling if WebSocket is disconnected
function startPollingFallback() {
    setInterval(async () => {
        if (Date.now() - lastTelemetryTime > 3500) {
            try {
                const res = await fetch('/api/status');
                if (res.ok) {
                    const data = await res.json();
                    lastTelemetryTime = Date.now();
                    updateDashboard(data);
                }
            } catch (err) {
                // Ignore transient network errors
            }
        }
    }, 3000);
}

function updateDashboard(data) {
    if (!data) return;

    // 1. Countdown sync
    if (typeof data.seconds_until_next_sample === 'number') {
        if (secondsRemaining <= 5 && data.seconds_until_next_sample >= 580) {
            refreshCameraImage();
        }
        secondsRemaining = data.seconds_until_next_sample;
        renderCountdown(secondsRemaining);
    }

    // 2. Overall Status & WQI
    const level = data.safety_level || "SAFE";
    const wqi = (typeof data.wqi === 'number') ? data.wqi : 98;
    const badge = document.getElementById('overallBadge');
    const wqiEl = document.getElementById('overallWqi');

    if (badge) {
        if (level === "CRITICAL") {
            badge.className = "status-badge status-alert";
            badge.textContent = "Unsafe / Alert";
        } else if (level === "WARNING") {
            badge.className = "status-badge status-warn";
            badge.textContent = "Warning";
        } else {
            badge.className = "status-badge status-safe";
            badge.textContent = "Safe";
        }
    }
    if (wqiEl) {
        wqiEl.textContent = `WQI: ${wqi}`;
    }

    // 3. Classifications (Camera, Sensors, AS7341)
    const classes = data.classifications || {};

    // Camera
    const camClass = classes.camera || {};
    const camBadge = document.getElementById('camClassBadge');
    const camDesc = document.getElementById('camClassDesc');
    if (camBadge) {
        camBadge.textContent = camClass.title || "Clean Water";
        const cStatus = camClass.status || "SAFE";
        camBadge.className = `badge ${cStatus === 'CRITICAL' ? 'badge-alert' : (cStatus === 'WARNING' ? 'badge-warn' : 'badge-safe')}`;
    }
    if (camDesc) {
        camDesc.textContent = camClass.summary || camClass.description || "Clear water, no visible impurities";
    }

    // Sensors
    const sensClass = classes.sensors || {};
    const sensBadge = document.getElementById('sensorClassBadge');
    const sensDesc = document.getElementById('sensorClassDesc');
    if (sensBadge) {
        sensBadge.textContent = sensClass.title || "Normal";
        const sStatus = sensClass.status || "SAFE";
        sensBadge.className = `badge ${sStatus === 'CRITICAL' ? 'badge-alert' : (sStatus === 'WARNING' ? 'badge-warn' : 'badge-safe')}`;
    }
    if (sensDesc) {
        sensDesc.textContent = sensClass.summary || sensClass.description || "Normal readings. Turbidity within limits.";
    }

    // AS7341 Spectrometer
    const specClass = classes.as7341 || {};
    const specBadge = document.getElementById('specClassBadge');
    const specDesc = document.getElementById('specClassDesc');
    const specConnected = specClass.connected !== false && specClass.status !== "OFFLINE" && specClass.title !== "Not Connected";
    if (specBadge) {
        if (!specConnected) {
            specBadge.textContent = "Not Connected";
            specBadge.className = "badge badge-neutral";
        } else {
            specBadge.textContent = specClass.title || "Clean";
            const spStatus = specClass.status || "SAFE";
            specBadge.className = `badge ${spStatus === 'CRITICAL' ? 'badge-alert' : (spStatus === 'WARNING' ? 'badge-warn' : 'badge-safe')}`;
        }
    }
    if (specDesc) {
        if (!specConnected) {
            specDesc.textContent = "Spectrometer probe not connected.";
        } else {
            specDesc.textContent = specClass.summary || specClass.description || "Normal spectrum. No algae detected.";
        }
    }

    // 4. Sensor Readings & Connection Table
    const inv = data.sensor_inventory || {};
    const readings = data.sensor_readings || {};

    // Temperature
    const tempInv = inv.temperature || {};
    const cellTemp = document.getElementById('cellTemp');
    const statusTemp = document.getElementById('statusTemp');
    const isTempConn = tempInv.connected === true && !readings.temp_dummy && readings.temp_c > -50.0 && readings.temp_c !== 85.0;
    if (cellTemp) {
        if (!isTempConn) {
            cellTemp.textContent = "Not connected";
            cellTemp.className = "text-muted";
        } else {
            const val = tempInv.value !== undefined && tempInv.value !== null ? tempInv.value : readings.temp_c;
            cellTemp.textContent = `${Number(val).toFixed(1)} °C`;
            cellTemp.className = "";
        }
    }
    if (statusTemp) {
        statusTemp.textContent = isTempConn ? "Connected" : "Not connected";
        statusTemp.className = `status-pill ${isTempConn ? 'pill-ok' : 'pill-off'}`;
    }

    // Turbidity
    const turbInv = inv.turbidity || {};
    const cellTurb = document.getElementById('cellTurb');
    const statusTurb = document.getElementById('statusTurb');
    if (cellTurb) {
        if (turbInv.connected === false) {
            cellTurb.textContent = "Not connected";
            cellTurb.className = "text-muted";
        } else {
            const val = turbInv.value !== undefined ? turbInv.value : readings.turbidity_ntu;
            cellTurb.textContent = (val !== undefined && val !== null) ? `${Number(val).toFixed(2)} NTU` : "0.10 NTU";
            cellTurb.className = "";
        }
    }
    if (statusTurb) {
        if (turbInv.connected === false) {
            statusTurb.textContent = "Not connected";
            statusTurb.className = "status-pill pill-off";
        } else {
            const val = turbInv.value !== undefined ? turbInv.value : readings.turbidity_ntu;
            if (val > 5.0) {
                statusTurb.textContent = "High";
                statusTurb.className = "status-pill pill-alert";
            } else {
                statusTurb.textContent = "Connected";
                statusTurb.className = "status-pill pill-ok";
            }
        }
    }

    // pH (Unequipped)
    const phInv = inv.ph || {};
    const cellPh = document.getElementById('cellPh');
    const statusPh = document.getElementById('statusPh');
    if (cellPh) {
        if (phInv.connected === false || readings.ph_dummy) {
            cellPh.textContent = "Not connected";
            cellPh.className = "text-muted";
        } else {
            const val = phInv.value !== undefined ? phInv.value : readings.ph;
            cellPh.textContent = (val !== undefined && val !== null) ? Number(val).toFixed(2) : "Not connected";
            cellPh.className = "";
        }
    }
    if (statusPh) {
        const isConn = phInv.connected && !readings.ph_dummy;
        statusPh.textContent = isConn ? "Connected" : "Not connected";
        statusPh.className = `status-pill ${isConn ? 'pill-ok' : 'pill-off'}`;
    }

    // ORP (Unequipped)
    const orpInv = inv.orp || {};
    const cellOrp = document.getElementById('cellOrp');
    const statusOrp = document.getElementById('statusOrp');
    if (cellOrp) {
        if (orpInv.connected === false || readings.orp_dummy) {
            cellOrp.textContent = "Not connected";
            cellOrp.className = "text-muted";
        } else {
            const val = orpInv.value !== undefined ? orpInv.value : readings.orp_mv;
            cellOrp.textContent = (val !== undefined && val !== null) ? `${Math.round(val)} mV` : "Not connected";
            cellOrp.className = "";
        }
    }
    if (statusOrp) {
        const isConn = orpInv.connected && !readings.orp_dummy;
        statusOrp.textContent = isConn ? "Connected" : "Not connected";
        statusOrp.className = `status-pill ${isConn ? 'pill-ok' : 'pill-off'}`;
    }

    // TDS (Unequipped)
    const tdsInv = inv.tds || {};
    const cellTds = document.getElementById('cellTds');
    const statusTds = document.getElementById('statusTds');
    if (cellTds) {
        if (tdsInv.connected === false || readings.tds_dummy) {
            cellTds.textContent = "Not connected";
            cellTds.className = "text-muted";
        } else {
            const val = tdsInv.value !== undefined ? tdsInv.value : readings.tds_ppm;
            cellTds.textContent = (val !== undefined && val !== null) ? `${Math.round(val)} ppm` : "Not connected";
            cellTds.className = "";
        }
    }
    if (statusTds) {
        const isConn = tdsInv.connected && !readings.tds_dummy;
        statusTds.textContent = isConn ? "Connected" : "Not connected";
        statusTds.className = `status-pill ${isConn ? 'pill-ok' : 'pill-off'}`;
    }

    // AS7341 Spectrometer
    const specInv = inv.spectral || {};
    const cellSpectral = document.getElementById('cellSpectral');
    const statusSpectral = document.getElementById('statusSpectral');
    const isSpecTableConn = specInv.connected === true;
    if (cellSpectral) {
        cellSpectral.textContent = isSpecTableConn ? "Connected" : "Not connected";
        cellSpectral.className = isSpecTableConn ? "" : "text-muted";
    }
    if (statusSpectral) {
        statusSpectral.textContent = isSpecTableConn ? "Connected" : "Not connected";
        statusSpectral.className = `status-pill ${isSpecTableConn ? 'pill-ok' : 'pill-off'}`;
    }

    // Camera Hardware
    const camInv = inv.camera || {};
    const cellCamera = document.getElementById('cellCamera');
    const statusCamera = document.getElementById('statusCamera');
    const camStatusHeader = document.getElementById('cameraStatus');
    if (cellCamera) {
        cellCamera.textContent = camInv.connected === false ? "Not connected" : "Connected";
        cellCamera.className = camInv.connected === false ? "text-muted" : "";
    }
    if (statusCamera) {
        statusCamera.textContent = camInv.connected === false ? "Not connected" : "Connected";
        statusCamera.className = `status-pill ${camInv.connected === false ? 'pill-off' : 'pill-ok'}`;
    }
    if (camStatusHeader) {
        camStatusHeader.textContent = camInv.connected === false ? "Not connected" : "Connected";
    }

    // 4b. AS7341 Spectral Channels Breakdown
    const specChannels = specInv.channels || {};
    const specStatusBadge = document.getElementById('spectralStatusBadge');
    if (specStatusBadge) {
        specStatusBadge.textContent = isSpecTableConn ? "Connected" : "Not connected";
        specStatusBadge.className = `badge-subtle ${isSpecTableConn ? 'pill-ok' : 'pill-off'}`;
    }

    const chMap = {
        'specF1': specChannels.f1_415,
        'specF2': specChannels.f2_445,
        'specF3': specChannels.f3_480,
        'specF4': specChannels.f4_515,
        'specF5': specChannels.f5_555,
        'specF6': specChannels.f6_590,
        'specF7': specChannels.f7_630,
        'specF8': specChannels.f8_680,
        'specClear': specChannels.clear,
        'specNIR': specChannels.nir
    };

    for (const [elemId, countVal] of Object.entries(chMap)) {
        const el = document.getElementById(elemId);
        if (el) {
            if (!isSpecTableConn || countVal === undefined || countVal === null) {
                el.textContent = "--";
                el.classList.add("text-muted");
            } else {
                el.textContent = Number(countVal).toLocaleString();
                el.classList.remove("text-muted");
            }
        }
    }

    const ndaiEl = document.getElementById('specIndexNdai');
    if (ndaiEl) {
        if (!isSpecTableConn || specInv.algae_ndai === undefined || specInv.algae_ndai === null) {
            ndaiEl.textContent = "--";
        } else {
            const raw = Number(specInv.algae_ndai);
            const delta = (specInv.delta_ndai !== undefined && specInv.delta_ndai !== null) ? Number(specInv.delta_ndai) : null;
            if (delta !== null && (specInv.calibrated || Math.abs(raw - delta) > 0.05)) {
                ndaiEl.textContent = `${delta >= 0 ? '+' : ''}${delta.toFixed(3)} (Raw: ${raw >= 0 ? '+' : ''}${raw.toFixed(2)})`;
            } else {
                ndaiEl.textContent = `${raw >= 0 ? '+' : ''}${raw.toFixed(3)}`;
            }
        }
    }

    const cdomEl = document.getElementById('specIndexCdom');
    if (cdomEl) {
        if (!isSpecTableConn || specInv.cdom_index === undefined || specInv.cdom_index === null) {
            cdomEl.textContent = "--";
        } else {
            const rawC = Number(specInv.cdom_index);
            const deltaC = (specInv.delta_cdom !== undefined && specInv.delta_cdom !== null) ? Number(specInv.delta_cdom) : null;
            if (deltaC !== null && (specInv.calibrated || Math.abs(rawC - deltaC) > 0.05)) {
                cdomEl.textContent = `${deltaC >= 0 ? '+' : ''}${deltaC.toFixed(3)} (Raw: ${rawC >= 0 ? '+' : ''}${rawC.toFixed(2)})`;
            } else {
                cdomEl.textContent = `${rawC >= 0 ? '+' : ''}${rawC.toFixed(3)}`;
            }
        }
    }


    // 4c. System Calibration Status
    const calib = data.calibration || {};
    const calibBadge = document.getElementById('calibStatusBadge');
    const calibStatusText = document.getElementById('calibStatusText');
    if (calibBadge) {
        if (calib.is_calibrated) {
            calibBadge.textContent = calib.status_label || "Calibrated";
            calibBadge.className = "badge badge-safe";
        } else {
            calibBadge.textContent = "Factory Default";
            calibBadge.className = "badge-subtle";
        }
    }
    if (calibStatusText) {
        if (calib.status_label && calib.is_calibrated) {
            calibStatusText.innerHTML = `Active Profile: <strong>${calib.status_label}</strong> (${calib.profiles_count || 0} category profile(s) trained).`;
        } else {
            calibStatusText.textContent = "Current profile: Factory default (Uncalibrated)";
        }
    }

    // 5. LoRaWAN Telemetry & Diagnostics
    const lora = data.lorawan || {};
    const loraBadge = document.getElementById('loraStatusBadge');
    const hwStatusEl = document.getElementById('loraHwStatus');
    const devEuiEl = document.getElementById('loraDevEui');
    const appSKeyEl = document.getElementById('loraAppSKey');
    const modemEl = document.getElementById('loraModem');
    const regionEl = document.getElementById('loraRegion');
    const btnCopyEui = document.getElementById('btnCopyEui');
    const btnSendLora = document.getElementById('btnSendLora');
    const timeEl = document.getElementById('loraLastTime');
    const portEl = document.getElementById('loraLastPort');
    const hexEl = document.getElementById('loraPayloadHex');
    const lenEl = document.getElementById('loraPayloadLen');
    const decEl = document.getElementById('loraPayloadDecoded');
    const txStatusEl = document.getElementById('loraTxStatus');

    const nodeFound = lora.node_found === true;

    if (loraBadge) {
        loraBadge.textContent = nodeFound ? "Connected" : "Node not found";
        loraBadge.className = `badge-subtle ${nodeFound ? 'pill-ok' : 'pill-off'}`;
    }

    if (hwStatusEl) {
        hwStatusEl.textContent = nodeFound ? `Connected (${lora.port})` : "Node not found (No serial response)";
    }

    if (devEuiEl) {
        devEuiEl.textContent = nodeFound ? (lora.dev_eui || "Unprogrammed") : "Not connected";
    }

    if (btnCopyEui) {
        btnCopyEui.style.display = (nodeFound && lora.dev_eui) ? "inline-block" : "none";
    }

    if (appSKeyEl) {
        appSKeyEl.textContent = nodeFound ? (lora.appskey_masked || lora.appskey || "Not configured") : "Not connected";
    }

    if (modemEl) {
        modemEl.textContent = nodeFound ? (lora.modem_model || "Ebyte E78-900M22S") : "Not detected";
    }

    if (regionEl) {
        regionEl.textContent = nodeFound ? (lora.region || "IN865 (India)") : "Not connected";
    }

    const btnJoinLora = document.getElementById('btnJoinLora');
    if (btnJoinLora) {
        btnJoinLora.disabled = !nodeFound;
    }

    if (btnSendLora) {
        btnSendLora.disabled = !nodeFound;
    }

    // Last Uplink Transmission
    const lastUplink = (nodeFound && (lora.last_uplink || data.last_uplink)) ? (lora.last_uplink || data.last_uplink) : null;
    if (lastUplink && lastUplink.status !== "NODE_NOT_FOUND") {
        if (timeEl && lastUplink.timestamp) timeEl.textContent = lastUplink.timestamp;
        if (portEl) portEl.textContent = `Port ${lastUplink.f_port || 10} (${lastUplink.type || 'HEARTBEAT'})`;
        if (hexEl) hexEl.textContent = lastUplink.payload_hex_spaced || lastUplink.payload_hex || "00 00 00 00";
        if (lenEl && lastUplink.bytes_length) lenEl.textContent = `${lastUplink.bytes_length} bytes`;
        if (decEl) decEl.textContent = lastUplink.summary || "Normal transmission";
        if (txStatusEl) {
            const desc = lastUplink.status_description || lastUplink.status || 'DELIVERED';
            txStatusEl.textContent = `Status: ${desc}`;
            txStatusEl.style.color = (lastUplink.status === 'DELIVERED') ? '#1a7f37' : '#cf222e';
        }
    } else {
        if (timeEl) timeEl.textContent = "None";
        if (portEl) portEl.textContent = "--";
        if (hexEl) hexEl.textContent = nodeFound ? "No transmission yet" : "No transmission";
        if (lenEl) lenEl.textContent = "--";
        if (decEl) decEl.textContent = nodeFound ? "Modem idle - ready for transmission" : "No LoRa node connected";
        if (txStatusEl) {
            txStatusEl.textContent = nodeFound ? `Status: Idle (Connected on ${lora.port})` : "Status: LoRa node not found";
            txStatusEl.style.color = "#57606a";
        }
    }

    const diagLoraEl = document.getElementById('loraStatus');
    if (diagLoraEl) {
        diagLoraEl.textContent = nodeFound ? `Active (${lora.serial_port || lora.port})` : "Offline (Node not found)";
    }

    const sd = data.sdcard || {};
    const sdEl = document.getElementById('sdStatus');
    if (sdEl) {
        sdEl.textContent = sd.enabled === false ? "Disabled" : `Active (${sd.total_samples_saved || 0} saved)`;
    }

    // Image update check
    if (readings.samples !== undefined && readings.samples !== lastSampleCount) {
        if (lastSampleCount !== -1) {
            refreshCameraImage();
        }
        lastSampleCount = readings.samples;
    }

    const now = Date.now();
    if (lastImageTimestamp === 0 || (now - lastImageTimestamp > 65000)) {
        refreshCameraImage();
    }
}

async function sampleNow() {
    const btn = document.getElementById('btnSampleNow');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    const origText = btn.textContent;
    btn.textContent = "Sampling...";

    try {
        await fetch('/api/sample_now', { method: 'POST' });
        await new Promise(resolve => setTimeout(resolve, 1800));

        const res = await fetch('/api/status');
        if (res.ok) {
            const data = await res.json();
            updateDashboard(data);
        }

        refreshCameraImage();
        secondsRemaining = 60;
        renderCountdown(secondsRemaining);

        btn.textContent = "Done!";
        setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
        }, 1000);
    } catch (err) {
        console.error("Sampling error:", err);
        btn.textContent = "Error";
        setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
        }, 1500);
    }
}

async function injectSelectedScenario(scenario) {
    const select = document.getElementById('simScenarioSelect');
    if (select) select.disabled = true;

    try {
        const res = await fetch('/api/simulate/scenario', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenario: scenario })
        });

        if (res.ok) {
            const statusRes = await fetch('/api/status');
            if (statusRes.ok) {
                const data = await statusRes.json();
                updateDashboard(data);
            }
            refreshCameraImage();
            secondsRemaining = 60;
            renderCountdown(secondsRemaining);
        }
    } catch (err) {
        console.error("Scenario injection error:", err);
    } finally {
        if (select) select.disabled = false;
    }
}

function copyDevEui() {
    const el = document.getElementById('loraDevEui');
    const btn = document.getElementById('btnCopyEui');
    if (!el) return;
    const text = el.textContent.trim();
    navigator.clipboard.writeText(text).then(() => {
        if (btn) {
            const orig = btn.textContent;
            btn.textContent = "Copied!";
            setTimeout(() => { btn.textContent = orig; }, 1500);
        }
    }).catch(err => {
        console.error("Clipboard copy failed:", err);
    });
}

function toggleSetDevEuiUI() {
    const box = document.getElementById('setEuiBox');
    const input = document.getElementById('inputNewDevEui');
    const currentEui = document.getElementById('loraDevEui')?.textContent.trim();
    if (!box) return;
    if (box.style.display === 'none' || box.style.display === '') {
        box.style.display = 'block';
        if (input && currentEui && currentEui !== "Not connected" && currentEui !== "Node not found") {
            input.value = currentEui;
        }
        if (input) input.focus();
    } else {
        box.style.display = 'none';
    }
}

async function setDevEui() {
    const input = document.getElementById('inputNewDevEui');
    const msgEl = document.getElementById('setEuiMsg');
    const btn = document.getElementById('btnSaveDevEui');
    if (!input || !btn || btn.disabled) return;

    const val = input.value.trim().toUpperCase();
    if (!/^[0-9A-F]{16}$/.test(val)) {
        if (msgEl) {
            msgEl.textContent = "Error: DevEUI must be exactly 16 hexadecimal characters (0-9, A-F).";
            msgEl.style.color = "#cf222e";
        }
        return;
    }

    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "Saving...";
    if (msgEl) {
        msgEl.textContent = "Sending AT+CDEVEUI command to modem...";
        msgEl.style.color = "#57606a";
    }

    try {
        const res = await fetch('/api/lorawan/deveui', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deveui: val })
        });
        const resData = await res.json();

        if (res.ok) {
            if (msgEl) {
                msgEl.textContent = "Success: DevEUI programmed to modem!";
                msgEl.style.color = "#1a7f37";
            }
            const statusRes = await fetch('/api/status');
            if (statusRes.ok) {
                const data = await statusRes.json();
                updateDashboard(data);
            }
            setTimeout(() => {
                toggleSetDevEuiUI();
                if (msgEl) msgEl.textContent = "";
            }, 1200);
        } else {
            if (msgEl) {
                msgEl.textContent = resData.message || "Failed to set DevEUI on modem.";
                msgEl.style.color = "#cf222e";
            }
        }
    } catch (err) {
        console.error("Set DevEUI error:", err);
        if (msgEl) {
            msgEl.textContent = "Network error while programming DevEUI.";
            msgEl.style.color = "#cf222e";
        }
    } finally {
        btn.textContent = orig;
        btn.disabled = false;
    }
}

async function probeLoraNode() {
    const btn = document.getElementById('btnProbeLora');
    const txStatus = document.getElementById('loraTxStatus');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "Scanning...";
    if (txStatus) txStatus.textContent = "Scanning serial ports with AT command...";

    try {
        const res = await fetch('/api/lorawan/scan', { method: 'POST' });
        const resData = await res.json();
        
        const statusRes = await fetch('/api/status');
        if (statusRes.ok) {
            const data = await statusRes.json();
            updateDashboard(data);
        }

        if (resData.node_found) {
            btn.textContent = "Found!";
        } else {
            btn.textContent = "Not Found";
        }
        setTimeout(() => {
            btn.textContent = orig;
            btn.disabled = false;
        }, 1500);
    } catch (err) {
        console.error("Probe error:", err);
        btn.textContent = "Error";
        setTimeout(() => {
            btn.textContent = orig;
            btn.disabled = false;
        }, 1500);
    }
}

async function triggerLoraJoin() {
    const btn = document.getElementById('btnJoinLora');
    const txStatus = document.getElementById('loraTxStatus');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "Joining...";
    if (txStatus) {
        txStatus.textContent = "Executing AT+CJOIN... waiting for gateway response";
        txStatus.style.color = "#0969da";
    }

    if (typeof executeAtCommand === 'function') {
        executeAtCommand('AT+CJOIN');
    }

    try {
        const res = await fetch('/api/lorawan/join', { method: 'POST' });
        const data = await res.json();

        const statusRes = await fetch('/api/status');
        if (statusRes.ok) {
            const sData = await statusRes.json();
            updateDashboard(sData);
        }

        const isOk = data.joined || (data.response && (data.response.includes('OK') || data.response.includes('ASR650')));
        if (isOk) {
            btn.textContent = "Join Sent!";
            if (txStatus) {
                txStatus.textContent = `Status: AT+CJOIN dispatched (${data.message || 'Waiting for gateway'})`;
                txStatus.style.color = "#1a7f37";
            }
        } else {
            btn.textContent = "Join Error";
            if (txStatus) {
                txStatus.textContent = `Status: Join failed (${data.message || data.response || 'Error'})`;
                txStatus.style.color = "#cf222e";
            }
        }
        setTimeout(() => {
            btn.textContent = orig;
            btn.disabled = false;
        }, 2000);
    } catch (err) {
        console.error("Join error:", err);
        btn.textContent = "Error";
        if (txStatus) {
            txStatus.textContent = `Status: Join error (${err.message || err})`;
            txStatus.style.color = "#cf222e";
        }
        setTimeout(() => {
            btn.textContent = orig;
            btn.disabled = false;
        }, 2000);
    }
}

async function sendTestUplink() {
    const btn = document.getElementById('btnSendLora');
    const txStatus = document.getElementById('loraTxStatus');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    const orig = btn.textContent;
    btn.textContent = "Sending...";
    if (txStatus) {
        txStatus.textContent = "Dispatching AT+DTRX packet to LoRaWAN...";
        txStatus.style.color = "#0969da";
    }

    try {
        const res = await fetch('/api/lorawan/send_now', { method: 'POST' });
        const resData = await res.json();
        const uplink = resData.uplink || {};

        if (typeof appendTerminalLine === 'function' && uplink.payload_hex) {
            const ts = typeof getTerminalTimestamp === 'function' ? getTerminalTimestamp() : '';
            appendTerminalLine('tx', `${ts} >> AT+DTRX=0,${uplink.f_port || 10},${uplink.bytes_length || 15},${uplink.payload_hex}`);
            if (uplink.modem_response) {
                const isErr = uplink.status === 'FAILED';
                appendTerminalLine(isErr ? 'rx-err' : 'rx', `${ts} << ${uplink.modem_response}`);
            }
        }

        const statusRes = await fetch('/api/status');
        if (statusRes.ok) {
            const data = await statusRes.json();
            updateDashboard(data);
        }

        if (uplink.status === 'DELIVERED') {
            btn.textContent = "Sent!";
            setTimeout(() => {
                btn.textContent = orig;
                btn.disabled = false;
            }, 1200);
        } else {
            btn.textContent = "Failed";
            if (txStatus) {
                txStatus.textContent = `Status: ${uplink.status_description || 'FAILED'}`;
                txStatus.style.color = "#cf222e";
            }
            setTimeout(() => {
                btn.textContent = orig;
                btn.disabled = false;
            }, 2000);
        }
    } catch (err) {
        console.error("Uplink error:", err);
        btn.textContent = "Error";
        setTimeout(() => {
            btn.textContent = orig;
            btn.disabled = false;
        }, 1500);
    }
}

async function calibrateCurrentSample() {
    const select = document.getElementById('calibCategorySelect');
    const btn = document.getElementById('btnCalibLearn');
    if (!select || !btn || btn.disabled) return;

    const category = select.value;
    const catLabel = select.options[select.selectedIndex]?.text || category;
    btn.disabled = true;
    const origText = btn.textContent;
    btn.textContent = "Learning...";

    try {
        const res = await fetch('/api/calibrate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category: category })
        });

        if (res.ok) {
            const resData = await res.json();
            const statusBox = document.getElementById('calibStatusText');
            if (statusBox) {
                statusBox.innerHTML = `Learned current sample as <strong>${catLabel}</strong>. Prototype saved.`;
            }
            const statusRes = await fetch('/api/status');
            if (statusRes.ok) {
                const data = await statusRes.json();
                updateDashboard(data);
            }
            btn.textContent = "Learned!";
            setTimeout(() => {
                btn.textContent = origText;
                btn.disabled = false;
            }, 1200);
        } else {
            const errData = await res.json().catch(() => ({}));
            btn.textContent = "Failed";
            setTimeout(() => {
                btn.textContent = origText;
                btn.disabled = false;
            }, 1500);
        }
    } catch (err) {
        console.error("Calibration error:", err);
        btn.textContent = "Error";
        setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
        }, 1500);
    }
}

async function resetCalibration() {
    const btn = document.getElementById('btnCalibReset');
    if (!btn || btn.disabled) return;
    if (!confirm("Reset all calibration profiles and restore factory defaults?")) return;

    btn.disabled = true;
    const origText = btn.textContent;
    btn.textContent = "Resetting...";

    try {
        const res = await fetch('/api/calibrate/reset', { method: 'POST' });
        if (res.ok) {
            const statusRes = await fetch('/api/status');
            if (statusRes.ok) {
                const data = await statusRes.json();
                updateDashboard(data);
            }
            const statusBox = document.getElementById('calibStatusText');
            if (statusBox) {
                statusBox.textContent = "Current profile: Factory default (Uncalibrated)";
            }
            btn.textContent = "Reset!";
            setTimeout(() => {
                btn.textContent = origText;
                btn.disabled = false;
            }, 1000);
        } else {
            btn.textContent = "Failed";
            setTimeout(() => {
                btn.textContent = origText;
                btn.disabled = false;
            }, 1500);
        }
    } catch (err) {
        console.error("Reset calibration error:", err);
        btn.textContent = "Error";
        setTimeout(() => {
            btn.textContent = origText;
            btn.disabled = false;
        }, 1500);
    }
}

// ==========================================
// LoRa Direct Serial Passthrough Terminal
// ==========================================
const loraTerminalHistory = [];
let loraTerminalHistoryIdx = -1;

function getTerminalTimestamp() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `[${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}]`;
}

function appendTerminalLine(type, text) {
    const consoleEl = document.getElementById('loraTerminalOutput');
    if (!consoleEl) return;

    const line = document.createElement('div');
    line.className = `terminal-line terminal-${type}`;
    line.textContent = text;
    consoleEl.appendChild(line);

    // Keep console capped at 120 lines to prevent DOM bloat
    while (consoleEl.children.length > 120) {
        consoleEl.removeChild(consoleEl.firstChild);
    }

    // Auto-scroll to bottom
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function clearTerminal() {
    const consoleEl = document.getElementById('loraTerminalOutput');
    if (!consoleEl) return;
    consoleEl.innerHTML = '';
    appendTerminalLine('system', '// Terminal cleared. Ready for AT commands.');
}

async function executeAtCommand(cmd) {
    if (!cmd) return;
    const cleanCmd = cmd.trim();
    if (!cleanCmd) return;

    const ts = getTerminalTimestamp();
    appendTerminalLine('tx', `${ts} >> ${cleanCmd}`);

    const sendBtn = document.getElementById('btnSendTerminal');
    if (sendBtn) sendBtn.disabled = true;

    try {
        let resp = '';
        let isOk = false;

        const res = await fetch('/api/lorawan/at', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cleanCmd })
        });

        if (res.ok) {
            const data = await res.json();
            resp = data.response || '';
            isOk = true;
        } else {
            // Fallback GET
            const resGet = await fetch(`/api/lorawan/at?cmd=${encodeURIComponent(cleanCmd)}`);
            if (resGet.ok) {
                const data = await resGet.json();
                resp = data.response || '';
                isOk = true;
            }
        }

        const tsRx = getTerminalTimestamp();
        if (resp && resp.trim().length > 0) {
            const isErr = resp.includes('ERROR') || resp.includes('ERR:');
            appendTerminalLine(isErr ? 'rx-err' : 'rx', `${tsRx} << ${resp.trim()}`);
        } else if (isOk) {
            appendTerminalLine('system', `${tsRx} << [No response received from LoRa module]`);
        } else {
            appendTerminalLine('rx-err', `${tsRx} << [Failed to communicate with MCU Bridge]`);
        }

        // If the user executed a command that could update modem status, refresh dashboard
        const upper = cleanCmd.toUpperCase();
        if (upper.includes('DEVEUI') || upper.includes('JOIN') || upper.includes('STATUS') || upper.includes('CGMM')) {
            try {
                const statusRes = await fetch('/api/status');
                if (statusRes.ok) {
                    const statusData = await statusRes.json();
                    updateDashboard(statusData);
                }
            } catch (_) {}
        }
    } catch (err) {
        console.error('Terminal AT command error:', err);
        const tsErr = getTerminalTimestamp();
        appendTerminalLine('rx-err', `${tsErr} !! Network/RPC Error: ${err.message || err}`);
    } finally {
        if (sendBtn) sendBtn.disabled = false;
        const inputEl = document.getElementById('loraTerminalInput');
        if (inputEl) inputEl.focus();
    }
}

function sendTerminalInput() {
    const inputEl = document.getElementById('loraTerminalInput');
    if (!inputEl) return;
    const cmd = inputEl.value.trim() || 'AT';

    // Store in command history
    if (loraTerminalHistory.length === 0 || loraTerminalHistory[loraTerminalHistory.length - 1] !== cmd) {
        loraTerminalHistory.push(cmd);
        if (loraTerminalHistory.length > 50) loraTerminalHistory.shift();
    }
    loraTerminalHistoryIdx = loraTerminalHistory.length;

    inputEl.value = '';
    executeAtCommand(cmd);
}

function sendTerminalChip(cmd) {
    const inputEl = document.getElementById('loraTerminalInput');
    if (inputEl) inputEl.value = cmd;
    executeAtCommand(cmd);
}

function initTerminalInputListeners() {
    const inputEl = document.getElementById('loraTerminalInput');
    if (!inputEl) return;

    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            sendTerminalInput();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (loraTerminalHistory.length > 0) {
                if (loraTerminalHistoryIdx > 0) {
                    loraTerminalHistoryIdx--;
                }
                inputEl.value = loraTerminalHistory[loraTerminalHistoryIdx] || '';
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (loraTerminalHistoryIdx < loraTerminalHistory.length - 1) {
                loraTerminalHistoryIdx++;
                inputEl.value = loraTerminalHistory[loraTerminalHistoryIdx] || '';
            } else {
                loraTerminalHistoryIdx = loraTerminalHistory.length;
                inputEl.value = '';
            }
        }
    });
}

window.addEventListener('DOMContentLoaded', () => {
    startTimer();
    connectWebSocket();
    startPollingFallback();
    refreshCameraImage();
    initTerminalInputListeners();
});

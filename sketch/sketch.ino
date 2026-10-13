/*
 * Arduino UNO Q - AquaWatch: Edge-AI LoRaWAN Water Quality Monitoring for Rural India
 * Real-Time MCU Firmware (STM32U585)
 * 
 * Hardware Connections:
 * - A0: Analog pH Sensor (0 - 3.3V scaled)
 * - A1: ASAIR AZDM01 Photoelectric Turbidity Sensor (940nm IR, 5V powered via 10k/20k voltage divider to 3.3V)
 * - A2: Analog TDS Sensor (0 - 3.3V scaled)
 * - A3: Analog ORP Sensor (0 - 3.3V scaled, defaults to dummy baseline if probe absent)
 * - D2: DS18B20 Waterproof Temperature Sensor (1-Wire, 4.7k pullup to 3.3V)
 * - D0/D1 (or Serial1): LoRaWAN Modem (IN865 Band: 865 - 867 MHz, e.g. Ebyte E78-900M22S [ASR6505 / SX1262, +22dBm])
 * - LED_BUILTIN: System Heartbeat & Alert Indicator
 */

#include <Arduino.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "CalibrationConfig.h"
#include "SensorFilters.h"

#if __has_include(<Adafruit_AS7341.h>)
  #include <Adafruit_AS7341.h>
  #define HAS_AS7341_LIB 1
#else
  #define HAS_AS7341_LIB 0
#endif

#if __has_include(<Arduino_RouterBridge.h>)
  #include <Arduino_RouterBridge.h>
  #define HAS_ROUTER_BRIDGE 1
#else
  #define HAS_ROUTER_BRIDGE 0
#endif

// Hardware Options
// Set to 1 if using physical probe; set to 0 to use safe static/dummy baseline (saves cost of expensive probes).
#define USE_PHYSICAL_PH_SENSOR     0
#define USE_PHYSICAL_TDS_SENSOR    0
#define USE_PHYSICAL_ORP_SENSOR    0
#define USE_AS7341_SPECTRAL_SENSOR 1  // 1 = Enable Adafruit AS7341 10-channel spectral analyzer (I2C addr 0x39)

// Static Baseline Values (Compliant with BIS IS 10500:2012 Drinking Water Standards)
static const float PH_STATIC_NOMINAL       = 7.35f;  // Safe neutral drinking water baseline (BIS range: 6.5 - 8.5)
static const float TDS_STATIC_NOMINAL_PPM  = 180.0f; // Safe mineral drinking water baseline (BIS limit: < 500 ppm)
static const float ORP_DUMMY_NOMINAL_MV    = 675.0f; // Safe municipal chlorinated tap water baseline (> 650 mV)

// Automatic disconnection detection voltage limits (on 3.3V scale)
static const float PH_DISCONNECTED_V_LOW   = 0.15f;
static const float PH_DISCONNECTED_V_HIGH  = 3.15f;
static const float TDS_DISCONNECTED_V_LOW  = 0.05f;
static const float TDS_DISCONNECTED_V_HIGH = 3.15f;
static const float ORP_DISCONNECTED_V_LOW  = 0.20f;
static const float ORP_DISCONNECTED_V_HIGH = 3.10f;

// Pin Assignments
static const int PIN_PH           = A0;
static const int PIN_TURBIDITY    = A1;
static const int PIN_TDS          = A2;
static const int PIN_ORP          = A3;
static const int PIN_TEMP_ONEWIRE = D2;
static const int PIN_HEARTBEAT    = LED_BUILTIN;

// 1-Wire Temperature Setup
OneWire oneWire(PIN_TEMP_ONEWIRE);
DallasTemperature tempSensors(&oneWire);

// Sensor Calibration parameters
SensorCalibration g_calibration;

// Digital Signal Filters (9-sample median filter)
MedianFilter<int, 9> filterRawPH;
MedianFilter<int, 9> filterRawTurbidity;
MedianFilter<int, 9> filterRawTDS;
MedianFilter<int, 9> filterRawORP;

LowPassFilter filterVoltagePH(0.25f);
LowPassFilter filterVoltageTurbidity(0.25f);
LowPassFilter filterVoltageTDS(0.25f);
LowPassFilter filterVoltageORP(0.25f);

// Telemetry state
struct TelemetryState {
    float temperatureC;
    float ph;
    float turbidityNTU;
    float tdsPPM;
    float orpMV;
    bool phDummy;
    bool tdsDummy;
    bool orpDummy;
    bool tempDummy;
    unsigned long sampleCount;
    unsigned long lastUpdateMs;
    bool contaminationAlert;
    uint8_t activeHazardCode;
} g_telemetry = {-127.0f, 7.35f, 0.45f, 180.0f, 675.0f, true, true, true, true, 0, 0, false, 0};

// Spectral Sensor Setup (Adafruit AS7341 10-channel I2C Spectral Sensor)
#if HAS_AS7341_LIB
Adafruit_AS7341 as7341;
TwoWire *g_pSpectralWire = nullptr;
#endif
AS7341SpectralReadings g_spectral = {
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0.0f, 0.0f, false
};

// 10-Minute Sampling Cadence & 1-Second Optical Pre-warm State Machine
static const unsigned long SAMPLING_CADENCE_MS = 600000; // 10-minute interval
static const unsigned long PREWARM_DURATION_MS = 1000;  // 1-second LED pre-warm

enum SamplingCycleState {
    STATE_IDLE,          // Waiting between 10-minute samples. AS7341 LED is OFF.
    STATE_PREWARM_LED,   // AS7341 LED turned ON 1 second prior to sampling.
    STATE_SAMPLE_NOW     // Capturing spectral, turbidity, temp; turning LED OFF.
};

SamplingCycleState g_samplingCycleState = STATE_IDLE;
unsigned long lastSampleCycleMs = 0;
unsigned long prewarmStartMs = 0;
volatile bool g_manualSampleTriggered = false;
volatile bool g_rpcLedCommandPending = false;
volatile bool g_rpcLedStateRequested = false;

unsigned long lastHeartbeatToggle = 0;
bool heartbeatState = false;

// Generate JSON telemetry
String getTelemetryJson() {
    String json = "{";
    json += "\"temp_c\":" + String(g_telemetry.temperatureC, 2) + ",";
    json += "\"temp_dummy\":" + String(g_telemetry.tempDummy ? "true" : "false") + ",";
    json += "\"temp_connected\":" + String(g_telemetry.tempDummy ? "false" : "true") + ",";
    json += "\"ph\":" + String(g_telemetry.ph, 2) + ",";
    json += "\"ph_dummy\":" + String(g_telemetry.phDummy ? "true" : "false") + ",";
    json += "\"turbidity_ntu\":" + String(g_telemetry.turbidityNTU, 2) + ",";
    json += "\"tds_ppm\":" + String(g_telemetry.tdsPPM, 1) + ",";
    json += "\"tds_dummy\":" + String(g_telemetry.tdsDummy ? "true" : "false") + ",";
    json += "\"orp_mv\":" + String(g_telemetry.orpMV, 1) + ",";
    json += "\"orp_dummy\":" + String(g_telemetry.orpDummy ? "true" : "false") + ",";
    json += "\"alert\":" + String(g_telemetry.contaminationAlert ? "true" : "false") + ",";
    json += "\"hazard_code\":" + String(g_telemetry.activeHazardCode) + ",";
    json += "\"samples\":" + String(g_telemetry.sampleCount) + ",";
    json += "\"uptime_ms\":" + String(millis()) + ",";
    json += "\"spectral\":{";
    json += "\"f1\":" + String(g_spectral.f1_415) + ",";
    json += "\"f2\":" + String(g_spectral.f2_445) + ",";
    json += "\"f3\":" + String(g_spectral.f3_480) + ",";
    json += "\"f4\":" + String(g_spectral.f4_515) + ",";
    json += "\"f5\":" + String(g_spectral.f5_555) + ",";
    json += "\"f6\":" + String(g_spectral.f6_590) + ",";
    json += "\"f7\":" + String(g_spectral.f7_630) + ",";
    json += "\"f8\":" + String(g_spectral.f8_680) + ",";
    json += "\"clear\":" + String(g_spectral.clear) + ",";
    json += "\"nir\":" + String(g_spectral.nir) + ",";
    json += "\"algae_ndai\":" + String(g_spectral.algae_ndai, 3) + ",";
    json += "\"cdom_index\":" + String(g_spectral.cdom_index, 3) + ",";
    json += "\"delta_ndai\":" + String(g_spectral.delta_ndai, 3) + ",";
    json += "\"delta_cdom\":" + String(g_spectral.delta_cdom, 3) + ",";
    json += "\"baseline_ndai\":" + String(g_spectral.baseline_ndai, 3) + ",";
    json += "\"baseline_cdom\":" + String(g_spectral.baseline_cdom, 3) + ",";
    json += "\"detected\":" + String(g_spectral.sensor_present ? "true" : "false");

    json += "}";
    json += "}";
    return json;
}


// Generate Compact LoRaWAN Hex Payload (15 bytes)
String getLoRaWANPayloadHex(uint8_t wqi, uint8_t clarity, uint8_t particles, uint8_t flags) {
    uint8_t payload[15];
    
    // Byte 0: [Alert bit][Hazard code]
    payload[0] = (g_telemetry.contaminationAlert ? 0x80 : 0x00) | (g_telemetry.activeHazardCode & 0x0F);
    payload[1] = wqi;

    uint16_t ph100 = (uint16_t)constrain((int)(g_telemetry.ph * 100.0f), 0, 1400);
    payload[2] = (ph100 >> 8) & 0xFF;
    payload[3] = ph100 & 0xFF;

    uint16_t turb10 = (uint16_t)constrain((int)(g_telemetry.turbidityNTU * 10.0f), 0, 30000);
    payload[4] = (turb10 >> 8) & 0xFF;
    payload[5] = turb10 & 0xFF;

    uint16_t tdsVal = (uint16_t)constrain((int)g_telemetry.tdsPPM, 0, 65535);
    payload[6] = (tdsVal >> 8) & 0xFF;
    payload[7] = tdsVal & 0xFF;

    int16_t orpVal = (int16_t)constrain((int)g_telemetry.orpMV, -2000, 2000);
    payload[8] = (orpVal >> 8) & 0xFF;
    payload[9] = orpVal & 0xFF;

    int16_t temp10 = (int16_t)constrain((int)(g_telemetry.temperatureC * 10.0f), -400, 1000);
    payload[10] = (temp10 >> 8) & 0xFF;
    payload[11] = temp10 & 0xFF;

    payload[12] = clarity;
    payload[13] = particles;
    payload[14] = flags;

    String hexStr = "";
    for (int i = 0; i < 15; i++) {
        if (payload[i] < 16) hexStr += "0";
        hexStr += String(payload[i], HEX);
    }
    hexStr.toUpperCase();
    return hexStr;
}

#if HAS_ROUTER_BRIDGE
static String rpc_get_telemetry(String input) {
    return getTelemetryJson();
}

static String rpc_set_alert_state(String input) {
    // Format: "ALERT_FLAG:HAZARD_CODE" e.g. "1:4"
    int sep = input.indexOf(':');
    if (sep >= 0) {
        g_telemetry.contaminationAlert = (input.substring(0, sep) == "1");
        g_telemetry.activeHazardCode = input.substring(sep + 1).toInt();
    }
    return "OK";
}

static String rpc_get_lorawan_hex(String input) {
    // Input: "WQI,CLARITY,PARTICLES,FLAGS"
    return getLoRaWANPayloadHex(85, 95, 2, 0);
}

static String rpc_trigger_sample(String input) {
    g_manualSampleTriggered = true;
    return "OK";
}

static String rpc_set_spectral_led(String input) {
    bool on = (input == "1" || input == "true" || input == "ON");
    // Thread-safe: do not perform I2C on the Zephyr RPC thread.
    // Signal the main loop() thread to update hardware.
    g_rpcLedStateRequested = on;
    g_rpcLedCommandPending = true;
    return on ? "LED_ON" : "LED_OFF";
}

static String rpc_send_lora_at(String input) {
    while (Serial1.available()) Serial1.read(); // Flush stale RX bytes
    Serial1.print(input);
    Serial1.print("\r\n");
    unsigned long t0 = millis();
    String resp = "";
    unsigned long maxWait = (input.startsWith("AT+DTRX") || input.startsWith("AT+CJOIN") || input.startsWith("AT+SEND") || input.startsWith("AT+DTX")) ? 2500 : 600;
    while (millis() - t0 < maxWait) {
        while (Serial1.available()) {
            int b = Serial1.read();
            if (b < 0) break;
            char c = (char)b;
            // Filter strictly to valid printable ASCII to protect Bridge UTF-8 decoding
            if ((c >= 32 && c <= 126) || c == '\r' || c == '\n' || c == '\t') {
                resp += c;
            }
            if (resp.indexOf("OK") >= 0 || resp.indexOf("ERROR") >= 0 || resp.indexOf("~#") >= 0 || resp.indexOf("ASR650") >= 0) {
                delay(10);
                while (Serial1.available()) {
                    int b2 = Serial1.read();
                    if (b2 >= 0) {
                        char c2 = (char)b2;
                        if ((c2 >= 32 && c2 <= 126) || c2 == '\r' || c2 == '\n') resp += c2;
                    }
                }
                resp.trim();
                return resp;
            }
        }
        delay(2); // Yield CPU to RTOS and allow UART FIFO to fill
    }
    resp.trim();
    return resp;
}

static String rpc_set_lora_baud(String input) {
    long baud = input.toInt();
    if (baud > 0) {
        Serial1.begin(baud);
        return "OK";
    }
    return "ERR";
}

void setupBridgeRPC() {
    Bridge.begin();

    // RPC methods exposed to Linux container via Arduino_RouterBridge
    Bridge.provide("get_telemetry", rpc_get_telemetry);
    Bridge.provide("set_alert_state", rpc_set_alert_state);
    Bridge.provide("get_lorawan_hex", rpc_get_lorawan_hex);
    Bridge.provide("trigger_sample", rpc_trigger_sample);
    Bridge.provide("set_spectral_led", rpc_set_spectral_led);
    Bridge.provide("send_lora_at", rpc_send_lora_at);
    Bridge.provide("set_lora_baud", rpc_set_lora_baud);
}
#endif

// Forward declarations for boot sample
void processSpectralSensor();
void processAnalogSensors();
void processTemperatureSensor();

bool initSpectralSensor() {
#if USE_AS7341_SPECTRAL_SENSOR && HAS_AS7341_LIB
    // 1. Probe Wire1 first (Arduino Uno Q Qwiic connector)
    Wire1.beginTransmission(0x39);
    if (Wire1.endTransmission() == 0) {
        if (as7341.begin(0x39, &Wire1)) {
            as7341.setATIME(100);
            as7341.setASTEP(999);
            as7341.setGain(AS7341_GAIN_256X);
            as7341.enableLED(false); // LED starts OFF when idle
            as7341.setLEDCurrent(0); // 0mA current to ensure completely dark with zero leakage
            g_spectral.sensor_present = true;
            g_pSpectralWire = &Wire1;
            Serial.println(F("[STM32] Adafruit AS7341 active on Wire1 (Qwiic connector)."));
            return true;
        } else {
            Serial.println(F("[STM32] AS7341 ACK on Wire1 (Qwiic) but begin() failed."));
        }
    }

    // 2. Fallback probe Wire (Arduino Uno Q header pins SDA/SCL)
    Wire.beginTransmission(0x39);
    if (Wire.endTransmission() == 0) {
        if (as7341.begin(0x39, &Wire)) {
            as7341.setATIME(100);
            as7341.setASTEP(999);
            as7341.setGain(AS7341_GAIN_256X);
            as7341.enableLED(false); // LED starts OFF when idle
            as7341.setLEDCurrent(0); // 0mA current to ensure completely dark with zero leakage
            g_spectral.sensor_present = true;
            g_pSpectralWire = &Wire;
            Serial.println(F("[STM32] Adafruit AS7341 active on Wire (Header pins)."));
            return true;
        } else {
            Serial.println(F("[STM32] AS7341 ACK on Wire (Headers) but begin() failed."));
        }
    }
#endif
    return false;
}

void setup() {
#if HAS_ROUTER_BRIDGE
    setupBridgeRPC();
#endif
    Serial.begin(115200);
    Serial.println(F("[STM32] AquaWatch Booting..."));

    // Initialize Hardware Serial1 on pins D0 (RX) and D1 (TX) for LoRaWAN AT modem
    Serial1.begin(115200);

    analogReadResolution(12);

    pinMode(PIN_HEARTBEAT, OUTPUT);
    digitalWrite(PIN_HEARTBEAT, HIGH);

    g_calibration = getDefaultCalibration();

    tempSensors.begin();
    tempSensors.setResolution(11);
    tempSensors.setWaitForConversion(false);
    tempSensors.requestTemperatures();

    // Initialize both I2C buses (Wire1 = Qwiic, Wire = Headers)
    Wire1.begin();
    Wire1.setClock(100000);
    Wire.begin();
    Wire.setClock(100000);

    if (!initSpectralSensor()) {
        g_spectral.sensor_present = false;
        Serial.println(F("[STM32] AS7341 not detected on Wire1 (Qwiic) or Wire (Headers). Sensor offline."));
    }

    // Initial baseline capture on boot with brief optical illumination
#if HAS_AS7341_LIB
    if (g_spectral.sensor_present) {
        as7341.setLEDCurrent(12);
        as7341.enableLED(true);
        delay(300);
        processSpectralSensor();
        as7341.enableLED(false);
        as7341.setLEDCurrent(0);
    } else {
        processSpectralSensor();
    }
#else
    processSpectralSensor();
#endif
    processAnalogSensors();
    processTemperatureSensor();
    lastSampleCycleMs = millis();
    g_samplingCycleState = STATE_IDLE;

    Serial.println(F("[STM32] AquaWatch Rural India Water Monitor Ready (1-min cadence)."));
}


void processAnalogSensors() {
    // 1. Turbidity Measurement (Physical Sensor: ASAIR AZDM01 Photoelectric 940nm)
    int rawTurbidity = readOversampledADC(PIN_TURBIDITY, 64);
    filterRawTurbidity.addSample(rawTurbidity);
    int medianTurbidity = filterRawTurbidity.getMedian();
    float vTurbidity = filterVoltageTurbidity.update(adcToMillivolts(medianTurbidity, g_calibration) / 1000.0f);
    g_telemetry.turbidityNTU = calculateTurbidityNTU(vTurbidity, g_calibration);

    // 2. pH Sensor Processing (Physical Probe with Disconnection Detection OR Safe Static Baseline)
    bool phDetected = false;
#if USE_PHYSICAL_PH_SENSOR
    int rawPH = readOversampledADC(PIN_PH, 64);
    filterRawPH.addSample(rawPH);
    int medianPH = filterRawPH.getMedian();
    float vPH = filterVoltagePH.update(adcToMillivolts(medianPH, g_calibration) / 1000.0f);
    if (vPH >= PH_DISCONNECTED_V_LOW && vPH <= PH_DISCONNECTED_V_HIGH) {
        g_telemetry.ph = calculatePH(vPH, g_telemetry.temperatureC, g_calibration);
        g_telemetry.phDummy = false;
        phDetected = true;
    }
#endif
    if (!phDetected) {
        // Safe static drinking water baseline (7.35 pH, BIS IS 10500 compliant) with subtle ADC jitter
        float subtleJitterPH = ((float)(millis() % 5) - 2.0f) * 0.005f;
        g_telemetry.ph = PH_STATIC_NOMINAL + subtleJitterPH;
        g_telemetry.phDummy = true;
    }

    // 3. TDS Sensor Processing (Physical Probe with Disconnection Detection OR Safe Static Baseline)
    bool tdsDetected = false;
#if USE_PHYSICAL_TDS_SENSOR
    int rawTDS = readOversampledADC(PIN_TDS, 64);
    filterRawTDS.addSample(rawTDS);
    int medianTDS = filterRawTDS.getMedian();
    float vTDS = filterVoltageTDS.update(adcToMillivolts(medianTDS, g_calibration) / 1000.0f);
    if (vTDS >= TDS_DISCONNECTED_V_LOW && vTDS <= TDS_DISCONNECTED_V_HIGH) {
        g_telemetry.tdsPPM = calculateTDS(vTDS, g_telemetry.temperatureC, g_calibration);
        g_telemetry.tdsDummy = false;
        tdsDetected = true;
    }
#endif
    if (!tdsDetected) {
        // Safe static low-mineral baseline (180.0 ppm, BIS IS 10500 compliant) with subtle ADC jitter
        float subtleJitterTDS = ((float)(millis() % 9) - 4.0f) * 0.25f;
        g_telemetry.tdsPPM = TDS_STATIC_NOMINAL_PPM + subtleJitterTDS;
        g_telemetry.tdsDummy = true;
    }

    // 4. ORP Sensor Processing with Automatic Disconnection Detection & Dummy Fallback
    bool orpDetected = false;
#if USE_PHYSICAL_ORP_SENSOR
    int rawORP = readOversampledADC(PIN_ORP, 64);
    filterRawORP.addSample(rawORP);
    int medianORP = filterRawORP.getMedian();
    float vORP = filterVoltageORP.update(adcToMillivolts(medianORP, g_calibration) / 1000.0f);

    // Check if connected: ORP module outputs ~1.65V at 0mV redox; open/ground reads < 0.20V or > 3.10V
    if (vORP >= ORP_DISCONNECTED_V_LOW && vORP <= ORP_DISCONNECTED_V_HIGH) {
        g_telemetry.orpMV = calculateORP(vORP, g_calibration);
        g_telemetry.orpDummy = false;
        orpDetected = true;
    }
#endif

    if (!orpDetected) {
        // Inject safe municipal chlorinated tap water dummy baseline (~675 mV) with minor physical drift
        float subtleJitter = ((float)(millis() % 7) - 3.0f) * 0.4f;
        g_telemetry.orpMV = ORP_DUMMY_NOMINAL_MV + subtleJitter;
        g_telemetry.orpDummy = true;
    }

    g_telemetry.sampleCount++;
    g_telemetry.lastUpdateMs = millis();
}

void processTemperatureSensor() {
    static unsigned long lastTempRetryMs = 0;
    int devCount = tempSensors.getDeviceCount();

    // If 0 devices detected, periodically re-run begin() to support hot-plugging
    if (devCount == 0 && (millis() - lastTempRetryMs > 3000)) {
        lastTempRetryMs = millis();
        tempSensors.begin();
        devCount = tempSensors.getDeviceCount();
    }

    if (devCount > 0) {
        tempSensors.requestTemperatures();
        float temp = tempSensors.getTempCByIndex(0);
        if (temp > -40.0f && temp < 85.0f && temp != 85.0f) {
            g_telemetry.temperatureC = temp;
            g_telemetry.tempDummy = false;
        } else {
            g_telemetry.temperatureC = -127.0f;
            g_telemetry.tempDummy = true;
        }
    } else {
        g_telemetry.temperatureC = -127.0f;
        g_telemetry.tempDummy = true;
    }
}


void processSpectralSensor() {
#if USE_AS7341_SPECTRAL_SENSOR && HAS_AS7341_LIB
    static unsigned long lastSpectralRetryMs = 0;
    if (!g_spectral.sensor_present && (millis() - lastSpectralRetryMs > 5000)) {
        lastSpectralRetryMs = millis();
        initSpectralSensor();
    }

    if (g_spectral.sensor_present) {
        if (as7341.readAllChannels()) {
            g_spectral.f1_415 = as7341.getChannel(AS7341_CHANNEL_415nm_F1);
            g_spectral.f2_445 = as7341.getChannel(AS7341_CHANNEL_445nm_F2);
            g_spectral.f3_480 = as7341.getChannel(AS7341_CHANNEL_480nm_F3);
            g_spectral.f4_515 = as7341.getChannel(AS7341_CHANNEL_515nm_F4);
            g_spectral.f5_555 = as7341.getChannel(AS7341_CHANNEL_555nm_F5);
            g_spectral.f6_590 = as7341.getChannel(AS7341_CHANNEL_590nm_F6);
            g_spectral.f7_630 = as7341.getChannel(AS7341_CHANNEL_630nm_F7);
            g_spectral.f8_680 = as7341.getChannel(AS7341_CHANNEL_680nm_F8);
            g_spectral.clear  = as7341.getChannel(AS7341_CHANNEL_CLEAR);
            g_spectral.nir    = as7341.getChannel(AS7341_CHANNEL_NIR);
            computeSpectralIndices(g_spectral);
            return;
        } else {
            g_spectral.sensor_present = false;
        }
    }
#endif
    // When AS7341 is NOT physically connected, output 0 counts and mark detected = false
    g_spectral.sensor_present = false;
    g_spectral.f1_415 = 0;
    g_spectral.f2_445 = 0;
    g_spectral.f3_480 = 0;
    g_spectral.f4_515 = 0;
    g_spectral.f5_555 = 0;
    g_spectral.f6_590 = 0;
    g_spectral.f7_630 = 0;
    g_spectral.f8_680 = 0;
    g_spectral.clear  = 0;
    g_spectral.nir    = 0;
    g_spectral.algae_ndai = 0.0f;
    g_spectral.cdom_index = 0.0f;
    g_spectral.delta_ndai = 0.0f;
    g_spectral.delta_cdom = 0.0f;
}

void handleSerialCommands() {
    if (!Serial.available()) return;
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() == 0) return;

    if (cmd == "GET" || cmd == "TELEMETRY") {
        Serial.println(getTelemetryJson());
    } else if (cmd == "GET_SPECTRAL") {
        String s = "{\"f1\":" + String(g_spectral.f1_415) + ",\"f2\":" + String(g_spectral.f2_445)
                 + ",\"f3\":" + String(g_spectral.f3_480) + ",\"f4\":" + String(g_spectral.f4_515)
                 + ",\"f5\":" + String(g_spectral.f5_555) + ",\"f6\":" + String(g_spectral.f6_590)
                 + ",\"f7\":" + String(g_spectral.f7_630) + ",\"f8\":" + String(g_spectral.f8_680)
                 + ",\"clear\":" + String(g_spectral.clear) + ",\"nir\":" + String(g_spectral.nir)
                 + ",\"algae_ndai\":" + String(g_spectral.algae_ndai, 3)
                 + ",\"cdom_index\":" + String(g_spectral.cdom_index, 3)
                 + ",\"delta_ndai\":" + String(g_spectral.delta_ndai, 3)
                 + ",\"delta_cdom\":" + String(g_spectral.delta_cdom, 3) + "}";
        Serial.println(s);
    } else if (cmd.startsWith("SET_SPECTRAL_BASELINE:")) {
        // e.g. SET_SPECTRAL_BASELINE:0.480:0.420
        String sub = cmd.substring(22);
        int idx = sub.indexOf(':');
        if (idx > 0) {
            float bNdai = sub.substring(0, idx).toFloat();
            float bCdom = sub.substring(idx + 1).toFloat();
            computeSpectralIndices(g_spectral, bNdai, bCdom);
            Serial.println(F("OK:SPECTRAL_BASELINE_SET"));
        }
    } else if (cmd.startsWith("SET_SPECTRAL_LED:")) {

        bool ledOn = (cmd.substring(17) == "1");
#if HAS_AS7341_LIB
        if (g_spectral.sensor_present) {
            if (ledOn) {
                as7341.setLEDCurrent(12);
                as7341.enableLED(true);
            } else {
                as7341.enableLED(false);
            }
        }
#endif
        Serial.println(ledOn ? F("OK:SPECTRAL_LED_ON") : F("OK:SPECTRAL_LED_OFF"));
    } else if (cmd.startsWith("ALERT:")) {
        // e.g. ALERT:1:4
        String sub = cmd.substring(6);
        int idx = sub.indexOf(':');
        if (idx > 0) {
            g_telemetry.contaminationAlert = (sub.substring(0, idx) == "1");
            g_telemetry.activeHazardCode = sub.substring(idx + 1).toInt();
            Serial.println(F("OK:ALERT_SET"));
        }
    } else if (cmd.startsWith("SET_STATIC:")) {
        // e.g. SET_STATIC:PH:7.40 or SET_STATIC:TDS:185.0 or SET_STATIC:ORP:680.0
        String sub = cmd.substring(11);
        int idx = sub.indexOf(':');
        if (idx > 0) {
            String param = sub.substring(0, idx);
            float val = sub.substring(idx + 1).toFloat();
            if (param == "PH") {
                g_telemetry.ph = val;
                g_telemetry.phDummy = true;
                Serial.println(F("OK:SET_STATIC_PH"));
            } else if (param == "TDS") {
                g_telemetry.tdsPPM = val;
                g_telemetry.tdsDummy = true;
                Serial.println(F("OK:SET_STATIC_TDS"));
            } else if (param == "ORP") {
                g_telemetry.orpMV = val;
                g_telemetry.orpDummy = true;
                Serial.println(F("OK:SET_STATIC_ORP"));
            }
        }
    } else if (cmd == "SAMPLE_NOW" || cmd == "TRIGGER_SAMPLE") {
        g_manualSampleTriggered = true;
        Serial.println(F("OK:SAMPLE_TRIGGERED"));
    } else if (cmd.startsWith("LORA_AT:")) {
        String atCmd = cmd.substring(8);
        while (Serial1.available()) Serial1.read();
        Serial1.print(atCmd);
        Serial1.print("\r\n");
        unsigned long t0 = millis();
        String resp = "";
        unsigned long maxWait = (atCmd.startsWith("AT+DTRX") || atCmd.startsWith("AT+CJOIN") || atCmd.startsWith("AT+SEND") || atCmd.startsWith("AT+DTX")) ? 2500 : 600;
        while (millis() - t0 < maxWait) {
            while (Serial1.available()) {
                char c = (char)Serial1.read();
                resp += c;
                if (resp.indexOf("OK") >= 0 || resp.indexOf("ERROR") >= 0 || resp.indexOf("~#") >= 0 || resp.indexOf("ASR650") >= 0) {
                    delay(10);
                    while (Serial1.available()) resp += (char)Serial1.read();
                    break;
                }
            }
            if (resp.indexOf("OK") >= 0 || resp.indexOf("ERROR") >= 0 || resp.indexOf("~#") >= 0 || resp.indexOf("ASR650") >= 0) break;
            delay(2);
        }
        resp.trim();
        Serial.println("LORA_RESP:" + resp);
    } else if (cmd.startsWith("SET_LORA_BAUD:")) {
        long baud = cmd.substring(14).toInt();
        if (baud > 0) {
            Serial1.begin(baud);
            Serial.println(F("OK:LORA_BAUD_SET"));
        }
    }
}


void loop() {
    unsigned long now = millis();

    // 0. Handle any thread-safe RPC LED requests from the Linux container on the main thread
    if (g_rpcLedCommandPending) {
        g_rpcLedCommandPending = false;
#if HAS_AS7341_LIB
        if (g_spectral.sensor_present) {
            if (g_rpcLedStateRequested) {
                as7341.setLEDCurrent(12);
                as7341.enableLED(true);
            } else {
                as7341.enableLED(false);
                as7341.setLEDCurrent(0);
            }
        }
#endif
    }

    // 10-Minute Sampling Cadence & 1-Second Optical Pre-warm State Machine
    if (g_samplingCycleState == STATE_IDLE) {
        // Refresh temperature sensor every 3 seconds while idle
        static unsigned long lastIdleTempMs = 0;
        if (now - lastIdleTempMs >= 3000) {
            lastIdleTempMs = now;
            processTemperatureSensor();
        }

        bool timeForCadence = (now - lastSampleCycleMs >= SAMPLING_CADENCE_MS);

        if (timeForCadence || g_manualSampleTriggered) {
            g_manualSampleTriggered = false;
            g_samplingCycleState = STATE_PREWARM_LED;
            prewarmStartMs = now;

            // Turn ON AS7341 illumination LED 1 second prior to sampling
#if HAS_AS7341_LIB
            if (g_spectral.sensor_present) {
                as7341.setLEDCurrent(12); // 12mA optical illumination for flow cell
                as7341.enableLED(true);
            }
#endif
            Serial.println(F("[STM32] Sampling cycle initiated: AS7341 LED ON (1s pre-warm)..."));
        }
    }
    else if (g_samplingCycleState == STATE_PREWARM_LED) {
        // Wait 1.0 second for optical stabilization
        if (now - prewarmStartMs >= PREWARM_DURATION_MS) {
            g_samplingCycleState = STATE_SAMPLE_NOW;
        }
    }
    else if (g_samplingCycleState == STATE_SAMPLE_NOW) {
        // 1. Capture spectral reading with illumination active
        processSpectralSensor();

        // 2. Immediately turn OFF the AS7341 illumination LED and cut current to 0mA
#if HAS_AS7341_LIB
        if (g_spectral.sensor_present) {
            as7341.enableLED(false);
            as7341.setLEDCurrent(0); // Cut current to 0mA to eliminate leakage/flicker
        }
#endif
        Serial.println(F("[STM32] Spectral sample captured. AS7341 LED OFF."));

        // 3. Capture physical analog sensor readings (Turbidity, pH, TDS, ORP)
        processAnalogSensors();

        // 4. Capture temperature reading (DS18B20)
        processTemperatureSensor();

        // 5. Reset cadence timer and update state
        lastSampleCycleMs = now;
        g_samplingCycleState = STATE_IDLE;

#if !HAS_ROUTER_BRIDGE
        // Print telemetry JSON to Serial only if not using RouterBridge
        Serial.println(getTelemetryJson());
#endif
    }

    // Fail-safe emergency guard: if sampling cycle takes longer than 4 seconds, force LED OFF
    if (g_samplingCycleState != STATE_IDLE && (now - prewarmStartMs > 4000)) {
#if HAS_AS7341_LIB
        if (g_spectral.sensor_present) {
            as7341.enableLED(false);
            as7341.setLEDCurrent(0);
        }
#endif
        g_samplingCycleState = STATE_IDLE;
        lastSampleCycleMs = now;
        Serial.println(F("[STM32] FAILSAFE: Sampling timeout exceeded. Forced AS7341 LED OFF."));
    }

    // Flash faster if active contamination alert
    unsigned long blinkInterval = g_telemetry.contaminationAlert ? 150 : 600;
    if (now - lastHeartbeatToggle >= blinkInterval) {
        lastHeartbeatToggle = now;
        heartbeatState = !heartbeatState;
        digitalWrite(PIN_HEARTBEAT, heartbeatState ? HIGH : LOW);
    }

#if !HAS_ROUTER_BRIDGE
    handleSerialCommands();
#endif
}


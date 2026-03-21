// ============================================================================
// Distance-to-Target System — INITIATOR (Node A)
// ============================================================================
// Mounts on the robot. Sends an ESP-NOW radio sync packet simultaneously with
// an ultrasonic pulse. The Responder (Node B) measures the sound flight time
// and radios the distance back.
//
// Hardware:  ESP32 DevKit + HY-SRF05 ultrasonic sensor
// Framework: Arduino-ESP32
// ============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_timer.h>

// ---------------------------------------------------------------------------
// Pin Definitions — adjust to match your wiring
// ---------------------------------------------------------------------------
#define TRIG_PIN   5    // HY-SRF05 Trigger (output, 3.3V safe)
#define ECHO_PIN   18   // HY-SRF05 Echo (input — USE VOLTAGE DIVIDER! 5V→3.3V)

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
#define BAUD_RATE           115200
#define MEASUREMENT_HZ      10          // Default update rate (Hz)
#define SPEED_OF_SOUND_CM   0.0343      // cm per microsecond (at ~20 °C)

// ---------------------------------------------------------------------------
// Responder MAC address — MUST be set to the actual MAC of your Node B
// To find it, flash the Responder and read the serial output at boot.
// ---------------------------------------------------------------------------
uint8_t responderMAC[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF}; // broadcast

// ---------------------------------------------------------------------------
// Sync packet structure — sent via ESP-NOW to the Responder
// ---------------------------------------------------------------------------
typedef struct {
    uint32_t seq;           // Sequence number for matching request/reply
    int64_t  timestamp_us;  // Initiator-side timestamp (informational only)
} sync_packet_t;

// ---------------------------------------------------------------------------
// Result packet structure — received from the Responder
// ---------------------------------------------------------------------------
typedef struct {
    uint32_t seq;           // Matches the sync packet seq
    float    distance_cm;   // Computed distance in centimetres
} result_packet_t;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
static volatile bool     enabled          = false;
static volatile float    lastDistance_cm   = -1.0;
static volatile bool     resultReady      = false;
static uint32_t          seqCounter       = 0;
static unsigned long     measureInterval_ms;
static unsigned long     lastMeasureTime  = 0;

// ---------------------------------------------------------------------------
// ESP-NOW receive callback — fires when the Responder sends a result
// ---------------------------------------------------------------------------
void onDataRecv(const uint8_t *mac, const uint8_t *data, int len) {
    if ((size_t)len == sizeof(result_packet_t)) {
        result_packet_t result;
        memcpy(&result, data, sizeof(result));
        lastDistance_cm = result.distance_cm;
        resultReady    = true;
    }
}

// ---------------------------------------------------------------------------
// ESP-NOW send callback (optional — used for debugging)
// ---------------------------------------------------------------------------
void onDataSent(const uint8_t *mac, esp_now_send_status_t status) {
    // Could toggle an LED or log success/failure here
}

// ---------------------------------------------------------------------------
// Trigger one measurement cycle
//   1. Pulse the HY-SRF05 Trig pin (10 µs)
//   2. Simultaneously broadcast an ESP-NOW sync packet
// ---------------------------------------------------------------------------
void triggerMeasurement() {
    seqCounter++;

    // Build sync packet
    sync_packet_t pkt;
    pkt.seq          = seqCounter;
    pkt.timestamp_us = esp_timer_get_time();

    // --- Trigger ultrasonic pulse ---
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    // --- Broadcast ESP-NOW sync packet ---
    esp_now_send(responderMAC, (uint8_t *)&pkt, sizeof(pkt));
}

// ---------------------------------------------------------------------------
// Parse and execute UART commands
// ---------------------------------------------------------------------------
void handleSerial() {
    if (!Serial.available()) return;

    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "EN") {
        enabled = true;
        Serial.println("STATUS: ENABLED");
    } else if (cmd == "DIS") {
        enabled = false;
        Serial.println("STATUS: DISABLED");
    } else if (cmd == "GET") {
        if (lastDistance_cm >= 0) {
            Serial.print("DIST: ");
            Serial.print(lastDistance_cm, 1);
            Serial.println(" cm");
        } else {
            Serial.println("DIST: -- cm");
        }
    } else if (cmd.startsWith("RATE:")) {
        // Allow runtime update rate tuning: RATE:<hz>
        int hz = cmd.substring(5).toInt();
        if (hz >= 1 && hz <= 50) {
            measureInterval_ms = 1000 / hz;
            Serial.print("RATE: ");
            Serial.print(hz);
            Serial.println(" Hz");
        }
    }
}

// ---------------------------------------------------------------------------
// setup()
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(BAUD_RATE);
    delay(200);

    // Pin configuration
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);   // Not used on Initiator, but wired for local echo fallback
    digitalWrite(TRIG_PIN, LOW);

    // Wi-Fi in station mode (required for ESP-NOW, does not connect to any AP)
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    Serial.print("INITIATOR MAC: ");
    Serial.println(WiFi.macAddress());

    // Initialise ESP-NOW
    if (esp_now_init() != ESP_OK) {
        Serial.println("ERROR: ESP-NOW init failed");
        while (true) { delay(1000); }
    }

    esp_now_register_send_cb(onDataSent);
    esp_now_register_recv_cb(onDataRecv);

    // Register the Responder as a peer
    esp_now_peer_info_t peer;
    memset(&peer, 0, sizeof(peer));
    memcpy(peer.peer_addr, responderMAC, 6);
    peer.channel = 0;     // Use current channel
    peer.encrypt = false;

    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("ERROR: Failed to add peer");
    }

    measureInterval_ms = 1000 / MEASUREMENT_HZ;

    Serial.println("STATUS: DISABLED");
    Serial.println("Distance-to-Target Initiator ready.");
    Serial.println("Commands: EN | DIS | GET | RATE:<hz>");
}

// ---------------------------------------------------------------------------
// loop()
// ---------------------------------------------------------------------------
void loop() {
    handleSerial();

    if (enabled) {
        unsigned long now = millis();
        if (now - lastMeasureTime >= measureInterval_ms) {
            lastMeasureTime = now;
            triggerMeasurement();
        }

        // Print distance when a new result arrives from the Responder
        if (resultReady) {
            resultReady = false;
            Serial.print("DIST: ");
            Serial.print(lastDistance_cm, 1);
            Serial.println(" cm");
        }
    }
}

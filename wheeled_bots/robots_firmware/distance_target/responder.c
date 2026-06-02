// ============================================================================
// Distance-to-Target System — RESPONDER (Node B)
// ============================================================================
// Stationary target beacon. Receives the ESP-NOW sync packet from the
// Initiator, times the ultrasonic pulse arrival on its own HY-SRF05 Echo pin,
// computes the distance, and radios the result back.
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
#define ECHO_PIN   18   // HY-SRF05 Echo (input — USE VOLTAGE DIVIDER! 5V→3.3V)

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
#define BAUD_RATE           115200
#define SPEED_OF_SOUND_CM   0.0343      // cm per microsecond (at ~20 °C)
#define ECHO_TIMEOUT_US     30000       // ~5 m max range → ~29200 µs round-trip

// ---------------------------------------------------------------------------
// Sync packet structure — matches the Initiator definition
// ---------------------------------------------------------------------------
typedef struct {
    uint32_t seq;
    int64_t  timestamp_us;
} sync_packet_t;

// ---------------------------------------------------------------------------
// Result packet structure — sent back to the Initiator
// ---------------------------------------------------------------------------
typedef struct {
    uint32_t seq;
    float    distance_cm;
} result_packet_t;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
static volatile bool    syncReceived    = false;
static volatile int64_t syncTime_us     = 0;
static volatile int64_t echoStartTime   = 0;
static volatile int64_t echoEndTime     = 0;
static volatile bool    echoComplete    = false;
static volatile bool    waitingForEcho  = false;
static uint32_t         currentSeq      = 0;
static float            lastDistance_cm  = -1.0;
static bool             enabled         = true;

// MAC address of the Initiator — filled in when the first sync packet arrives
static uint8_t initiatorMAC[6] = {0};
static bool    initiatorKnown  = false;

// ---------------------------------------------------------------------------
// Hardware interrupt — fires when the Echo pin changes state
// ---------------------------------------------------------------------------
void IRAM_ATTR echoISR() {
    if (digitalRead(ECHO_PIN) == HIGH) {
        echoStartTime = esp_timer_get_time();
    } else {
        echoEndTime  = esp_timer_get_time();
        echoComplete = true;
    }
}

// ---------------------------------------------------------------------------
// ESP-NOW receive callback — fires when the Initiator sends a sync packet
// ---------------------------------------------------------------------------
void onSyncRecv(const uint8_t *mac, const uint8_t *data, int len) {
    if (!enabled) return;
    if ((size_t)len != sizeof(sync_packet_t)) return;

    // Remember the Initiator's MAC so we can reply
    if (!initiatorKnown) {
        memcpy(initiatorMAC, mac, 6);
        initiatorKnown = true;

        // Register as peer for sending results back
        esp_now_peer_info_t peer;
        memset(&peer, 0, sizeof(peer));
        memcpy(peer.peer_addr, initiatorMAC, 6);
        peer.channel = 0;
        peer.encrypt = false;
        esp_now_add_peer(&peer);
    }

    sync_packet_t pkt;
    memcpy(&pkt, data, sizeof(pkt));

    currentSeq    = pkt.seq;
    syncTime_us   = esp_timer_get_time();   // Record the moment we received the radio sync
    echoComplete  = false;
    waitingForEcho = true;

    // Enable the Echo pin interrupt to catch the incoming ultrasonic pulse
    attachInterrupt(digitalPinToInterrupt(ECHO_PIN), echoISR, CHANGE);
}

// ---------------------------------------------------------------------------
// Send computed distance back to the Initiator via ESP-NOW
// ---------------------------------------------------------------------------
void sendResult(float distance_cm) {
    if (!initiatorKnown) return;

    result_packet_t result;
    result.seq         = currentSeq;
    result.distance_cm = distance_cm;

    esp_now_send(initiatorMAC, (uint8_t *)&result, sizeof(result));
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
        waitingForEcho = false;
        detachInterrupt(digitalPinToInterrupt(ECHO_PIN));
        Serial.println("STATUS: DISABLED");
    } else if (cmd == "GET") {
        if (lastDistance_cm >= 0) {
            Serial.print("DIST: ");
            Serial.print(lastDistance_cm, 1);
            Serial.println(" cm");
        } else {
            Serial.println("DIST: -- cm");
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
    pinMode(ECHO_PIN, INPUT);

    // Wi-Fi in station mode (required for ESP-NOW)
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    Serial.print("RESPONDER MAC: ");
    Serial.println(WiFi.macAddress());

    // Initialise ESP-NOW
    if (esp_now_init() != ESP_OK) {
        Serial.println("ERROR: ESP-NOW init failed");
        while (true) { delay(1000); }
    }

    esp_now_register_recv_cb(onSyncRecv);

    Serial.println("STATUS: ENABLED");
    Serial.println("Distance-to-Target Responder ready.");
    Serial.println("Waiting for sync packets from Initiator...");
}

// ---------------------------------------------------------------------------
// loop()
// ---------------------------------------------------------------------------
void loop() {
    handleSerial();

    // --- Process a completed echo measurement ---
    if (waitingForEcho && echoComplete) {
        waitingForEcho = false;
        detachInterrupt(digitalPinToInterrupt(ECHO_PIN));

        // The distance is computed from the time between the radio sync
        // arrival (syncTime_us) and the ultrasonic echo arrival.
        // However, the more accurate measurement uses the echo pulse width
        // (echoEndTime - echoStartTime), which is the actual sound flight time
        // from the Initiator's sensor to this sensor's receiver.
        //
        // For the "Sync-and-Calculate" method described in the spec:
        //   distance = (echoStartTime - syncTime_us) * SPEED_OF_SOUND_CM
        //
        // echoStartTime is when the sound pulse first reaches this node's
        // receiver (Echo pin goes HIGH). syncTime_us is when the radio packet
        // arrived (essentially the moment the Initiator fired the pulse,
        // since radio propagation is near-instantaneous).

        int64_t flightTime_us = echoStartTime - syncTime_us;

        if (flightTime_us > 0 && flightTime_us < ECHO_TIMEOUT_US) {
            lastDistance_cm = (float)flightTime_us * SPEED_OF_SOUND_CM;

            // Send result back to Initiator
            sendResult(lastDistance_cm);

            // Also print locally
            Serial.print("DIST: ");
            Serial.print(lastDistance_cm, 1);
            Serial.println(" cm");
        } else {
            // Out of range or invalid reading
            Serial.println("DIST: -- cm (out of range)");
        }
    }

    // --- Timeout: if waiting too long for echo, abort ---
    if (waitingForEcho && !echoComplete) {
        int64_t elapsed = esp_timer_get_time() - syncTime_us;
        if (elapsed > ECHO_TIMEOUT_US) {
            waitingForEcho = false;
            detachInterrupt(digitalPinToInterrupt(ECHO_PIN));
            Serial.println("DIST: -- cm (timeout)");
        }
    }
}

/**
 * SwarmNode.cpp — Mira Swarm Node Implementation
 *
 * ESP-NOW radio layer for robot arm nodes.
 * Uses broadcast-only communication with MAC-based filtering.
 */

#include "SwarmNode.h"

#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>

// ---------------------------------------------------------------------------
// Singleton pointer for static ESP-NOW callbacks
// ---------------------------------------------------------------------------
static SwarmNode* _instance = nullptr;

// ---------------------------------------------------------------------------
// ESP-NOW receive callback (ISR context — keep it fast)
// ---------------------------------------------------------------------------
static void _onEspNowRecv(const esp_now_recv_info_t* info,
                           const uint8_t* data, int len) {
    if (_instance) {
        _instance->_handleReceive(data, len);
    }
}

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

SwarmNode::SwarmNode()
    : _seq(0), _lastHelloMs(0), _handler(nullptr),
      _cmdHead(0), _cmdTail(0) {
    memset(_myMac, 0, 6);
    memset(_myMacStr, 0, 18);
    for (int i = 0; i < SWARM_CMD_QUEUE_SIZE; i++) {
        _cmdQueue[i].pending = false;
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

void SwarmNode::onCommand(SwarmCommandHandler handler) {
    _handler = handler;
}

const uint8_t* SwarmNode::getMac() const {
    return _myMac;
}

const char* SwarmNode::getMacString() const {
    return _myMacStr;
}

void SwarmNode::begin() {
    _instance = this;

    // --- Init WiFi in STA mode (no connection, just radio) ---
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    // Force WiFi channel reliably (promiscuous mode trick for ESP-IDF 5.x)
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_channel(SWARM_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
    esp_wifi_set_promiscuous(false);

    // Read factory MAC address using Arduino WiFi API
    WiFi.macAddress(_myMac);
    swarmMacToString(_myMac, _myMacStr);

    Serial.print("[Swarm] Node MAC: ");
    Serial.println(_myMacStr);

    // Verify channel was set
    uint8_t primary;
    wifi_second_chan_t secondary;
    esp_wifi_get_channel(&primary, &secondary);
    Serial.print("[Swarm] WiFi channel: ");
    Serial.println(primary);

    // --- Init ESP-NOW ---
    _initEspNow();

    // --- Send initial HELLO ---
    _sendHello();
    _lastHelloMs = millis();

    Serial.println("[Swarm] Node ready — listening for commands");
}

void SwarmNode::update() {
    // --- Periodic HELLO re-broadcast ---
    uint32_t now = millis();
    if (now - _lastHelloMs >= SWARM_HELLO_INTERVAL_MS) {
        _sendHello();
        _lastHelloMs = now;
    }

    // --- Process queued commands ---
    while (_cmdTail != _cmdHead || _cmdQueue[_cmdTail].pending) {
        CmdEntry& entry = _cmdQueue[_cmdTail];
        if (!entry.pending) break;

        if (_handler) {
            // Execute command and capture response
            char response[SWARM_EFFECTIVE_PAYLOAD];
            response[0] = '\0';
            _handler(entry.command, response, sizeof(response));

            // Send response back to master (if non-empty)
            if (response[0] != '\0') {
                _sendReply(entry.senderMac, response);
            }
        }

        entry.pending = false;
        _cmdTail = (_cmdTail + 1) % SWARM_CMD_QUEUE_SIZE;
    }
}

// ---------------------------------------------------------------------------
// ESP-NOW receive handler (called from ISR context via static callback)
// ---------------------------------------------------------------------------

void SwarmNode::_handleReceive(const uint8_t* data, int len) {
    if (len < (int)SWARM_HEADER_SIZE) return;  // Too short

    const SwarmPacket* pkt = (const SwarmPacket*)data;

    // Only process CMD messages intended for us
    if (pkt->msg_type != SWARM_MSG_CMD) return;
    if (!swarmIsForMe(*pkt, _myMac)) return;

    // Don't process our own broadcasts
    if (swarmMacMatch(pkt->sender_mac, _myMac)) return;

    // Queue the command for processing in loop()
    uint8_t nextHead = (_cmdHead + 1) % SWARM_CMD_QUEUE_SIZE;
    if (_cmdQueue[_cmdHead].pending) {
        // Queue full — drop oldest by advancing tail
        // (This is a rare edge case; commands are processed fast)
        return;
    }

    CmdEntry& entry = _cmdQueue[_cmdHead];
    size_t payloadLen = len - SWARM_HEADER_SIZE;
    if (payloadLen >= SWARM_EFFECTIVE_PAYLOAD) payloadLen = SWARM_EFFECTIVE_PAYLOAD - 1;
    memcpy(entry.command, pkt->payload, payloadLen);
    entry.command[payloadLen] = '\0';
    memcpy(entry.senderMac, pkt->sender_mac, 6);
    entry.pending = true;
    _cmdHead = nextHead;
}

// ---------------------------------------------------------------------------
// Send helpers
// ---------------------------------------------------------------------------

void SwarmNode::_sendHello() {
    SwarmPacket pkt;
    memset(&pkt, 0, sizeof(pkt));
    pkt.msg_type = SWARM_MSG_HELLO;
    memcpy(pkt.target_mac, SWARM_BROADCAST_MAC, 6);
    memcpy(pkt.sender_mac, _myMac, 6);
    pkt.seq = _seq++;
    pkt.payload[0] = '\0';  // HELLO has no payload

    esp_now_send(SWARM_BROADCAST_MAC, (const uint8_t*)&pkt,
                 SWARM_HEADER_SIZE + 1);  // +1 for null terminator
}

void SwarmNode::_sendReply(const uint8_t* targetMac, const char* response) {
    SwarmPacket pkt;
    memset(&pkt, 0, sizeof(pkt));
    pkt.msg_type = SWARM_MSG_REPLY;
    // Target the master that sent the command
    memcpy(pkt.target_mac, targetMac, 6);
    memcpy(pkt.sender_mac, _myMac, 6);
    pkt.seq = _seq++;

    size_t respLen = strlen(response);
    if (respLen >= SWARM_EFFECTIVE_PAYLOAD) respLen = SWARM_EFFECTIVE_PAYLOAD - 1;
    memcpy(pkt.payload, response, respLen);
    pkt.payload[respLen] = '\0';

    // Always broadcast (all nodes hear it, but only master cares about REPLY)
    esp_now_send(SWARM_BROADCAST_MAC, (const uint8_t*)&pkt,
                 SWARM_HEADER_SIZE + respLen + 1);
}

// ---------------------------------------------------------------------------
// ESP-NOW initialization
// ---------------------------------------------------------------------------

void SwarmNode::_initEspNow() {
    if (esp_now_init() != ESP_OK) {
        Serial.println("[Swarm] ERROR — ESP-NOW init failed!");
        return;
    }

    // Register receive callback
    esp_now_register_recv_cb(_onEspNowRecv);

    // Add broadcast peer (required for sending)
    esp_now_peer_info_t peer;
    memset(&peer, 0, sizeof(peer));
    memcpy(peer.peer_addr, SWARM_BROADCAST_MAC, 6);
    peer.channel = 0;  // 0 = use current channel (avoids mismatch)
    peer.encrypt = false;

    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("[Swarm] ERROR — failed to add broadcast peer");
    }
}

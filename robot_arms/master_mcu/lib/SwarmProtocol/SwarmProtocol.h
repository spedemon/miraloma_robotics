/**
 * SwarmProtocol.h — Mira Swarm ESP-NOW Protocol
 *
 * Shared packet structure and helpers used by both master and node.
 * All communication uses broadcast (FF:FF:FF:FF:FF:FF) with
 * target MAC filtering inside the payload.
 *
 * Packet layout (max 250 bytes for ESP-NOW):
 *   [msg_type:1] [target_mac:6] [seq:1] [payload:up to 242]
 */

#ifndef MIRA_SWARM_PROTOCOL_H
#define MIRA_SWARM_PROTOCOL_H

#include <Arduino.h>
#include <cstring>

// ---------------------------------------------------------------------------
// Message types
// ---------------------------------------------------------------------------
#define SWARM_MSG_HELLO   0x01   // Node → Master: "I exist" (payload = empty)
#define SWARM_MSG_CMD     0x02   // Master → Node: text command
#define SWARM_MSG_REPLY   0x03   // Node → Master: text response

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
#define SWARM_MAX_PAYLOAD    242  // 250 - 8 byte header
#define SWARM_WIFI_CHANNEL   1   // All devices must be on the same channel

// Broadcast MAC — used as ESP-NOW peer and as "ALL" target
static const uint8_t SWARM_BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// ---------------------------------------------------------------------------
// Packet structure
// ---------------------------------------------------------------------------
#pragma pack(push, 1)
typedef struct {
    uint8_t  msg_type;               // SWARM_MSG_HELLO, CMD, or REPLY
    uint8_t  target_mac[6];          // Intended recipient (or FF:FF:FF:FF:FF:FF for ALL)
    uint8_t  sender_mac[6];          // Sender's own MAC (filled before send)
    uint8_t  seq;                    // Sequence number (for dedup)
    char     payload[SWARM_MAX_PAYLOAD]; // Null-terminated text
} SwarmPacket;
#pragma pack(pop)

// Actual header size (before payload)
#define SWARM_HEADER_SIZE (1 + 6 + 6 + 1)  // 14 bytes

// Max payload given header
#define SWARM_EFFECTIVE_PAYLOAD (250 - SWARM_HEADER_SIZE)  // 236 bytes

// ---------------------------------------------------------------------------
// MAC address utilities (inline, header-only)
// ---------------------------------------------------------------------------

/** Check if a MAC is the broadcast address (FF:FF:FF:FF:FF:FF). */
inline bool swarmIsBroadcast(const uint8_t mac[6]) {
    return memcmp(mac, SWARM_BROADCAST_MAC, 6) == 0;
}

/** Compare two MAC addresses. Returns true if identical. */
inline bool swarmMacMatch(const uint8_t a[6], const uint8_t b[6]) {
    return memcmp(a, b, 6) == 0;
}

/**
 * Format a MAC address as "AA:BB:CC:DD:EE:FF" into a buffer.
 * Buffer must be at least 18 bytes.
 */
inline void swarmMacToString(const uint8_t mac[6], char* buf) {
    snprintf(buf, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

/**
 * Parse a MAC string "AA:BB:CC:DD:EE:FF" into a 6-byte array.
 * Returns true on success.
 */
inline bool swarmStringToMac(const char* str, uint8_t mac[6]) {
    unsigned int tmp[6];
    if (sscanf(str, "%02X:%02X:%02X:%02X:%02X:%02X",
               &tmp[0], &tmp[1], &tmp[2], &tmp[3], &tmp[4], &tmp[5]) != 6) {
        return false;
    }
    for (int i = 0; i < 6; i++) mac[i] = (uint8_t)tmp[i];
    return true;
}

/**
 * Check if a received packet is intended for this node.
 * Returns true if target_mac matches myMac or is broadcast.
 */
inline bool swarmIsForMe(const SwarmPacket& pkt, const uint8_t myMac[6]) {
    return swarmIsBroadcast(pkt.target_mac) || swarmMacMatch(pkt.target_mac, myMac);
}

#endif // MIRA_SWARM_PROTOCOL_H

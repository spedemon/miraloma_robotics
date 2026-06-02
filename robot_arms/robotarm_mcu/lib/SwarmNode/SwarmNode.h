/**
 * SwarmNode.h — Mira Swarm Node (ESP-NOW)
 *
 * Makes a robot arm a participant in the ESP-NOW swarm.
 * On boot, broadcasts a HELLO with its factory MAC address.
 * Receives commands from the master and forwards them to the
 * local SerialConsole for execution. Sends replies back.
 *
 * Usage:
 *   SwarmNode swarm;
 *   swarm.onCommand([](const char* cmd, char* resp, size_t max) {
 *       // execute cmd, write response into resp
 *   });
 *   swarm.begin();
 *   // in loop():
 *   swarm.update();
 */

#ifndef MIRA_SWARM_NODE_H
#define MIRA_SWARM_NODE_H

#include <Arduino.h>
#include "SwarmProtocol.h"

// How often to re-broadcast HELLO (ms)
#define SWARM_HELLO_INTERVAL_MS  2000

// Max pending incoming commands (ring buffer)
#define SWARM_CMD_QUEUE_SIZE     4

/**
 * Callback signature for command execution.
 * @param command   Null-terminated command string (e.g., "home", "goto 50 0 60")
 * @param response  Buffer to write the response into
 * @param maxLen    Maximum bytes to write into response
 */
typedef void (*SwarmCommandHandler)(const char* command, char* response, size_t maxLen);

class SwarmNode {
public:
    SwarmNode();

    /**
     * Initialize WiFi (STA, no connection), ESP-NOW, register broadcast peer,
     * and send initial HELLO. Call in setup() after Serial.begin().
     */
    void begin();

    /**
     * Call every loop() iteration. Handles:
     *   - Periodic HELLO re-broadcasts
     *   - Processing queued incoming commands
     */
    void update();

    /**
     * Register the command handler callback.
     * Must be called before begin().
     */
    void onCommand(SwarmCommandHandler handler);

    /**
     * Get this node's MAC address (6 bytes).
     */
    const uint8_t* getMac() const;

    /**
     * Get this node's MAC as a string "AA:BB:CC:DD:EE:FF".
     */
    const char* getMacString() const;

    // --- Internal (called from static ESP-NOW callback) ---
    void _handleReceive(const uint8_t* data, int len);

private:
    uint8_t  _myMac[6];
    char     _myMacStr[18];
    uint8_t  _seq;
    uint32_t _lastHelloMs;
    SwarmCommandHandler _handler;

    // Incoming command queue (ring buffer, ISR-safe)
    struct CmdEntry {
        char     command[SWARM_EFFECTIVE_PAYLOAD];
        uint8_t  senderMac[6];
        bool     pending;
    };
    CmdEntry _cmdQueue[SWARM_CMD_QUEUE_SIZE];
    volatile uint8_t _cmdHead;  // Write position (ISR)
    uint8_t _cmdTail;           // Read position (loop)

    void _sendHello();
    void _sendReply(const uint8_t* targetMac, const char* response);
    void _initEspNow();
};

#endif // MIRA_SWARM_NODE_H

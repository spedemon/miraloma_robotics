/**
 * BleTransport — direct Mira control over Bluetooth Low Energy.
 *
 * The BLE callbacks only copy commands into a ring buffer. Commands execute
 * from update() in the Arduino loop so motion code never runs on the NimBLE
 * host task. A connected BLE client owns direct control; the application can
 * use isConnected() to keep ESP-NOW from issuing competing motion commands.
 */

#ifndef MIRA_BLE_TRANSPORT_H
#define MIRA_BLE_TRANSPORT_H

#include <Arduino.h>
#include "config.h"

class NimBLECharacteristic;
class NimBLEServer;

typedef void (*BleCommandHandler)(const char* command, String& response);

class BleTransport {
public:
    BleTransport();

    void begin(const char* stableId, const char* robotName, BleCommandHandler handler);
    void setRobotName(const char* robotName);
    void update();
    bool isConnected() const;

    // Called by NimBLE callback adapters.
    void queueCommand(const char* command, size_t length);
    void connected();
    void disconnected();

private:
    struct CommandEntry {
        char value[MIRA_BLE_MAX_COMMAND_LENGTH + 1];
        bool pending;
    };

    BleCommandHandler _handler;
    NimBLECharacteristic* _response;
    NimBLECharacteristic* _info;
    NimBLEServer* _server;
    CommandEntry _commands[MIRA_BLE_COMMAND_QUEUE_SIZE];
    volatile uint8_t _head;
    uint8_t _tail;
    volatile bool _connected;
    volatile bool _stopAfterDisconnect;
    char _stableId[18];
    char _robotName[16];

    void notifyResponse(const String& response);
    void refreshDeviceInfo();
};

#endif

#include "BleTransport.h"

#include <NimBLEDevice.h>
#include "config.h"

namespace {
BleTransport* activeTransport = nullptr;

class MiraServerCallbacks final : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer*, NimBLEConnInfo&) override {
        if (activeTransport) activeTransport->connected();
    }

    void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
        if (activeTransport) activeTransport->disconnected();
    }
};

class MiraCommandCallbacks final : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
        if (!activeTransport) return;
        const std::string value = characteristic->getValue();
        activeTransport->queueCommand(value.data(), value.size());
    }
};

MiraServerCallbacks serverCallbacks;
MiraCommandCallbacks commandCallbacks;
}

BleTransport::BleTransport()
    : _handler(nullptr), _response(nullptr), _server(nullptr),
      _head(0), _tail(0), _connected(false), _stopAfterDisconnect(false) {
    for (auto& command : _commands) command.pending = false;
}

void BleTransport::begin(const char* stableId, BleCommandHandler handler) {
    activeTransport = this;
    _handler = handler;

    String suffix(stableId ? stableId : "MIRA");
    suffix.replace(":", "");
    if (suffix.length() > 4) suffix = suffix.substring(suffix.length() - 4);
    const String deviceName = "Mira-" + suffix;

    NimBLEDevice::init(deviceName.c_str());
    NimBLEDevice::setPower(3);
    NimBLEDevice::setMTU(247);

    _server = NimBLEDevice::createServer();
    _server->setCallbacks(&serverCallbacks);

    NimBLEService* service = _server->createService(MIRA_BLE_SERVICE_UUID);
    NimBLECharacteristic* command = service->createCharacteristic(
        MIRA_BLE_COMMAND_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR,
        MIRA_BLE_MAX_COMMAND_LENGTH
    );
    command->setCallbacks(&commandCallbacks);

    _response = service->createCharacteristic(
        MIRA_BLE_RESPONSE_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY,
        MIRA_BLE_RESPONSE_CHUNK
    );
    _response->setValue("MIRA_READY\n");

    NimBLECharacteristic* info = service->createCharacteristic(
        MIRA_BLE_DEVICE_INFO_UUID,
        NIMBLE_PROPERTY::READ,
        160
    );
    String metadata = "role=robot id=" + String(stableId) +
        " firmware=" MIRA_FIRMWARE_VERSION +
        " protocol=" + String(MIRA_PROTOCOL_VERSION) +
        " hardware=esp32c3";
    info->setValue(metadata.c_str());

    _server->start();
    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    advertising->addServiceUUID(MIRA_BLE_SERVICE_UUID);
    advertising->enableScanResponse(true);
    advertising->setName(deviceName.c_str());
    advertising->start();

    Serial.print("[BLE] Advertising as ");
    Serial.println(deviceName);
}

void BleTransport::queueCommand(const char* command, size_t length) {
    if (!command || length == 0) return;
    if (length > MIRA_BLE_MAX_COMMAND_LENGTH) length = MIRA_BLE_MAX_COMMAND_LENGTH;

    CommandEntry& entry = _commands[_head];
    if (entry.pending) return;
    memcpy(entry.value, command, length);
    entry.value[length] = '\0';
    while (length > 0 && (entry.value[length - 1] == '\n' || entry.value[length - 1] == '\r')) {
        entry.value[--length] = '\0';
    }
    if (length == 0) return;
    entry.pending = true;
    _head = (_head + 1) % MIRA_BLE_COMMAND_QUEUE_SIZE;
}

void BleTransport::connected() {
    _connected = true;
    Serial.println("[BLE] Controller connected");
}

void BleTransport::disconnected() {
    _connected = false;
    _stopAfterDisconnect = true;
    NimBLEDevice::getAdvertising()->start();
    Serial.println("[BLE] Controller disconnected");
}

bool BleTransport::isConnected() const {
    return _connected;
}

void BleTransport::update() {
    if (_stopAfterDisconnect) {
        _stopAfterDisconnect = false;
        if (_handler) {
            String ignored;
            _handler("stop", ignored);
        }
    }

    while (_commands[_tail].pending) {
        CommandEntry& entry = _commands[_tail];
        String response;
        if (_handler) _handler(entry.value, response);
        if (response.length() > 0) notifyResponse(response);
        entry.pending = false;
        _tail = (_tail + 1) % MIRA_BLE_COMMAND_QUEUE_SIZE;
    }
}

void BleTransport::notifyResponse(const String& response) {
    if (!_connected || !_response) return;

    String framed = response;
    if (!framed.endsWith("\n")) framed += "\n";
    for (size_t offset = 0; offset < framed.length(); offset += MIRA_BLE_RESPONSE_CHUNK) {
        const size_t length = min((size_t)MIRA_BLE_RESPONSE_CHUNK, framed.length() - offset);
        _response->setValue(
            reinterpret_cast<const uint8_t*>(framed.c_str() + offset),
            length
        );
        _response->notify();
    }
}

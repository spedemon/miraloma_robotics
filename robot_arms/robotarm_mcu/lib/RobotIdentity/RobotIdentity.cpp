#include "RobotIdentity.h"

#include <Preferences.h>

namespace {
constexpr const char* NAMESPACE = "mira_identity";
constexpr const char* NAME_KEY = "name";
}

void RobotIdentity::begin() {
    Preferences preferences;
    if (!preferences.begin(NAMESPACE, true)) return;
    String stored = preferences.getString(NAME_KEY, "");
    preferences.end();
    if (stored.length() > 15) stored = "";
    stored.toCharArray(_name, sizeof(_name));
}

const char* RobotIdentity::name() const {
    return _name;
}

bool RobotIdentity::setName(const String& requested, String& error) {
    String value = requested;
    value.trim();
    if (value.length() == 0 || value.length() > 15) {
        error = "Name must be 1 to 15 characters";
        return false;
    }
    for (size_t index = 0; index < value.length(); ++index) {
        const uint8_t character = static_cast<uint8_t>(value[index]);
        if (character < 0x20 || character > 0x7e) {
            error = "Name must use printable ASCII characters";
            return false;
        }
    }

    Preferences preferences;
    if (!preferences.begin(NAMESPACE, false)) {
        error = "Could not open identity storage";
        return false;
    }
    const size_t written = preferences.putString(NAME_KEY, value);
    preferences.end();
    if (written != value.length()) {
        error = "Could not save name";
        return false;
    }

    value.toCharArray(_name, sizeof(_name));
    ++_revision;
    return true;
}

uint32_t RobotIdentity::revision() const {
    return _revision;
}

String RobotIdentity::encode(const char* value) {
    String encoded;
    static const char hex[] = "0123456789ABCDEF";
    for (const uint8_t* cursor = reinterpret_cast<const uint8_t*>(value); cursor && *cursor; ++cursor) {
        const uint8_t character = *cursor;
        if ((character >= 'a' && character <= 'z') ||
            (character >= 'A' && character <= 'Z') ||
            (character >= '0' && character <= '9') ||
            character == '-' || character == '_' || character == '.') {
            encoded += static_cast<char>(character);
        } else {
            encoded += '%';
            encoded += hex[character >> 4];
            encoded += hex[character & 0x0f];
        }
    }
    return encoded;
}

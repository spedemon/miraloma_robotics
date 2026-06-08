/**
 * CustomGestureStore.cpp — Multi-gesture NVS Flash Storage
 *
 * Uses the ESP32 Preferences library to persist custom gestures.
 *
 * NVS storage scheme (namespace "mira_cg"):
 *   Key "n_<i>"    → gesture name (String, max 15 chars)
 *   Key "kc_<i>"   → keyframe count (UChar / uint8_t)
 *   Key "kf_<i>"   → keyframe data (raw bytes via putBytes)
 *   Key "used_<i>" → slot in use flag (Bool)
 *
 * Each gesture slot uses ~1KB of NVS space (20B × 50 keyframes max).
 * 20 slots ≈ 20KB, well within the ESP32-C3's typical 24KB NVS partition.
 */

#include "CustomGestureStore.h"
#include <Preferences.h>
#include <string.h>

static const char* NVS_NAMESPACE = "mira_cg";

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

CustomGestureStore::CustomGestureStore(SmoothMover& smooth)
    : _smooth(smooth), _stagingCount(0), _stagingLoop(true) {
    // Initialize all slots as unused
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        _slots[i].used = false;
        _slots[i].name[0] = '\0';
        _slots[i].keyframeCount = 0;
        _slots[i].loop = true;
        _players[i] = nullptr;
    }
}

// ---------------------------------------------------------------------------
// begin() — Load from flash
// ---------------------------------------------------------------------------

void CustomGestureStore::begin() {
    _initPlayers();
    _loadAllFromFlash();

    uint8_t loaded = 0;
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        if (_slots[i].used) {
            _syncPlayerFromSlot(i);
            loaded++;
        }
    }

    Serial.print("[CustomStore] Loaded ");
    Serial.print(loaded);
    Serial.println(" custom gestures from flash");
}

// ---------------------------------------------------------------------------
// Staging buffer
// ---------------------------------------------------------------------------

void CustomGestureStore::clearStaging() {
    _stagingCount = 0;
    _stagingLoop = true;  // default to looping
}

bool CustomGestureStore::addStagingKeyframe(float base, float shoulder,
                                             float elbow, float grip,
                                             uint32_t durationMs) {
    if (_stagingCount >= SequenceGesture::MAX_KEYFRAMES) return false;
    _stagingKeyframes[_stagingCount++] = {base, shoulder, elbow, grip, durationMs};
    return true;
}

uint8_t CustomGestureStore::stagingCount() const {
    return _stagingCount;
}

// ---------------------------------------------------------------------------
// save() — Persist staging buffer as a named gesture
// ---------------------------------------------------------------------------

CustomGestureStore::SaveResult CustomGestureStore::save(const char* name) {
    // Validate name
    if (!name || name[0] == '\0') {
        return ERR_NAME_EMPTY;
    }
    if (strlen(name) > 15) {
        return ERR_NAME_TOO_LONG;
    }

    // Check for duplicate name
    if (_findSlotByName(name) >= 0) {
        return ERR_NAME_DUPLICATE;
    }

    // Must have keyframes in staging
    if (_stagingCount == 0) {
        return ERR_NO_KEYFRAMES;
    }

    // Find a free slot
    int8_t slot = _findFreeSlot();
    if (slot < 0) {
        return ERR_STORE_FULL;
    }

    // Populate the slot
    strncpy(_slots[slot].name, name, sizeof(_slots[slot].name) - 1);
    _slots[slot].name[sizeof(_slots[slot].name) - 1] = '\0';
    _slots[slot].keyframeCount = _stagingCount;
    memcpy(_slots[slot].keyframes, _stagingKeyframes,
           _stagingCount * sizeof(SequenceKeyframe));
    _slots[slot].used = true;
    _slots[slot].loop = _stagingLoop;

    // Persist to flash
    _saveSlotToFlash(slot);

    // Sync the player
    _syncPlayerFromSlot(slot);

    Serial.print("[CustomStore] Saved gesture '");
    Serial.print(name);
    Serial.print("' with ");
    Serial.print(_stagingCount);
    Serial.println(" keyframes");

    return SAVE_OK;
}

// ---------------------------------------------------------------------------
// remove() — Delete a gesture
// ---------------------------------------------------------------------------

bool CustomGestureStore::remove(const char* name) {
    int8_t slot = _findSlotByName(name);
    if (slot < 0) return false;

    // Clear the slot
    _slots[slot].used = false;
    _slots[slot].name[0] = '\0';
    _slots[slot].keyframeCount = 0;

    // Clear the player
    _players[slot]->clear();
    _players[slot]->setName("_deleted");

    // Remove from flash
    _deleteSlotFromFlash(slot);

    Serial.print("[CustomStore] Deleted gesture '");
    Serial.print(name);
    Serial.println("'");

    return true;
}

// ---------------------------------------------------------------------------
// Query methods
// ---------------------------------------------------------------------------

uint8_t CustomGestureStore::count() const {
    uint8_t n = 0;
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        if (_slots[i].used) n++;
    }
    return n;
}

const char* CustomGestureStore::getName(uint8_t slotIndex) const {
    if (slotIndex >= MAX_CUSTOM_GESTURES) return nullptr;
    if (!_slots[slotIndex].used) return nullptr;
    return _slots[slotIndex].name;
}

SequenceGesture* CustomGestureStore::find(const char* name) {
    int8_t slot = _findSlotByName(name);
    if (slot < 0) return nullptr;
    return _players[slot];
}

void CustomGestureStore::registerAll(GestureManager& mgr) {
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        if (_slots[i].used) {
            mgr.registerGesture(_players[i]);
        }
    }
}

// ---------------------------------------------------------------------------
// Error string lookup
// ---------------------------------------------------------------------------

const char* CustomGestureStore::errorString(SaveResult result) {
    switch (result) {
        case SAVE_OK:           return "ok";
        case ERR_NAME_EMPTY:    return "name_empty";
        case ERR_NAME_TOO_LONG: return "name_too_long";
        case ERR_NAME_DUPLICATE:return "name_duplicate";
        case ERR_NO_KEYFRAMES:  return "no_keyframes";
        case ERR_STORE_FULL:    return "store_full";
        case ERR_FLASH_WRITE:   return "flash_write_error";
        default:                return "unknown_error";
    }
}

// ---------------------------------------------------------------------------
// NVS flash helpers
// ---------------------------------------------------------------------------

void CustomGestureStore::_saveSlotToFlash(uint8_t index) {
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, false);  // read-write

    String keyUsed = "u_" + String(index);
    String keyName = "n_" + String(index);
    String keyCount = "kc_" + String(index);
    String keyData = "kf_" + String(index);

    prefs.putBool(keyUsed.c_str(), true);
    prefs.putString(keyName.c_str(), _slots[index].name);
    prefs.putUChar(keyCount.c_str(), _slots[index].keyframeCount);
    prefs.putBytes(keyData.c_str(), _slots[index].keyframes,
                   _slots[index].keyframeCount * sizeof(SequenceKeyframe));

    String keyLoop = "lp_" + String(index);
    prefs.putBool(keyLoop.c_str(), _slots[index].loop);

    prefs.end();
}

void CustomGestureStore::_deleteSlotFromFlash(uint8_t index) {
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, false);  // read-write

    String keyUsed = "u_" + String(index);
    String keyName = "n_" + String(index);
    String keyCount = "kc_" + String(index);
    String keyData = "kf_" + String(index);

    prefs.remove(keyUsed.c_str());
    prefs.remove(keyName.c_str());
    prefs.remove(keyCount.c_str());
    prefs.remove(keyData.c_str());

    prefs.end();
}

void CustomGestureStore::_loadAllFromFlash() {
    Preferences prefs;
    prefs.begin(NVS_NAMESPACE, true);  // read-only

    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        String keyUsed = "u_" + String(i);
        _slots[i].used = prefs.getBool(keyUsed.c_str(), false);

        if (_slots[i].used) {
            String keyName = "n_" + String(i);
            String keyCount = "kc_" + String(i);
            String keyData = "kf_" + String(i);

            String name = prefs.getString(keyName.c_str(), "");
            strncpy(_slots[i].name, name.c_str(), sizeof(_slots[i].name) - 1);
            _slots[i].name[sizeof(_slots[i].name) - 1] = '\0';

            _slots[i].keyframeCount = prefs.getUChar(keyCount.c_str(), 0);

            String keyLoop = "lp_" + String(i);
            _slots[i].loop = prefs.getBool(keyLoop.c_str(), true);  // default true for backward compat

            size_t dataSize = _slots[i].keyframeCount * sizeof(SequenceKeyframe);
            if (dataSize > 0) {
                prefs.getBytes(keyData.c_str(), _slots[i].keyframes, dataSize);
            }
        }
    }

    prefs.end();
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

void CustomGestureStore::_syncPlayerFromSlot(uint8_t index) {
    SequenceGesture* player = _players[index];
    player->clear();
    player->setName(_slots[index].name);
    player->setLoop(_slots[index].loop);

    for (uint8_t k = 0; k < _slots[index].keyframeCount; k++) {
        const SequenceKeyframe& kf = _slots[index].keyframes[k];
        player->addKeyframe(kf.base, kf.shoulder, kf.elbow, kf.grip, kf.durationMs);
    }
}

void CustomGestureStore::_initPlayers() {
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        if (!_players[i]) {
            _players[i] = new SequenceGesture(_smooth, "_empty");
        }
    }
}

int8_t CustomGestureStore::_findSlotByName(const char* name) const {
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        if (_slots[i].used && strcmp(_slots[i].name, name) == 0) {
            return (int8_t)i;
        }
    }
    return -1;
}

int8_t CustomGestureStore::_findFreeSlot() const {
    for (uint8_t i = 0; i < MAX_CUSTOM_GESTURES; i++) {
        if (!_slots[i].used) return (int8_t)i;
    }
    return -1;
}

/**
 * CustomGestureStore.h — Multi-gesture NVS Flash Storage
 *
 * Manages up to MAX_CUSTOM_GESTURES named SequenceGesture instances,
 * persisted to ESP32 NVS flash. Each gesture has a user-provided name
 * (max 15 chars) and up to 50 keyframes.
 *
 * Upload flow:
 *   1. clearStaging()                     — reset staging buffer
 *   2. addStagingKeyframe(...) × N        — populate staging
 *   3. save("my_dance")                   — persist to flash + create player
 *
 * Playback: find("my_dance") returns a SequenceGesture* registered
 *           with the GestureManager for immediate use.
 *
 * Error codes from save() provide detailed failure reasons to the UI.
 */

#ifndef MIRA_CUSTOM_GESTURE_STORE_H
#define MIRA_CUSTOM_GESTURE_STORE_H

#include <Arduino.h>
#include "SequenceGesture.h"
#include "Gesture.h"

class CustomGestureStore {
public:
    static const uint8_t MAX_CUSTOM_GESTURES = 20;

    /** Error codes returned by save(). */
    enum SaveResult {
        SAVE_OK = 0,
        ERR_NAME_EMPTY,
        ERR_NAME_TOO_LONG,
        ERR_NAME_DUPLICATE,
        ERR_NO_KEYFRAMES,
        ERR_STORE_FULL,
        ERR_FLASH_WRITE,
    };

    CustomGestureStore(SmoothMover& smooth);

    /** Load all gestures from NVS flash. Call once in setup(). */
    void begin();

    /**
     * Save the current staging buffer as a named gesture.
     * Persists to NVS flash and creates a playable SequenceGesture.
     * @param name  Gesture name (max 15 chars, no spaces)
     * @return SaveResult error code
     */
    SaveResult save(const char* name);

    /**
     * Delete a gesture by name. Removes from flash and frees the slot.
     * @return true if found and deleted, false if not found.
     */
    bool remove(const char* name);

    /** Get the number of stored custom gestures. */
    uint8_t count() const;

    /**
     * Get gesture name by slot index (for listing).
     * Skips unused slots. Returns nullptr if index is invalid or unused.
     */
    const char* getName(uint8_t slotIndex) const;

    /**
     * Find a SequenceGesture player by name (for playback via GestureManager).
     * Returns nullptr if not found.
     */
    SequenceGesture* find(const char* name);

    /** Register all stored (non-empty) gestures with the GestureManager. */
    void registerAll(GestureManager& mgr);

    // --- Staging buffer (used during upload) ---

    /** Clear the staging buffer for a fresh upload. */
    void clearStaging();

    /** Add a keyframe to the staging buffer. Returns false if full (max 50). */
    bool addStagingKeyframe(float base, float shoulder, float elbow,
                            float grip, uint32_t durationMs);

    /** Set the loop flag for the staging buffer (default: true). */
    void setStagingLoop(bool loop) { _stagingLoop = loop; }

    /** Number of keyframes currently in the staging buffer. */
    uint8_t stagingCount() const;

    /** Human-readable error string for a SaveResult code. */
    static const char* errorString(SaveResult result);

private:
    // Per-slot storage
    struct Slot {
        char name[16];
        SequenceKeyframe keyframes[SequenceGesture::MAX_KEYFRAMES];
        uint8_t keyframeCount;
        bool used;
        bool loop;   // true = loops forever, false = one-shot
    };

    Slot _slots[MAX_CUSTOM_GESTURES];

    // Each slot gets its own SequenceGesture player for runtime playback
    SequenceGesture* _players[MAX_CUSTOM_GESTURES];
    SmoothMover& _smooth;

    // Staging buffer for incoming upload (before save)
    SequenceKeyframe _stagingKeyframes[SequenceGesture::MAX_KEYFRAMES];
    uint8_t _stagingCount;
    bool _stagingLoop;   // loop flag for next save

    // --- NVS helpers ---
    void _saveSlotToFlash(uint8_t index);
    void _loadAllFromFlash();
    void _deleteSlotFromFlash(uint8_t index);

    /** Copy slot data into its SequenceGesture player for runtime use. */
    void _syncPlayerFromSlot(uint8_t index);
    void _initPlayers();

    int8_t _findSlotByName(const char* name) const;
    int8_t _findFreeSlot() const;
};

#endif // MIRA_CUSTOM_GESTURE_STORE_H

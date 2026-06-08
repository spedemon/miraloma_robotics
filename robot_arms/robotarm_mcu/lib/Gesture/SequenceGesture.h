#ifndef MIRA_SEQUENCE_GESTURE_H
#define MIRA_SEQUENCE_GESTURE_H

#include "Gesture.h"
#include "SmoothMover.h"

struct SequenceKeyframe {
    float base;
    float shoulder;
    float elbow;
    float grip;
    uint32_t durationMs;
};

class SequenceGesture : public Gesture {
public:
    static const uint8_t MAX_KEYFRAMES = 50;

    SequenceGesture(SmoothMover& smooth, const char* gestureName = "custom");

    const char* name() override { return _name; }
    bool isEmpty() override { return _keyframeCount == 0; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;

    void clear();
    bool addKeyframe(float base, float shoulder, float elbow, float grip, uint32_t durationMs);
    uint8_t count() const { return _keyframeCount; }
    void setName(const char* name);

    /** Set whether this gesture loops continuously or plays once. */
    void setLoop(bool loop) { _loop = loop; }
    bool getLoop() const { return _loop; }

private:
    SmoothMover& _smooth;
    bool _running;
    bool _loop;       // true = loop forever, false = one-shot
    uint8_t _phase;
    char _name[16];

    SequenceKeyframe _keyframes[MAX_KEYFRAMES];
    uint8_t _keyframeCount;

    void _enqueueNextKeyframe();
};

#endif // MIRA_SEQUENCE_GESTURE_H

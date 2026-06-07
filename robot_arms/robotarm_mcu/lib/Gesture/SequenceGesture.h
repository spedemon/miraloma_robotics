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

    SequenceGesture(SmoothMover& smooth);

    const char* name() override { return "custom"; }
    void start() override;
    void stop() override;
    void update() override;
    bool isRunning() override;

    void clear();
    bool addKeyframe(float base, float shoulder, float elbow, float grip, uint32_t durationMs);

private:
    SmoothMover& _smooth;
    bool _running;
    uint8_t _phase;
    
    SequenceKeyframe _keyframes[MAX_KEYFRAMES];
    uint8_t _keyframeCount;

    void _enqueueNextKeyframe();
};

#endif // MIRA_SEQUENCE_GESTURE_H

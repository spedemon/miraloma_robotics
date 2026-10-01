#ifndef MIRA_ROBOT_IDENTITY_H
#define MIRA_ROBOT_IDENTITY_H

#include <Arduino.h>

class RobotIdentity {
public:
    void begin();
    const char* name() const;
    bool setName(const String& name, String& error);
    uint32_t revision() const;

    static String encode(const char* value);

private:
    char _name[16] = {0};
    uint32_t _revision = 0;
};

#endif

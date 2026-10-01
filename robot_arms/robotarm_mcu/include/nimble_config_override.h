// Project-wide NimBLE configuration. PlatformIO force-includes this file
// before the framework headers, so the prebuilt Arduino sdkconfig is loaded
// once and these server-only values remain authoritative.
#pragma once

#include "sdkconfig.h"

#undef CONFIG_BT_NIMBLE_MAX_CONNECTIONS
#define CONFIG_BT_NIMBLE_MAX_CONNECTIONS 1

#undef CONFIG_BT_NIMBLE_LOG_LEVEL
#define CONFIG_BT_NIMBLE_LOG_LEVEL 5

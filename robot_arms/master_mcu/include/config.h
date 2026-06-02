/**
 * config.h — Mira Master MCU Configuration
 */

#ifndef MIRA_MASTER_CONFIG_H
#define MIRA_MASTER_CONFIG_H

// ---------------------------------------------------------------------------
// Serial
// ---------------------------------------------------------------------------
#define SERIAL_BAUD       115200

// ---------------------------------------------------------------------------
// Swarm
// ---------------------------------------------------------------------------
#define MAX_ROBOTS        32       // Maximum discovered robots
#define HELLO_TIMEOUT_MS  5000     // Consider robot offline after 5s no HELLO

// ---------------------------------------------------------------------------
// Reply collection
// ---------------------------------------------------------------------------
#define REPLY_TIMEOUT_MS  2000     // Wait up to 2s for replies after a command

#endif // MIRA_MASTER_CONFIG_H

/**
 * main.cpp — Mira Master MCU (Swarm Controller)
 *
 * USB-to-ESP-NOW bridge. Connects to laptop via serial, broadcasts
 * commands to robot arm nodes, and collects responses.
 *
 * Console syntax:
 *   <command>              → broadcast to ALL robots
 *   @R1 <command>          → send to robot R1 only
 *   @all <command>         → explicit broadcast (same as no prefix)
 *   @AA:BB:CC:DD:EE:FF cmd → target by raw MAC address
 *
 * Master-only commands:
 *   swarm list             → list discovered robots
 *   swarm ping             → trigger HELLO from all robots
 *   swarm rename R1 Lefty  → rename a robot
 *   help                   → show help
 */

#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>
#include "config.h"
#include "SwarmProtocol.h"

// ---------------------------------------------------------------------------
// Status LED — breathing animation (2× speed vs robot nodes)
// ---------------------------------------------------------------------------
#define LED_PIN                8
#define LED_PWM_FREQ           5000
#define LED_PWM_RESOLUTION     8
#define LED_BREATH_PERIOD_MS   1500    // Half of robotarm_mcu's 3000ms
#define LED_ACTIVE_LOW         true
#define LED_TASK_STACK         2048
#define LED_TASK_PRIORITY      1

static void ledBreatheTask(void* pvParameters) {
    const uint16_t maxDuty = (1 << LED_PWM_RESOLUTION) - 1;

    for (;;) {
        float phase = (float)(millis() % LED_BREATH_PERIOD_MS) / (float)LED_BREATH_PERIOD_MS;
        float brightness = (1.0f - cosf(2.0f * M_PI * phase)) / 2.0f;
        uint16_t duty = (uint16_t)(brightness * maxDuty);

        if (LED_ACTIVE_LOW) {
            duty = maxDuty - duty;
        }

        ledcWrite(LED_PIN, duty);
        vTaskDelay(pdMS_TO_TICKS(16));  // ~60 fps
    }
}

// ---------------------------------------------------------------------------
// Robot registry
// ---------------------------------------------------------------------------

struct RobotEntry {
    uint8_t  mac[6];
    char     name[16];       // "R1", "R2", or user-assigned name
    uint32_t lastSeenMs;
    bool     active;
};

static RobotEntry robots[MAX_ROBOTS];
static uint8_t    robotCount = 0;
static uint8_t    myMac[6];
static char       myMacStr[18];
static uint8_t    txSeq = 0;

// Serial input buffer
static String inputBuffer;

// Forward declaration
static void printPrompt();

// Reply collection buffer
static String replyBuffer;
static uint32_t lastCmdSentMs = 0;
static bool     waitingForReply = false;

// ---------------------------------------------------------------------------
// Robot registry management
// ---------------------------------------------------------------------------

/**
 * Find a robot by MAC. Returns index or -1.
 */
static int findRobotByMac(const uint8_t mac[6]) {
    for (int i = 0; i < robotCount; i++) {
        if (swarmMacMatch(robots[i].mac, mac)) return i;
    }
    return -1;
}

/**
 * Find a robot by name (case-insensitive). Returns index or -1.
 */
static int findRobotByName(const String& name) {
    for (int i = 0; i < robotCount; i++) {
        if (name.equalsIgnoreCase(robots[i].name)) return i;
    }
    return -1;
}

/**
 * Register a new robot or refresh an existing one.
 */
static void registerRobot(const uint8_t mac[6]) {
    int idx = findRobotByMac(mac);

    if (idx >= 0) {
        // Existing robot — refresh timestamp
        bool wasOffline = !robots[idx].active;
        robots[idx].lastSeenMs = millis();
        robots[idx].active = true;

        // Notify serial when a robot comes back online
        if (wasOffline) {
            char macStr[18];
            swarmMacToString(mac, macStr);
            Serial.println();
            Serial.print("ROBOT_ONLINE: ");
            Serial.print(robots[idx].name);
            Serial.print(" [");
            Serial.print(macStr);
            Serial.println("]");
            printPrompt();
        }
        return;
    }

    // New robot
    if (robotCount >= MAX_ROBOTS) {
        Serial.println("[Swarm] WARNING — robot registry full, ignoring new robot");
        return;
    }

    idx = robotCount++;
    memcpy(robots[idx].mac, mac, 6);
    snprintf(robots[idx].name, sizeof(robots[idx].name), "R%d", idx + 1);
    robots[idx].lastSeenMs = millis();
    robots[idx].active = true;

    char macStr[18];
    swarmMacToString(mac, macStr);
    Serial.print("NEW_ROBOT: ");
    Serial.print(robots[idx].name);
    Serial.print(" [");
    Serial.print(macStr);
    Serial.println("]");
}

// ---------------------------------------------------------------------------
// ESP-NOW callbacks
// ---------------------------------------------------------------------------

static void onEspNowRecv(const esp_now_recv_info_t* info,
                          const uint8_t* data, int len) {
    if (len < (int)SWARM_HEADER_SIZE) return;

    const SwarmPacket* pkt = (const SwarmPacket*)data;

    // Ignore our own broadcasts
    if (swarmMacMatch(pkt->sender_mac, myMac)) return;

    switch (pkt->msg_type) {
        case SWARM_MSG_HELLO:
            registerRobot(pkt->sender_mac);
            break;

        case SWARM_MSG_REPLY: {
            // Find the robot name for this MAC
            int idx = findRobotByMac(pkt->sender_mac);
            const char* name = (idx >= 0) ? robots[idx].name : "???";

            // Print the reply with robot name prefix
            // Payload may contain multiple lines — prefix each one
            String payload(pkt->payload);
            int start = 0;
            while (start < (int)payload.length()) {
                int nl = payload.indexOf('\n', start);
                String line;
                if (nl >= 0) {
                    line = payload.substring(start, nl);
                    start = nl + 1;
                } else {
                    line = payload.substring(start);
                    start = payload.length();
                }
                if (line.length() > 0) {
                    Serial.print(name);
                    Serial.print("> ");
                    Serial.println(line);
                }
            }
            break;
        }

        default:
            break;  // Ignore CMD messages (those are for nodes)
    }
}

// ---------------------------------------------------------------------------
// ESP-NOW initialization
// ---------------------------------------------------------------------------

static void initEspNow() {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    // Force WiFi channel reliably (promiscuous mode trick for ESP-IDF 5.x)
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_channel(SWARM_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
    esp_wifi_set_promiscuous(false);

    // Read own MAC
    WiFi.macAddress(myMac);
    swarmMacToString(myMac, myMacStr);

    if (esp_now_init() != ESP_OK) {
        Serial.println("[Swarm] ERROR — ESP-NOW init failed!");
        return;
    }

    esp_now_register_recv_cb(onEspNowRecv);

    // Add broadcast peer
    esp_now_peer_info_t peer;
    memset(&peer, 0, sizeof(peer));
    memcpy(peer.peer_addr, SWARM_BROADCAST_MAC, 6);
    peer.channel = 0;  // 0 = use current channel (avoids mismatch)
    peer.encrypt = false;

    if (esp_now_add_peer(&peer) != ESP_OK) {
        Serial.println("[Swarm] ERROR — failed to add broadcast peer");
    }

    Serial.print("[Swarm] Master MAC: ");
    Serial.println(myMacStr);

    // Verify channel
    uint8_t primary;
    wifi_second_chan_t secondary;
    esp_wifi_get_channel(&primary, &secondary);
    Serial.print("[Swarm] WiFi channel: ");
    Serial.println(primary);
}

// ---------------------------------------------------------------------------
// Send a command to robot(s) via ESP-NOW
// ---------------------------------------------------------------------------

static void sendCommand(const uint8_t targetMac[6], const char* command) {
    SwarmPacket pkt;
    memset(&pkt, 0, sizeof(pkt));
    pkt.msg_type = SWARM_MSG_CMD;
    memcpy(pkt.target_mac, targetMac, 6);
    memcpy(pkt.sender_mac, myMac, 6);
    pkt.seq = txSeq++;

    size_t cmdLen = strlen(command);
    if (cmdLen >= SWARM_EFFECTIVE_PAYLOAD) cmdLen = SWARM_EFFECTIVE_PAYLOAD - 1;
    memcpy(pkt.payload, command, cmdLen);
    pkt.payload[cmdLen] = '\0';

    esp_now_send(SWARM_BROADCAST_MAC, (const uint8_t*)&pkt,
                 SWARM_HEADER_SIZE + cmdLen + 1);

    lastCmdSentMs = millis();
    waitingForReply = true;
}

// ---------------------------------------------------------------------------
// Master-only commands
// ---------------------------------------------------------------------------

static void cmdSwarmList() {
    Serial.println("─────────────────────────────────────────────────────");
    Serial.println("  Swarm — Discovered Robots");
    Serial.println("─────────────────────────────────────────────────────");

    if (robotCount == 0) {
        Serial.println("  (no robots discovered yet)");
        Serial.println();
        Serial.println("  Power on robot arms to trigger auto-discovery.");
    } else {
        uint32_t now = millis();
        for (int i = 0; i < robotCount; i++) {
            char macStr[18];
            swarmMacToString(robots[i].mac, macStr);
            uint32_t ago = (now - robots[i].lastSeenMs) / 1000;

            Serial.print("  ");
            Serial.print(robots[i].name);

            // Pad name to 10 chars
            int nameLen = strlen(robots[i].name);
            for (int p = nameLen; p < 10; p++) Serial.print(' ');

            Serial.print(macStr);
            Serial.print("  ");

            if (ago < 5) {
                Serial.print("online");
            } else {
                Serial.print(ago);
                Serial.print("s ago");
            }

            if (!robots[i].active) {
                Serial.print("  [OFFLINE]");
            }

            Serial.println();
        }
    }

    Serial.println("─────────────────────────────────────────────────────");
}

static void cmdSwarmPing() {
    // Send a special "ping" that triggers robots to re-send HELLO
    // We just broadcast a CMD with "ping" — nodes don't know this command
    // but they'll respond with "Unknown command" which proves they're alive.
    // Better: nodes can recognize "ping" as a special no-op that sends HELLO.
    Serial.println("[Swarm] Requesting HELLO from all robots...");

    // Actually, we can't force a HELLO — just note when we last saw them.
    // The nodes periodically HELLO every 30s anyway.
    // For now, just show the list.
    cmdSwarmList();
}

static void cmdSwarmRename(const String& args) {
    // Parse: "R1 NewName"
    int sp = args.indexOf(' ');
    if (sp < 0) {
        Serial.println("Usage: swarm rename <current_name> <new_name>");
        return;
    }

    String oldName = args.substring(0, sp);
    String newName = args.substring(sp + 1);
    oldName.trim();
    newName.trim();

    int idx = findRobotByName(oldName);
    if (idx < 0) {
        Serial.print("Unknown robot: '");
        Serial.print(oldName);
        Serial.println("'. Use 'swarm list'");
        return;
    }

    if (newName.length() >= sizeof(robots[0].name)) {
        Serial.println("Name too long (max 15 chars)");
        return;
    }

    strncpy(robots[idx].name, newName.c_str(), sizeof(robots[idx].name) - 1);
    robots[idx].name[sizeof(robots[idx].name) - 1] = '\0';

    Serial.print("OK — ");
    Serial.print(oldName);
    Serial.print(" renamed to ");
    Serial.println(newName);
}

static void cmdHelp() {
    Serial.println("══════════════════════════════════════════════════════");
    Serial.println("  Mira Master Console — Commands");
    Serial.println("══════════════════════════════════════════════════════");
    Serial.println();
    Serial.println("  ── Targeting ──");
    Serial.println("  <command>                 Send to ALL robots");
    Serial.println("  @R1 <command>             Send to robot R1");
    Serial.println("  @all <command>            Explicit broadcast");
    Serial.println("  @AA:BB:CC:DD:EE:FF <cmd>  Target by MAC");
    Serial.println();
    Serial.println("  ── Swarm Management ──");
    Serial.println("  swarm list                List discovered robots");
    Serial.println("  swarm ping                Show robot status");
    Serial.println("  swarm rename R1 NewName   Rename a robot");
    Serial.println();
    Serial.println("  ── Robot Commands (forwarded to nodes) ──");
    Serial.println("  home                      Home all servos");
    Serial.println("  where                     Show position (x,y,z)");
    Serial.println("  joints                    Show joint angles");
    Serial.println("  set <joint> <angle>       Set servo angle");
    Serial.println("  goto <x> <y> <z>          Move to position");
    Serial.println("  grip <angle>              Set grip angle");
    Serial.println("  move <x> <y> <z> [speed]  Smooth move");
    Serial.println("  stop                      Stop all motion");
    Serial.println("  gesture list              List gestures");
    Serial.println("  gesture <name>            Start gesture");
    Serial.println("  gesture <name> stop       Stop gesture");
    Serial.println("  smset <joint> <angle>     Smooth servo move");
    Serial.println("  timed_set B S E G <ms>   Timed move (all joints)");
    Serial.println("  test <name>               Servo test (blocking)");
    Serial.println();
    Serial.println("  help                      Show this message");
    Serial.println("══════════════════════════════════════════════════════");
}

// ---------------------------------------------------------------------------
// Command processing
// ---------------------------------------------------------------------------

static void processCommand(const String& line) {
    String cmd = line;
    cmd.trim();
    if (cmd.length() == 0) return;

    // --- Master-local commands ---
    if (cmd == "help" || cmd == "?") {
        cmdHelp();
        return;
    }
    if (cmd.startsWith("swarm ")) {
        String sub = cmd.substring(6);
        sub.trim();
        if (sub == "list") {
            cmdSwarmList();
        } else if (sub == "ping") {
            cmdSwarmPing();
        } else if (sub.startsWith("rename ")) {
            cmdSwarmRename(sub.substring(7));
        } else {
            Serial.println("Usage: swarm list | swarm ping | swarm rename <old> <new>");
        }
        return;
    }
    if (cmd == "swarm") {
        Serial.println("Usage: swarm list | swarm ping | swarm rename <old> <new>");
        return;
    }

    // --- Parse target prefix ---
    uint8_t targetMac[6];
    String robotCmd;

    if (cmd.startsWith("@")) {
        // Extract target and command
        int sp = cmd.indexOf(' ');
        if (sp < 0) {
            Serial.println("Usage: @<target> <command>");
            return;
        }

        String target = cmd.substring(1, sp);  // Remove '@'
        robotCmd = cmd.substring(sp + 1);
        robotCmd.trim();

        if (target.equalsIgnoreCase("all")) {
            // Broadcast
            memcpy(targetMac, SWARM_BROADCAST_MAC, 6);
        } else if (target.indexOf(':') > 0) {
            // Raw MAC address
            if (!swarmStringToMac(target.c_str(), targetMac)) {
                Serial.print("Invalid MAC: ");
                Serial.println(target);
                return;
            }
        } else {
            // Robot name lookup
            int idx = findRobotByName(target);
            if (idx < 0) {
                Serial.print("Unknown robot: '");
                Serial.print(target);
                Serial.println("'. Use 'swarm list'");
                return;
            }
            memcpy(targetMac, robots[idx].mac, 6);
        }
    } else {
        // No prefix — broadcast to all
        memcpy(targetMac, SWARM_BROADCAST_MAC, 6);
        robotCmd = cmd;
    }

    if (robotCmd.length() == 0) {
        Serial.println("No command specified");
        return;
    }

    // --- Send over ESP-NOW ---
    if (swarmIsBroadcast(targetMac)) {
        Serial.print("[→ ALL] ");
    } else {
        int idx = findRobotByMac(targetMac);
        if (idx >= 0) {
            Serial.print("[→ ");
            Serial.print(robots[idx].name);
            Serial.print("] ");
        } else {
            char macStr[18];
            swarmMacToString(targetMac, macStr);
            Serial.print("[→ ");
            Serial.print(macStr);
            Serial.print("] ");
        }
    }
    Serial.println(robotCmd);

    sendCommand(targetMac, robotCmd.c_str());
}

// ---------------------------------------------------------------------------
// Prompt
// ---------------------------------------------------------------------------

static void printPrompt() {
    Serial.print("master> ");
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(1000);  // Give USB CDC time to enumerate

    Serial.println();
    Serial.println("══════════════════════════════════════════");
    Serial.println("  Mira Master MCU — v0.1.0");
    Serial.println("  Swarm Controller (ESP-NOW)");
    Serial.println("══════════════════════════════════════════");
    Serial.println();

    // --- LED breathing ---
    ledcAttach(LED_PIN, LED_PWM_FREQ, LED_PWM_RESOLUTION);
    ledcWrite(LED_PIN, LED_ACTIVE_LOW ? ((1 << LED_PWM_RESOLUTION) - 1) : 0);
    xTaskCreate(ledBreatheTask, "led_breathe", LED_TASK_STACK, nullptr,
                LED_TASK_PRIORITY, nullptr);
    Serial.println("[StatusLed] Breathing started (fast)");

    initEspNow();

    Serial.println();
    Serial.println("Waiting for robots to check in...");
    Serial.println("Type 'help' for available commands.");
    Serial.println();
    printPrompt();
}

void loop() {
    // --- Serial input from laptop ---
    while (Serial.available()) {
        char c = Serial.read();

        if (c == '\n' || c == '\r') {
            if (inputBuffer.length() > 0) {
                Serial.println();
                processCommand(inputBuffer);
                inputBuffer = "";
                printPrompt();
            }
        } else if (c == '\b' || c == 127) {
            if (inputBuffer.length() > 0) {
                inputBuffer.remove(inputBuffer.length() - 1);
                Serial.print("\b \b");
            }
        } else {
            inputBuffer += c;
            Serial.print(c);
        }
    }

    // --- Mark robots as offline if HELLO timeout exceeded ---
    uint32_t now = millis();
    for (int i = 0; i < robotCount; i++) {
        if (robots[i].active && (now - robots[i].lastSeenMs > HELLO_TIMEOUT_MS)) {
            robots[i].active = false;
            Serial.println();
            Serial.print("[Swarm] ");
            Serial.print(robots[i].name);
            Serial.println(" went offline (no HELLO received)");
            printPrompt();
        }
    }
}

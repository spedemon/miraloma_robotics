/**
 * Mira Swarm Controller — Client-Side Application
 *
 * Manages WebSocket connection to the Flask server, handles robot
 * selection, slider control, gesture toggling, and console logging.
 */

// ---------------------------------------------------------------------------
// Arm Geometry & IK/FK (mirrored from robotarm_mcu/include/config.h)
// ---------------------------------------------------------------------------

const ARM_BASE_HEIGHT  = 22.0;   // d0: base pivot to shoulder pivot (mm)
const ARM_LINK1_LENGTH = 40.0;   // L1: shoulder pivot to elbow pivot (mm)
const ARM_LINK2_LENGTH = 86.0;   // L2: elbow pivot to end effector (mm)

// Servo ↔ geometric angle mapping (from config.h)
const SERVO_BASE_OFFSET          = 0.0;
const SERVO_BASE_DIRECTION       = 1.0;
const SERVO_SHOULDER_OFFSET      = 90.0;
const SERVO_SHOULDER_DIRECTION   = -1.0;
const SERVO_ELBOW_OFFSET         = 0.0;
const SERVO_ELBOW_DIRECTION      = -1.0;

// Joint limits (servo degrees, from config.h)
const JOINT_BASE_MIN     = -90;
const JOINT_BASE_MAX     =  90;
const JOINT_SHOULDER_MIN = -109;
const JOINT_SHOULDER_MAX =  104;
const JOINT_ELBOW_MIN    = -100;
const JOINT_ELBOW_MAX    =  100;

const DEG2RAD = Math.PI / 180.0;
const RAD2DEG = 180.0 / Math.PI;

/**
 * Forward Kinematics: servo angles (degrees) → Cartesian position (mm).
 * Mirrors ArmController::forwardKinematics() from ArmController.cpp.
 */
function fk(baseServoDeg, shoulderServoDeg, elbowServoDeg) {
    const L1 = ARM_LINK1_LENGTH;
    const L2 = ARM_LINK2_LENGTH;
    const d0 = ARM_BASE_HEIGHT;

    // Servo → geometric angles (radians)
    const baseGeo     = ((baseServoDeg     - SERVO_BASE_OFFSET)     / SERVO_BASE_DIRECTION)     * DEG2RAD;
    const shoulderGeo = ((shoulderServoDeg - SERVO_SHOULDER_OFFSET) / SERVO_SHOULDER_DIRECTION) * DEG2RAD;
    const elbowGeo    = ((elbowServoDeg    - SERVO_ELBOW_OFFSET)   / SERVO_ELBOW_DIRECTION)   * DEG2RAD;

    // End-effector in the vertical plane
    const r    = L1 * Math.cos(shoulderGeo) + L2 * Math.cos(shoulderGeo + elbowGeo);
    const zEff = L1 * Math.sin(shoulderGeo) + L2 * Math.sin(shoulderGeo + elbowGeo);

    return {
        x: r * Math.cos(baseGeo),
        y: r * Math.sin(baseGeo),
        z: zEff + d0,
    };
}

/**
 * Inverse Kinematics: Cartesian position (mm) → servo angles (degrees).
 * Mirrors ArmController::solve() from ArmController.cpp.
 * Returns { base, shoulder, elbow } or null if unreachable.
 */
function ik(x, y, z) {
    const L1 = ARM_LINK1_LENGTH;
    const L2 = ARM_LINK2_LENGTH;
    const d0 = ARM_BASE_HEIGHT;

    // Base angle (top-down view)
    const baseGeo = Math.atan2(y, x);

    // 2-link planar IK in the vertical plane
    const r    = Math.sqrt(x * x + y * y);
    const zEff = z - d0;

    const distSq = r * r + zEff * zEff;
    const D = (distSq - L1 * L1 - L2 * L2) / (2.0 * L1 * L2);

    if (D * D > 1.0) return null;  // Unreachable

    // Elbow angle (elbow-down solution)
    const elbowGeo = Math.atan2(-Math.sqrt(1.0 - D * D), D);

    // Shoulder angle
    const shoulderGeo = Math.atan2(zEff, r)
                      - Math.atan2(L2 * Math.sin(elbowGeo), L1 + L2 * Math.cos(elbowGeo));

    // Geometric → servo angles
    const baseAngle     = SERVO_BASE_OFFSET     + SERVO_BASE_DIRECTION     * (baseGeo     * RAD2DEG);
    const shoulderAngle = SERVO_SHOULDER_OFFSET  + SERVO_SHOULDER_DIRECTION * (shoulderGeo * RAD2DEG);
    const elbowAngle    = SERVO_ELBOW_OFFSET     + SERVO_ELBOW_DIRECTION   * (elbowGeo    * RAD2DEG);

    // Check joint limits
    if (baseAngle     < JOINT_BASE_MIN     || baseAngle     > JOINT_BASE_MAX)     return null;
    if (shoulderAngle < JOINT_SHOULDER_MIN || shoulderAngle > JOINT_SHOULDER_MAX) return null;
    if (elbowAngle    < JOINT_ELBOW_MIN    || elbowAngle    > JOINT_ELBOW_MAX)    return null;

    return { base: baseAngle, shoulder: shoulderAngle, elbow: elbowAngle };
}

// ---------------------------------------------------------------------------
// Gesture definitions
// ---------------------------------------------------------------------------

const GESTURES = [
    { id: "dance",     label: "💃 Dance",          continuous: true  },
    { id: "break",     label: "🕺 Break",          continuous: true  },
    { id: "crab",      label: "🦀 Crab",           continuous: true  },
    { id: "circle",    label: "⭕ Side Circle",    continuous: true  },
    { id: "square",    label: "🟦 Side Square",    continuous: true  },
    { id: "triangle",  label: "🔺 Side Triangle",  continuous: true  },
    { id: "fcircle",   label: "🌀 Front Circle",   continuous: true  },
    { id: "fsquare",   label: "🎯 Front Square",   continuous: true  },
    { id: "ftriangle", label: "📐 Front Triangle",  continuous: true  },
    { id: "bow",       label: "🎩 Bow",            continuous: false },
    { id: "wave",      label: "🌊 Wave",           continuous: true  },
];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let socket = null;
let robots = [];
let selectedTarget = null;  // null = all robots, or { name, mac, masterName }
let activeGesture = null;   // gesture id currently running
let serialConnected = false;
let openMenuMac = null;     // MAC of robot whose context menu is open

// Control mode & motion type
let controlMode = 'joint';  // 'cartesian' or 'joint'
let motionType = 'smooth';      // 'smooth' or 'instant'

// Slider throttle
let sliderThrottleTimer = null;
let gripThrottleTimer = null;
const SLIDER_THROTTLE_MS = 100;

// ---------------------------------------------------------------------------
// Socket.IO Connection
// ---------------------------------------------------------------------------

function initSocket() {
    socket = io();

    socket.on("connect", () => {
        addConsoleLine("Connected to server", "system");
    });

    socket.on("disconnect", () => {
        addConsoleLine("Disconnected from server", "error");
    });

    socket.on("serial_status", (data) => {
        serialConnected = data.connected;
        updateSerialUI(data);
    });

    socket.on("robot_list", (data) => {
        robots = data;
        renderRobotList();
    });

    socket.on("console_line", (data) => {
        addConsoleLine(data.text, data.type, data.time);
    });
}

// ---------------------------------------------------------------------------
// Serial UI
// ---------------------------------------------------------------------------

function updateSerialUI(data) {
    const badge = document.getElementById("serial-badge");
    const label = document.getElementById("serial-label");
    const banner = document.getElementById("disconnected-banner");

    if (data.connected) {
        badge.classList.add("connected");
        label.textContent = data.port || "Connected";
        banner.style.display = "none";
    } else {
        badge.classList.remove("connected");
        label.textContent = "Disconnected";
        banner.style.display = "flex";
    }
}

// ---------------------------------------------------------------------------
// Settings Modal
// ---------------------------------------------------------------------------

function openSettings() {
    document.getElementById("settings-modal").classList.add("visible");
    refreshPorts();
}

function closeSettings() {
    document.getElementById("settings-modal").classList.remove("visible");
}

async function refreshPorts() {
    const select = document.getElementById("port-select");
    select.innerHTML = '<option value="">Loading...</option>';

    try {
        const res = await fetch("/api/serial/ports");
        const data = await res.json();

        select.innerHTML = "";
        if (data.ports.length === 0) {
            select.innerHTML = '<option value="">No ports found</option>';
            return;
        }

        data.ports.forEach((p) => {
            const opt = document.createElement("option");
            opt.value = p.device;
            opt.textContent = `${p.device} — ${p.description}`;
            if (p.device === data.current) opt.selected = true;
            select.appendChild(opt);
        });
    } catch (e) {
        select.innerHTML = '<option value="">Error loading ports</option>';
    }
}

async function connectSerial() {
    const port = document.getElementById("port-select").value;
    if (!port) return;

    try {
        const res = await fetch("/api/serial/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ port }),
        });
        const data = await res.json();
        if (data.ok) {
            closeSettings();
            addConsoleLine(`Connected to ${port}`, "system");
        } else {
            addConsoleLine(`Failed to connect to ${port}`, "error");
        }
    } catch (e) {
        addConsoleLine("Connection error", "error");
    }
}

async function disconnectSerial() {
    try {
        await fetch("/api/serial/disconnect", { method: "POST" });
        closeSettings();
        addConsoleLine("Disconnected from serial port", "warning");
    } catch (e) {
        // ignore
    }
}

// ---------------------------------------------------------------------------
// Robot List
// ---------------------------------------------------------------------------

function renderRobotList() {
    const list = document.getElementById("robot-list");
    const emptyState = document.getElementById("empty-state");
    const countEl = document.getElementById("robot-count");

    // Update count (online / total)
    const onlineCount = robots.filter((r) => r.online).length;
    const totalCount = robots.length;
    countEl.textContent = `${onlineCount}/${totalCount}`;

    if (robots.length === 0) {
        emptyState.style.display = "flex";
        // Remove any existing robot items
        list.querySelectorAll(".robot-item").forEach((el) => el.remove());
        return;
    }

    emptyState.style.display = "none";

    // Build list
    // Remove old items
    list.querySelectorAll(".robot-item").forEach((el) => el.remove());

    robots.forEach((robot) => {
        const item = document.createElement("div");
        item.className = "robot-item";
        item.dataset.mac = robot.mac;

        if (selectedTarget && selectedTarget.mac === robot.mac) {
            item.classList.add("selected");
        }

        const isOnline = robot.online;
        if (!isOnline) {
            item.classList.add("offline");
        }
        const menuOpen = openMenuMac === robot.mac;

        item.innerHTML = `
            <div class="robot-status-dot ${isOnline ? "online" : ""}"></div>
            <div class="robot-info">
                <div class="robot-name">${escapeHtml(robot.name)}</div>
                <div class="robot-mac">${robot.mac}</div>
            </div>
            <button class="robot-menu-btn ${menuOpen ? "open" : ""}" data-mac="${robot.mac}" title="Actions"></button>
            <div class="robot-context-menu ${menuOpen ? "visible" : ""}" data-mac="${robot.mac}">
                <button class="robot-context-item" data-action="rename" data-mac="${robot.mac}">
                    <span class="ctx-icon">✏️</span> Rename
                </button>
            </div>
        `;

        // Click on the main area to select the robot
        item.addEventListener("click", (e) => {
            // Don't select if clicking the kebab button or context menu
            if (e.target.closest(".robot-menu-btn") || e.target.closest(".robot-context-menu")) return;
            closeAllMenus();
            selectRobot(robot);
        });

        // Kebab menu button
        const menuBtn = item.querySelector(".robot-menu-btn");
        menuBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            toggleRobotMenu(robot.mac);
        });

        // Context menu item clicks
        const ctxItems = item.querySelectorAll(".robot-context-item");
        ctxItems.forEach((ci) => {
            ci.addEventListener("click", (e) => {
                e.stopPropagation();
                const action = ci.dataset.action;
                closeAllMenus();
                if (action === "rename") {
                    // Re-query the item after menu closes
                    setTimeout(() => {
                        const freshItem = document.querySelector(`.robot-item[data-mac="${robot.mac}"]`);
                        if (freshItem) startRename(freshItem, robot);
                    }, 0);
                }
            });
        });

        list.appendChild(item);
    });
}

function selectRobot(robot) {
    selectedTarget = robot;

    // Update UI
    document.getElementById("all-robots-btn").classList.remove("active");
    renderRobotList();
    updateTargetBanner();
}

function selectAllRobots() {
    selectedTarget = null;

    document.getElementById("all-robots-btn").classList.add("active");
    renderRobotList();
    updateTargetBanner();
}

function updateTargetBanner() {
    const nameEl = document.getElementById("target-name");
    const badgeEl = document.getElementById("target-badge");

    if (selectedTarget) {
        nameEl.textContent = selectedTarget.name;
        nameEl.className = "target-name single";
        badgeEl.textContent = "THIS ONE ☝️";
        badgeEl.className = "target-badge single";
        document.getElementById("all-robots-btn").classList.remove("active");
    } else {
        nameEl.textContent = "All Robots";
        nameEl.className = "target-name all";
        badgeEl.textContent = "";
        badgeEl.className = "target-badge";
        document.getElementById("all-robots-btn").classList.add("active");
    }
}

// ---------------------------------------------------------------------------
// Context Menu
// ---------------------------------------------------------------------------

function toggleRobotMenu(mac) {
    if (openMenuMac === mac) {
        closeAllMenus();
    } else {
        openMenuMac = mac;
        renderRobotList();
    }
}

function closeAllMenus() {
    if (openMenuMac !== null) {
        openMenuMac = null;
        // Just hide menus without full re-render to avoid flicker
        document.querySelectorAll(".robot-context-menu.visible").forEach((m) => m.classList.remove("visible"));
        document.querySelectorAll(".robot-menu-btn.open").forEach((b) => b.classList.remove("open"));
    }
}

// ---------------------------------------------------------------------------
// Rename
// ---------------------------------------------------------------------------

function startRename(itemEl, robot) {
    const nameEl = itemEl.querySelector(".robot-name");
    if (!nameEl) return;
    const currentName = robot.name;

    const input = document.createElement("input");
    input.type = "text";
    input.className = "robot-rename-input";
    input.value = currentName;
    input.maxLength = 15;

    nameEl.replaceWith(input);
    input.focus();
    input.select();

    let finished = false;

    const finish = async (save) => {
        if (finished) return;
        finished = true;
        const newName = input.value.trim();
        input.removeEventListener("keydown", onKey);
        input.removeEventListener("blur", onBlur);

        if (save && newName && newName !== currentName) {
            try {
                const res = await fetch("/api/robots/rename", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ mac: robot.mac, name: newName }),
                });
                const data = await res.json();
                if (data.ok) {
                    addConsoleLine(`Renamed ${currentName} → ${newName}`, "system");
                }
            } catch (e) {
                addConsoleLine("Rename failed", "error");
            }
        } else {
            renderRobotList();
        }
    };

    const onKey = (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            finish(true);
        } else if (e.key === "Escape") {
            e.preventDefault();
            finish(false);
        }
    };

    const onBlur = () => finish(true);

    input.addEventListener("keydown", onKey);
    input.addEventListener("blur", onBlur);
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function getTargetName() {
    if (selectedTarget) {
        return selectedTarget.masterName || selectedTarget.name;
    }
    return "all";
}

function sendCommand(cmd) {
    if (!socket) return;
    socket.emit("send_command", {
        target: getTargetName(),
        command: cmd,
    });
}

function sendHome() {
    // Use smooth moves instead of instant "home" for gentler motion
    sendCommand("smset base 0");
    sendCommand("smset shoulder 0");
    sendCommand("smset elbow 0");
    sendCommand("smset grip 0");
    // Reset joint sliders to home (all 0°)
    document.getElementById("slider-base").value = 0;
    document.getElementById("slider-shoulder").value = 0;
    document.getElementById("slider-elbow").value = 0;
    document.getElementById("slider-grip-joint").value = 0;
    document.getElementById("slider-grip").value = 0;
    // Compute Cartesian home position from FK
    const homePos = fk(0, 0, 0);
    document.getElementById("slider-x").value = Math.max(0, homePos.x.toFixed(1));
    document.getElementById("slider-y").value = homePos.y.toFixed(1);
    document.getElementById("slider-z").value = homePos.z.toFixed(1);
    updateSliderValues();
}

function sendWhere() {
    sendCommand("where");
    // Auto-show the debug console so the user can see the response
    const panel = document.getElementById("console-panel");
    if (panel && panel.classList.contains("collapsed")) {
        toggleConsole();
    }
}

function sendStop() {
    sendCommand("stop");
    setActiveGesture(null);
}

function sendCartesianMove() {
    const x = parseFloat(document.getElementById("slider-x").value);
    const y = parseFloat(document.getElementById("slider-y").value);
    const z = parseFloat(document.getElementById("slider-z").value);
    if (motionType === 'smooth') {
        sendCommand(`move ${x} ${y} ${z}`);
    } else {
        sendCommand(`goto ${x} ${y} ${z}`);
    }
}

function sendJointMove(joint) {
    const angle = parseFloat(document.getElementById(`slider-${joint}`).value);
    if (motionType === 'smooth') {
        sendCommand(`smset ${joint} ${angle}`);
    } else {
        sendCommand(`set ${joint} ${angle}`);
    }
}

function sendGrip() {
    if (controlMode === 'joint') {
        const grip = parseFloat(document.getElementById("slider-grip-joint").value);
        if (motionType === 'smooth') {
            sendCommand(`smset grip ${grip}`);
        } else {
            sendCommand(`set grip ${grip}`);
        }
    } else {
        const grip = parseFloat(document.getElementById("slider-grip").value);
        sendCommand(`grip ${grip}`);
    }
}

// ---------------------------------------------------------------------------
// Mode & Motion Toggles
// ---------------------------------------------------------------------------

function setControlMode(mode) {
    const prevMode = controlMode;
    controlMode = mode;

    // Sync slider values between modes
    if (prevMode === 'cartesian' && mode === 'joint') {
        syncCartesianToJoint();
    } else if (prevMode === 'joint' && mode === 'cartesian') {
        syncJointToCartesian();
    }

    document.getElementById('mode-cartesian').classList.toggle('active', mode === 'cartesian');
    document.getElementById('mode-joint').classList.toggle('active', mode === 'joint');

    document.getElementById('sliders-cartesian').style.display = mode === 'cartesian' ? '' : 'none';
    document.getElementById('sliders-joint').style.display = mode === 'joint' ? '' : 'none';
}

/**
 * Sync Cartesian slider values → Joint sliders via IK.
 * Called when switching from Cartesian to Joint mode,
 * and in the background when Cartesian sliders change.
 */
function syncCartesianToJoint() {
    const x = parseFloat(document.getElementById("slider-x").value);
    const y = parseFloat(document.getElementById("slider-y").value);
    const z = parseFloat(document.getElementById("slider-z").value);

    const result = ik(x, y, z);
    if (result) {
        document.getElementById("slider-base").value = result.base.toFixed(1);
        document.getElementById("slider-shoulder").value = result.shoulder.toFixed(1);
        document.getElementById("slider-elbow").value = result.elbow.toFixed(1);
    }
    // Sync grip (same value in both modes)
    document.getElementById("slider-grip-joint").value =
        document.getElementById("slider-grip").value;
    updateSliderValues();
}

/**
 * Sync Joint slider values → Cartesian sliders via FK.
 * Called when switching from Joint to Cartesian mode,
 * and in the background when Joint sliders change.
 */
function syncJointToCartesian() {
    const base     = parseFloat(document.getElementById("slider-base").value);
    const shoulder = parseFloat(document.getElementById("slider-shoulder").value);
    const elbow    = parseFloat(document.getElementById("slider-elbow").value);

    const pos = fk(base, shoulder, elbow);

    // Clamp to slider min/max to avoid out-of-range values
    const sliderX = document.getElementById("slider-x");
    const sliderY = document.getElementById("slider-y");
    const sliderZ = document.getElementById("slider-z");

    sliderX.value = Math.max(sliderX.min, Math.min(sliderX.max, pos.x.toFixed(1)));
    sliderY.value = Math.max(sliderY.min, Math.min(sliderY.max, pos.y.toFixed(1)));
    sliderZ.value = Math.max(sliderZ.min, Math.min(sliderZ.max, pos.z.toFixed(1)));

    // Sync grip
    document.getElementById("slider-grip").value =
        document.getElementById("slider-grip-joint").value;
    updateSliderValues();
}

function setMotionType(type) {
    motionType = type;

    document.getElementById('motion-smooth').classList.toggle('active', type === 'smooth');
    document.getElementById('motion-instant').classList.toggle('active', type === 'instant');
}

// ---------------------------------------------------------------------------
// Slider Tick Marks
// ---------------------------------------------------------------------------

function initSliderTicks() {
    document.querySelectorAll('.slider-ticks').forEach((container) => {
        const min = parseFloat(container.dataset.min);
        const max = parseFloat(container.dataset.max);
        const tickStep = parseFloat(container.dataset.tick);
        const labelStep = parseFloat(container.dataset.label);
        const range = max - min;

        // Clear any existing ticks
        container.innerHTML = '';

        for (let v = min; v <= max; v += tickStep) {
            // Round to avoid floating point drift
            const val = Math.round(v * 100) / 100;
            const pct = ((val - min) / range) * 100;
            const isMajor = Math.abs(val % labelStep) < 0.01 || Math.abs(val % labelStep - labelStep) < 0.01;

            const tick = document.createElement('div');
            tick.className = 'slider-tick';
            tick.style.left = pct + '%';

            const line = document.createElement('div');
            line.className = 'slider-tick-line ' + (isMajor ? 'major' : 'minor');
            tick.appendChild(line);

            if (isMajor) {
                const label = document.createElement('div');
                label.className = 'slider-tick-label';
                label.textContent = val;
                tick.appendChild(label);
            }

            container.appendChild(tick);
        }
    });
}

// ---------------------------------------------------------------------------
// Sliders
// ---------------------------------------------------------------------------

function initSliders() {
    // Cartesian sliders
    ["slider-x", "slider-y", "slider-z"].forEach((id) => {
        document.getElementById(id).addEventListener("input", () => {
            updateSliderValues();
            // Keep joint sliders in sync (background, no commands sent for joints)
            syncCartesianToJoint();
            throttledSend(() => sendCartesianMove());
        });
    });

    document.getElementById("slider-grip").addEventListener("input", () => {
        updateSliderValues();
        // Sync grip to joint mode
        document.getElementById("slider-grip-joint").value =
            document.getElementById("slider-grip").value;
        throttledSendGrip();
    });

    // Joint sliders
    ["base", "shoulder", "elbow"].forEach((joint) => {
        document.getElementById(`slider-${joint}`).addEventListener("input", () => {
            updateSliderValues();
            // Keep cartesian sliders in sync (background, no commands sent for cartesian)
            syncJointToCartesian();
            const j = joint; // capture for closure
            throttledSend(() => sendJointMove(j));
        });
    });

    document.getElementById("slider-grip-joint").addEventListener("input", () => {
        updateSliderValues();
        // Sync grip to cartesian mode
        document.getElementById("slider-grip").value =
            document.getElementById("slider-grip-joint").value;
        throttledSendGrip();
    });
}

function updateSliderValues() {
    // Cartesian
    document.getElementById("value-x").textContent = parseFloat(document.getElementById("slider-x").value).toFixed(1);
    document.getElementById("value-y").textContent = parseFloat(document.getElementById("slider-y").value).toFixed(1);
    document.getElementById("value-z").textContent = parseFloat(document.getElementById("slider-z").value).toFixed(1);
    document.getElementById("value-grip").textContent = parseInt(document.getElementById("slider-grip").value);

    // Joint
    document.getElementById("value-base").textContent = parseFloat(document.getElementById("slider-base").value).toFixed(1);
    document.getElementById("value-shoulder").textContent = parseFloat(document.getElementById("slider-shoulder").value).toFixed(1);
    document.getElementById("value-elbow").textContent = parseFloat(document.getElementById("slider-elbow").value).toFixed(1);
    document.getElementById("value-grip-joint").textContent = parseInt(document.getElementById("slider-grip-joint").value);
}

function throttledSend(fn) {
    if (sliderThrottleTimer) clearTimeout(sliderThrottleTimer);
    sliderThrottleTimer = setTimeout(() => {
        fn();
        sliderThrottleTimer = null;
    }, SLIDER_THROTTLE_MS);
}

function throttledSendGrip() {
    if (gripThrottleTimer) clearTimeout(gripThrottleTimer);
    gripThrottleTimer = setTimeout(() => {
        sendGrip();
        gripThrottleTimer = null;
    }, SLIDER_THROTTLE_MS);
}

// ---------------------------------------------------------------------------
// Gestures
// ---------------------------------------------------------------------------

function initGestures() {
    const grid = document.getElementById("gesture-grid");
    grid.innerHTML = "";

    GESTURES.forEach((g) => {
        const btn = document.createElement("button");
        btn.className = "gesture-btn";
        btn.id = `gesture-${g.id}`;
        btn.innerHTML = `<span class="play-icon">▶</span> ${g.label}`;

        btn.addEventListener("click", () => {
            toggleGesture(g);
        });

        grid.appendChild(btn);
    });
}

function toggleGesture(gesture) {
    if (gesture.continuous) {
        if (activeGesture === gesture.id) {
            // Stop it
            sendCommand(`gesture ${gesture.id} stop`);
            setActiveGesture(null);
        } else {
            // Stop previous, start new
            if (activeGesture) {
                sendCommand(`gesture ${activeGesture} stop`);
            }
            sendCommand(`gesture ${gesture.id}`);
            setActiveGesture(gesture.id);
        }
    } else {
        // One-shot: just start it
        if (activeGesture) {
            sendCommand(`gesture ${activeGesture} stop`);
            setActiveGesture(null);
        }
        sendCommand(`gesture ${gesture.id}`);
    }
}

function setActiveGesture(id) {
    activeGesture = id;

    GESTURES.forEach((g) => {
        const btn = document.getElementById(`gesture-${g.id}`);
        if (!btn) return;

        if (g.id === id) {
            btn.classList.add("active");
            btn.innerHTML = `<span class="play-icon">⏹</span> ${g.label}`;
        } else {
            btn.classList.remove("active");
            btn.innerHTML = `<span class="play-icon">▶</span> ${g.label}`;
        }
    });
}

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------

const MAX_CONSOLE_LINES = 200;

function addConsoleLine(text, type = "info", time = null) {
    const body = document.getElementById("console-body");
    if (!time) {
        const now = new Date();
        time = now.toTimeString().substring(0, 8);
    }

    const line = document.createElement("div");
    line.className = `console-line ${type}`;
    line.innerHTML = `<span class="console-time">${time}</span><span class="console-text">${escapeHtml(text)}</span>`;

    body.appendChild(line);

    // Limit lines
    while (body.children.length > MAX_CONSOLE_LINES) {
        body.removeChild(body.firstChild);
    }

    // Auto-scroll
    body.scrollTop = body.scrollHeight;
}

function clearConsole() {
    document.getElementById("console-body").innerHTML = "";
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Keyframe Sequencer
// ---------------------------------------------------------------------------

let keyframes = [];
let kfPlaying = false;
let kfPlayStartMs = 0;
let kfPlayTimers = [];
let kfPlayRAF = null;
let kfCurrentIndex = -1;
let kfSpeedMultiplier = 1.0;
let kfPlayheadTimeMs = 0;  // current playhead position in ms (for seek)
let kfLooping = false;     // loop playback
let kfPlayStartOffsetMs = 0; // timeline offset when play started (for resume)

// Zoom: px per ms — mutable, drives timeline scale
const KF_ZOOM_MIN = 0.02;   // very zoomed out
const KF_ZOOM_MAX = 2.0;    // very zoomed in
const KF_ZOOM_DEFAULT = 0.2;
let KF_PX_PER_MS = KF_ZOOM_DEFAULT;

const KF_MIN_DURATION = 50;
const KF_DEFAULT_DURATION = 1000;
const KF_LABEL_OFFSET = 50;  // px, matches the track label width

function kfSetSpeed(val) {
    const v = parseFloat(val);
    if (isNaN(v) || v < 0.1) kfSpeedMultiplier = 0.1;
    else if (v > 10) kfSpeedMultiplier = 10;
    else kfSpeedMultiplier = v;
    // Update the input to reflect clamped value
    document.getElementById('kf-speed').value = kfSpeedMultiplier.toFixed(1);
}

// --- Zoom helpers ---

/** Convert a 0–100 slider value to px/ms using exponential interpolation */
function kfSliderToZoom(sliderVal) {
    const t = sliderVal / 100;  // 0..1
    return KF_ZOOM_MIN * Math.pow(KF_ZOOM_MAX / KF_ZOOM_MIN, t);
}

/** Convert px/ms to a 0–100 slider value (inverse of above) */
function kfZoomToSlider(zoom) {
    const t = Math.log(zoom / KF_ZOOM_MIN) / Math.log(KF_ZOOM_MAX / KF_ZOOM_MIN);
    return Math.round(Math.max(0, Math.min(100, t * 100)));
}

/** Apply a new zoom level, sync slider & label */
function kfUpdateZoom(newZoom, anchorScrollFraction) {
    const oldZoom = KF_PX_PER_MS;
    KF_PX_PER_MS = Math.max(KF_ZOOM_MIN, Math.min(KF_ZOOM_MAX, newZoom));

    // Update slider position
    const slider = document.getElementById('kf-zoom-slider');
    if (slider) slider.value = kfZoomToSlider(KF_PX_PER_MS);

    // Update percentage label (100% = default zoom)
    const pct = Math.round((KF_PX_PER_MS / KF_ZOOM_DEFAULT) * 100);
    const label = document.getElementById('kf-zoom-label');
    if (label) label.textContent = pct + '%';

    // Maintain scroll position around the anchor point
    if (typeof anchorScrollFraction === 'number') {
        const wrapper = document.getElementById('kf-timeline-wrapper');
        if (wrapper) {
            // Re-render first so container width updates
            kfRender();
            const container = document.getElementById('kf-timeline-container');
            const contentWidth = container ? container.scrollWidth : 0;
            const viewportWidth = wrapper.clientWidth;
            // Restore the same fraction of content at the center of the viewport
            wrapper.scrollLeft = anchorScrollFraction * (contentWidth / oldZoom * KF_PX_PER_MS) - viewportWidth / 2;
            return;  // kfRender already called
        }
    }

    kfRender();
}

function kfZoomIn() {
    const currentSlider = kfZoomToSlider(KF_PX_PER_MS);
    const newSlider = Math.min(100, currentSlider + 5);
    kfUpdateZoom(kfSliderToZoom(newSlider));
}

function kfZoomOut() {
    const currentSlider = kfZoomToSlider(KF_PX_PER_MS);
    const newSlider = Math.max(0, currentSlider - 5);
    kfUpdateZoom(kfSliderToZoom(newSlider));
}

function kfZoomFromSlider(val) {
    kfUpdateZoom(kfSliderToZoom(parseFloat(val)));
}

function kfZoomFit() {
    if (keyframes.length === 0) return;
    const totalMs = kfGetTotalDuration();
    const wrapper = document.getElementById('kf-timeline-wrapper');
    if (!wrapper) return;
    const availableWidth = wrapper.clientWidth - KF_LABEL_OFFSET - 30;  // 30px padding
    if (availableWidth <= 0) return;
    const fitZoom = availableWidth / totalMs;
    kfUpdateZoom(fitZoom);
}

function initKfZoom() {
    // Set slider to match default zoom
    const slider = document.getElementById('kf-zoom-slider');
    if (slider) slider.value = kfZoomToSlider(KF_ZOOM_DEFAULT);

    // Set initial label
    const label = document.getElementById('kf-zoom-label');
    if (label) label.textContent = '100%';

    // Ctrl+Scroll / pinch-to-zoom on the timeline wrapper
    const wrapper = document.getElementById('kf-timeline-wrapper');
    if (wrapper) {
        wrapper.addEventListener('wheel', (e) => {
            // Only intercept zoom gestures: Ctrl+wheel (mouse) or pinchZoom (trackpad ctrlKey)
            if (!e.ctrlKey && !e.metaKey) return;
            e.preventDefault();

            // Compute the anchor point: what time is under the cursor?
            const rect = wrapper.getBoundingClientRect();
            const cursorX = e.clientX - rect.left + wrapper.scrollLeft - KF_LABEL_OFFSET;
            const cursorTimeMs = cursorX / KF_PX_PER_MS;

            // Zoom in/out
            const delta = e.deltaY > 0 ? -3 : 3;
            const currentSlider = kfZoomToSlider(KF_PX_PER_MS);
            const newSlider = Math.max(0, Math.min(100, currentSlider + delta));
            const newZoom = kfSliderToZoom(newSlider);

            KF_PX_PER_MS = Math.max(KF_ZOOM_MIN, Math.min(KF_ZOOM_MAX, newZoom));

            // Update slider & label
            const sliderEl = document.getElementById('kf-zoom-slider');
            if (sliderEl) sliderEl.value = kfZoomToSlider(KF_PX_PER_MS);
            const pct = Math.round((KF_PX_PER_MS / KF_ZOOM_DEFAULT) * 100);
            const labelEl = document.getElementById('kf-zoom-label');
            if (labelEl) labelEl.textContent = pct + '%';

            // Re-render
            kfRender();

            // Adjust scroll so the time under the cursor stays in place
            const newCursorPx = cursorTimeMs * KF_PX_PER_MS + KF_LABEL_OFFSET;
            wrapper.scrollLeft = newCursorPx - (e.clientX - rect.left);
        }, { passive: false });
    }
}

function kfAddKeyframe() {
    let base, shoulder, elbow, grip;

    if (controlMode === 'cartesian') {
        // Compute joint angles from current Cartesian slider position via IK
        const x = parseFloat(document.getElementById("slider-x").value);
        const y = parseFloat(document.getElementById("slider-y").value);
        const z = parseFloat(document.getElementById("slider-z").value);
        const result = ik(x, y, z);
        if (!result) {
            addConsoleLine("Cannot add keyframe: current Cartesian position is unreachable", "error");
            return;
        }
        base     = result.base;
        shoulder = result.shoulder;
        elbow    = result.elbow;
        grip     = parseFloat(document.getElementById("slider-grip").value);
    } else {
        base     = parseFloat(document.getElementById("slider-base").value);
        shoulder = parseFloat(document.getElementById("slider-shoulder").value);
        elbow    = parseFloat(document.getElementById("slider-elbow").value);
        grip     = parseFloat(document.getElementById("slider-grip-joint").value);
    }

    const kf = {
        base: base,
        shoulder: shoulder,
        elbow: elbow,
        grip: grip,
        durationMs: KF_DEFAULT_DURATION,
    };
    keyframes.push(kf);
    kfRender();
    addConsoleLine(`Keyframe ${keyframes.length} added: B=${kf.base.toFixed(1)} S=${kf.shoulder.toFixed(1)} E=${kf.elbow.toFixed(1)} G=${kf.grip.toFixed(0)} (${kf.durationMs}ms)`, "system");
}

function kfRemoveKeyframe(index) {
    if (kfPlaying) return;
    keyframes.splice(index, 1);
    kfRender();
}

function kfGetTotalDuration() {
    return keyframes.reduce((sum, kf) => sum + kf.durationMs, 0);
}

function kfRender() {
    const totalMs = kfGetTotalDuration();
    const totalEl = document.getElementById("kf-total-time");
    totalEl.textContent = `Total: ${(totalMs / 1000).toFixed(1)}s`;

    const emptyEl = document.getElementById("kf-empty");
    const wrapperEl = document.getElementById("kf-timeline-wrapper");

    if (keyframes.length === 0) {
        emptyEl.style.display = "";
        wrapperEl.style.display = "none";
        return;
    }

    emptyEl.style.display = "none";
    wrapperEl.style.display = "";

    // Show playhead at current position
    const playhead = document.getElementById("kf-playhead");
    if (!kfPlaying) {
        playhead.style.left = (KF_LABEL_OFFSET + kfPlayheadTimeMs * KF_PX_PER_MS) + "px";
    }

    // Set container width
    const totalPx = totalMs * KF_PX_PER_MS;
    const containerEl = document.getElementById("kf-timeline-container");
    containerEl.style.width = (KF_LABEL_OFFSET + Math.max(totalPx, 200) + 20) + "px";

    // Render ruler
    kfRenderRuler(totalMs);

    // Render bars in each lane
    const joints = ["base", "shoulder", "elbow", "grip"];
    const jointKeys = ["base", "shoulder", "elbow", "grip"];

    joints.forEach((joint, ji) => {
        const lane = document.getElementById(`kf-lane-${joint}`);
        lane.innerHTML = "";

        let offsetMs = 0;
        keyframes.forEach((kf, ki) => {
            const bar = document.createElement("div");
            bar.className = "kf-bar";
            bar.dataset.joint = joint;
            bar.dataset.index = ki;
            bar.style.left = (offsetMs * KF_PX_PER_MS) + "px";
            bar.style.width = (kf.durationMs * KF_PX_PER_MS) + "px";

            const angle = kf[jointKeys[ji]];
            bar.innerHTML = `<span class="kf-bar-text">${angle.toFixed(0)}°</span>`;

            // Only add controls to the first track lane (base) to avoid clutter
            if (ji === 0) {
                // Delete button
                const del = document.createElement("button");
                del.className = "kf-bar-delete";
                del.textContent = "✕";
                del.addEventListener("click", (e) => {
                    e.stopPropagation();
                    kfRemoveKeyframe(ki);
                });
                bar.appendChild(del);
            }

            // Right resize handle (on all tracks)
            const handleR = document.createElement("div");
            handleR.className = "kf-bar-handle right";
            handleR.addEventListener("mousedown", (e) => {
                e.stopPropagation();
                kfStartResize(e, ki, "right");
            });
            bar.appendChild(handleR);

            // Click to edit (on all tracks for individual joint angle)
            bar.addEventListener("dblclick", (e) => {
                e.stopPropagation();
                kfStartEdit(bar, ki, joint);
            });

            // Drag to reorder (only on base track)
            if (ji === 0) {
                bar.draggable = true;
                bar.addEventListener("dragstart", (e) => {
                    if (kfPlaying) { e.preventDefault(); return; }
                    e.dataTransfer.setData("text/plain", ki.toString());
                    e.dataTransfer.effectAllowed = "move";
                    bar.classList.add("dragging");
                });
                bar.addEventListener("dragend", () => {
                    bar.classList.remove("dragging");
                    document.querySelectorAll(".kf-bar").forEach(b => {
                        b.classList.remove("drag-over-left", "drag-over-right");
                    });
                });
            }

            // Drop targets (all base bars)
            if (ji === 0) {
                bar.addEventListener("dragover", (e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                    const rect = bar.getBoundingClientRect();
                    const midX = rect.left + rect.width / 2;
                    bar.classList.toggle("drag-over-left", e.clientX < midX);
                    bar.classList.toggle("drag-over-right", e.clientX >= midX);
                });
                bar.addEventListener("dragleave", () => {
                    bar.classList.remove("drag-over-left", "drag-over-right");
                });
                bar.addEventListener("drop", (e) => {
                    e.preventDefault();
                    const fromIdx = parseInt(e.dataTransfer.getData("text/plain"));
                    const rect = bar.getBoundingClientRect();
                    const midX = rect.left + rect.width / 2;
                    let toIdx = e.clientX < midX ? ki : ki + 1;

                    if (fromIdx !== toIdx && fromIdx + 1 !== toIdx) {
                        const [moved] = keyframes.splice(fromIdx, 1);
                        if (toIdx > fromIdx) toIdx--;
                        keyframes.splice(toIdx, 0, moved);
                        kfRender();
                    }
                    document.querySelectorAll(".kf-bar").forEach(b => {
                        b.classList.remove("drag-over-left", "drag-over-right");
                    });
                });
            }

            lane.appendChild(bar);
            offsetMs += kf.durationMs;
        });

        // Click on lane to seek (only when not playing)
        lane.addEventListener("click", (e) => {
            if (kfPlaying) return;
            // Only handle clicks on the lane itself, not on bars
            if (e.target !== lane) return;
            kfTimelineClick(e, lane);
        });
    });
}

function kfRenderRuler(totalMs) {
    const ruler = document.getElementById("kf-ruler");
    ruler.innerHTML = "";

    // Adapt tick density to zoom level
    let step, majorStep;
    if (KF_PX_PER_MS >= 0.5) {
        step = 100;       // minor tick every 100ms
        majorStep = 500;  // major tick every 0.5s
    } else if (KF_PX_PER_MS >= 0.15) {
        step = 250;       // minor tick every 250ms
        majorStep = 1000; // major tick every 1s
    } else if (KF_PX_PER_MS >= 0.08) {
        step = 500;       // minor tick every 500ms
        majorStep = 2000; // major tick every 2s
    } else {
        step = 2000;      // minor tick every 2s
        majorStep = 5000; // major tick every 5s
    }

    for (let ms = 0; ms <= totalMs + step; ms += step) {
        const tick = document.createElement("div");
        tick.className = "kf-ruler-tick";
        tick.style.left = (ms * KF_PX_PER_MS) + "px";

        const isMajor = ms % majorStep === 0;
        const line = document.createElement("div");
        line.className = "kf-ruler-tick-line " + (isMajor ? "major" : "minor");
        tick.appendChild(line);

        if (isMajor) {
            const label = document.createElement("div");
            label.className = "kf-ruler-label";
            const secs = ms / 1000;
            label.textContent = secs >= 10 ? secs.toFixed(0) + "s" : secs.toFixed(1) + "s";
            tick.appendChild(label);
        }

        ruler.appendChild(tick);
    }

    // Click on ruler to seek
    ruler.addEventListener("click", (e) => {
        if (kfPlaying) return;
        const rect = ruler.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickMs = clickX / KF_PX_PER_MS;
        kfSeekToTime(clickMs);
    });
}

// --- Resize ---
function kfStartResize(e, index, edge) {
    if (kfPlaying) return;
    e.preventDefault();

    const startX = e.clientX;
    const startDuration = keyframes[index].durationMs;

    const onMove = (me) => {
        const dx = me.clientX - startX;
        const dMs = dx / KF_PX_PER_MS;

        if (edge === "right") {
            keyframes[index].durationMs = Math.max(KF_MIN_DURATION, Math.round(startDuration + dMs));
        }
        kfRender();
    };

    const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
}

// --- Inline Edit ---
function kfStartEdit(barEl, kfIndex, joint) {
    if (kfPlaying) return;

    const kf = keyframes[kfIndex];
    const currentValue = kf[joint];

    const input = document.createElement("input");
    input.type = "number";
    input.className = "kf-bar-input";
    input.value = currentValue.toFixed(1);
    input.step = "0.5";

    barEl.querySelector(".kf-bar-text").style.display = "none";
    barEl.appendChild(input);
    input.focus();
    input.select();

    let finished = false;
    const finish = (save) => {
        if (finished) return;
        finished = true;
        if (save) {
            const val = parseFloat(input.value);
            if (!isNaN(val)) {
                kf[joint] = val;
            }
        }
        kfRender();
    };

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); finish(true); }
        else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
}

/**
 * Update all sliders (joint + cartesian) to reflect a given pose.
 * Called when the sequencer seeks or plays through keyframes so the
 * slider UI stays in sync with the robot's target position.
 */
function kfUpdateSlidersFromPose(base, shoulder, elbow, grip) {
    // Update joint sliders
    document.getElementById("slider-base").value = base.toFixed(1);
    document.getElementById("slider-shoulder").value = shoulder.toFixed(1);
    document.getElementById("slider-elbow").value = elbow.toFixed(1);
    document.getElementById("slider-grip-joint").value = grip.toFixed(0);

    // Compute cartesian position via FK and update cartesian sliders
    const pos = fk(base, shoulder, elbow);
    const sliderX = document.getElementById("slider-x");
    const sliderY = document.getElementById("slider-y");
    const sliderZ = document.getElementById("slider-z");
    sliderX.value = Math.max(sliderX.min, Math.min(sliderX.max, pos.x.toFixed(1)));
    sliderY.value = Math.max(sliderY.min, Math.min(sliderY.max, pos.y.toFixed(1)));
    sliderZ.value = Math.max(sliderZ.min, Math.min(sliderZ.max, pos.z.toFixed(1)));
    document.getElementById("slider-grip").value = grip.toFixed(0);

    // Refresh displayed numeric values
    updateSliderValues();
}

// --- Timeline Click to Seek ---
function kfTimelineClick(e, laneEl) {
    const rect = laneEl.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickMs = clickX / KF_PX_PER_MS;
    kfSeekToTime(clickMs);
}

function kfSeekToTime(timeMs) {
    if (keyframes.length === 0) return;

    // Clamp to total duration
    const totalMs = kfGetTotalDuration();
    timeMs = Math.max(0, Math.min(timeMs, totalMs));

    // Find which keyframe this time falls within
    let cumMs = 0;
    let targetKfIndex = 0;
    for (let i = 0; i < keyframes.length; i++) {
        cumMs += keyframes[i].durationMs;
        if (timeMs <= cumMs) {
            targetKfIndex = i;
            break;
        }
        // If we've gone past all keyframes, use the last one
        if (i === keyframes.length - 1) targetKfIndex = i;
    }

    // Update playhead position
    kfPlayheadTimeMs = timeMs;
    const playhead = document.getElementById("kf-playhead");
    playhead.style.left = (KF_LABEL_OFFSET + timeMs * KF_PX_PER_MS) + "px";

    // Send the robot to the target keyframe's pose
    const kf = keyframes[targetKfIndex];
    const cmd = `timed_set ${kf.base.toFixed(1)} ${kf.shoulder.toFixed(1)} ${kf.elbow.toFixed(1)} ${kf.grip.toFixed(1)} 500`;
    sendCommand(cmd);

    // Refresh sliders to reflect the target pose
    kfUpdateSlidersFromPose(kf.base, kf.shoulder, kf.elbow, kf.grip);

    addConsoleLine(`Seek → Keyframe ${targetKfIndex + 1} (${(timeMs / 1000).toFixed(2)}s)`, "system");
}

// --- Play / Pause ---
function kfTogglePlay() {
    if (kfPlaying) {
        kfPause();
    } else {
        kfPlay();
    }
}

/**
 * Start (or resume) playback from the current playhead position.
 * Only the keyframes after the cursor are scheduled.
 */
function kfPlay() {
    if (keyframes.length === 0) {
        addConsoleLine("No keyframes to play", "warning");
        return;
    }

    kfPlaying = true;
    kfPlayStartOffsetMs = kfPlayheadTimeMs;  // remember where we're starting from
    kfPlayStartMs = performance.now();

    const btn = document.getElementById("kf-play-btn");
    btn.classList.add("playing");
    document.getElementById("kf-play-icon").textContent = "⏸";
    document.getElementById("kf-play-label").textContent = "Pause";

    const playhead = document.getElementById("kf-playhead");
    playhead.classList.add("playing");

    // Figure out the speed-adjusted offset: what real-time delay corresponds
    // to the timeline offset so we can skip already-elapsed keyframes.
    const originalTotalMs = kfGetTotalDuration();
    const totalPlayMs = kfGetSpeedAdjustedTotal();
    const ratio = totalPlayMs / (originalTotalMs || 1);
    const startOffsetRealMs = kfPlayStartOffsetMs * ratio;

    // Schedule keyframes that haven't been passed yet
    let cumOrigMs = 0;  // cumulative original-timeline time
    kfPlayTimers = [];

    keyframes.forEach((kf, i) => {
        const actualDuration = Math.max(KF_MIN_DURATION, Math.round(kf.durationMs / kfSpeedMultiplier));
        const kfOrigStartMs = cumOrigMs;
        cumOrigMs += kf.durationMs;

        // Skip keyframes whose start is before the cursor
        if (cumOrigMs <= kfPlayStartOffsetMs) return;

        // Real-time delay from now for this keyframe
        const kfRealStart = kfOrigStartMs * ratio;
        const delayFromNow = Math.max(0, kfRealStart - startOffsetRealMs);

        const timer = setTimeout(() => {
            if (!kfPlaying) return;
            kfCurrentIndex = i;
            const cmd = `timed_set ${kf.base.toFixed(1)} ${kf.shoulder.toFixed(1)} ${kf.elbow.toFixed(1)} ${kf.grip.toFixed(1)} ${actualDuration}`;
            sendCommand(cmd);
            // Refresh sliders to follow playback
            kfUpdateSlidersFromPose(kf.base, kf.shoulder, kf.elbow, kf.grip);
        }, delayFromNow);
        kfPlayTimers.push(timer);
    });

    // Remaining real-time duration from cursor to end
    const remainingRealMs = totalPlayMs - startOffsetRealMs;

    // Auto-end after remaining keyframes complete
    const endTimer = setTimeout(() => {
        if (!kfPlaying) return;
        if (kfLooping) {
            // Loop: rewind and restart
            kfPlayheadTimeMs = 0;
            kfPlayTimers.forEach(t => clearTimeout(t));
            kfPlayTimers = [];
            kfPlay();
        } else {
            kfPause();
            // Move playhead to end
            kfPlayheadTimeMs = originalTotalMs;
            const ph = document.getElementById("kf-playhead");
            ph.style.left = (KF_LABEL_OFFSET + originalTotalMs * KF_PX_PER_MS) + "px";
        }
    }, remainingRealMs + 100);
    kfPlayTimers.push(endTimer);

    // Animate playhead
    kfAnimatePlayhead();
}

/** Pause playback — leaves the playhead where it is. */
function kfPause() {
    kfPlaying = false;
    kfCurrentIndex = -1;

    kfPlayTimers.forEach(t => clearTimeout(t));
    kfPlayTimers = [];

    if (kfPlayRAF) {
        cancelAnimationFrame(kfPlayRAF);
        kfPlayRAF = null;
    }

    const btn = document.getElementById("kf-play-btn");
    btn.classList.remove("playing");
    document.getElementById("kf-play-icon").textContent = "▶";
    document.getElementById("kf-play-label").textContent = "Play";

    const playhead = document.getElementById("kf-playhead");
    playhead.classList.remove("playing");
    // kfPlayheadTimeMs is already up-to-date from the animation loop

    sendCommand("stop");
}

/** Rewind the cursor to the start of the sequence. */
function kfRewind() {
    if (kfPlaying) kfPause();
    kfPlayheadTimeMs = 0;
    const playhead = document.getElementById("kf-playhead");
    playhead.style.left = KF_LABEL_OFFSET + "px";
}

/** Toggle loop mode on/off. */
function kfToggleLoop() {
    kfLooping = !kfLooping;
    const btn = document.getElementById("kf-loop-btn");
    btn.classList.toggle("active", kfLooping);
}

/** Compute total speed-adjusted playback duration in real ms. */
function kfGetSpeedAdjustedTotal() {
    return keyframes.reduce((sum, kf) =>
        sum + Math.max(KF_MIN_DURATION, Math.round(kf.durationMs / kfSpeedMultiplier)), 0);
}

function kfAnimatePlayhead() {
    if (!kfPlaying) return;

    const elapsed = performance.now() - kfPlayStartMs;
    const originalTotalMs = kfGetTotalDuration();
    const totalPlayMs = kfGetSpeedAdjustedTotal();
    const ratio = originalTotalMs / (totalPlayMs || 1);

    // Map elapsed real time → original timeline time, offset by where we started
    const timelineMs = Math.min(kfPlayStartOffsetMs + elapsed * ratio, originalTotalMs);
    kfPlayheadTimeMs = timelineMs;

    const px = KF_LABEL_OFFSET + (timelineMs * KF_PX_PER_MS);
    const playhead = document.getElementById("kf-playhead");
    playhead.style.left = px + "px";

    // Auto-scroll the timeline to keep playhead visible
    const wrapper = document.getElementById("kf-timeline-wrapper");
    const scrollRight = wrapper.scrollLeft + wrapper.clientWidth;
    if (px > scrollRight - 40) {
        wrapper.scrollLeft = px - wrapper.clientWidth + 60;
    }

    if (timelineMs < originalTotalMs) {
        kfPlayRAF = requestAnimationFrame(kfAnimatePlayhead);
    }
}

// --- Download JSON ---
function kfDownloadJSON() {
    if (keyframes.length === 0) {
        addConsoleLine("No keyframes to export", "warning");
        return;
    }

    const data = {
        name: "Mira Keyframe Sequence",
        created: new Date().toISOString(),
        totalDurationMs: kfGetTotalDuration(),
        keyframes: keyframes.map(kf => ({
            base: parseFloat(kf.base.toFixed(1)),
            shoulder: parseFloat(kf.shoulder.toFixed(1)),
            elbow: parseFloat(kf.elbow.toFixed(1)),
            grip: parseFloat(kf.grip.toFixed(1)),
            durationMs: kf.durationMs,
        })),
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-").substring(0, 19);
    a.href = url;
    a.download = `mira_keyframes_${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);

    addConsoleLine(`Exported ${keyframes.length} keyframes as JSON`, "system");
}

// --- Load JSON ---
function kfTriggerLoad() {
    const input = document.getElementById('kf-file-input');
    input.value = '';  // reset so re-selecting the same file triggers change
    input.click();
}

function kfLoadJSON(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);

            // Validate structure
            if (!data.keyframes || !Array.isArray(data.keyframes) || data.keyframes.length === 0) {
                addConsoleLine("Invalid file: no keyframes array found", "error");
                return;
            }

            // Validate each keyframe has required fields
            for (let i = 0; i < data.keyframes.length; i++) {
                const kf = data.keyframes[i];
                if (typeof kf.base !== 'number' || typeof kf.shoulder !== 'number' ||
                    typeof kf.elbow !== 'number' || typeof kf.grip !== 'number' ||
                    typeof kf.durationMs !== 'number') {
                    addConsoleLine(`Invalid keyframe at index ${i}: missing or invalid fields`, "error");
                    return;
                }
            }

            // Stop playback if active
            if (kfPlaying) {
                kfPause();
            }

            // Load the keyframes
            keyframes = data.keyframes.map(kf => ({
                base: kf.base,
                shoulder: kf.shoulder,
                elbow: kf.elbow,
                grip: kf.grip,
                durationMs: kf.durationMs,
            }));

            // Reset playhead
            kfPlayheadTimeMs = 0;

            // Re-render
            kfRender();

            const name = data.name || file.name;
            addConsoleLine(`Loaded ${keyframes.length} keyframes from "${name}"`, "system");
        } catch (err) {
            addConsoleLine(`Failed to parse JSON: ${err.message}`, "error");
        }
    };
    reader.readAsText(file);
}
// ---------------------------------------------------------------------------
// Console Resize
// ---------------------------------------------------------------------------

function initConsoleResize() {
    const handle = document.getElementById("console-resize-handle");
    const consolePanel = document.getElementById("console-panel");
    if (!handle || !consolePanel) return;

    let startY, startHeight;

    handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        startY = e.clientY;
        startHeight = consolePanel.getBoundingClientRect().height;

        const onMove = (me) => {
            const dy = startY - me.clientY; // dragging up increases height
            let newHeight = startHeight + dy;
            const maxHeight = window.innerHeight * 0.5;
            newHeight = Math.max(80, Math.min(maxHeight, newHeight));
            consolePanel.style.height = newHeight + "px";
        };

        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
        };

        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

// ---------------------------------------------------------------------------
// Console Toggle (collapse / expand)
// ---------------------------------------------------------------------------

function toggleConsole() {
    const panel = document.getElementById("console-panel");
    const btn = document.getElementById("console-toggle-btn");
    if (!panel || !btn) return;

    const isCollapsed = panel.classList.toggle("collapsed");
    if (isCollapsed) {
        btn.textContent = "▲ Show";
        panel.style.height = ""; // reset inline height so CSS var takes over
    } else {
        btn.textContent = "▼ Hide";
        panel.style.height = ""; // reset so CSS expanded height applies
    }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
    initSocket();
    initSliderTicks();
    initSliders();
    initGestures();
    updateSliderValues();
    kfRender();
    initKfZoom();
    initConsoleResize();
    initSectionBackground();
});

// ---------------------------------------------------------------------------
// Section-aware Background
// ---------------------------------------------------------------------------

const BG_CLASSES = ['bg-arm', 'bg-dance', 'bg-animation'];

function setSectionBackground(cls) {
    BG_CLASSES.forEach(c => document.body.classList.remove(c));
    if (cls) document.body.classList.add(cls);
}

function initSectionBackground() {
    const cards = document.querySelectorAll('#control-panel > .card');
    // Card order: 0 = Move the Arm, 1 = Dance Moves, 2 = Animation Maker
    const mapping = ['bg-arm', 'bg-dance', 'bg-animation'];

    cards.forEach((card, i) => {
        const cls = mapping[i];
        if (!cls) return;
        card.addEventListener('pointerenter', () => setSectionBackground(cls));
        card.addEventListener('click', () => setSectionBackground(cls));
    });
}

// Close modal on overlay click
document.getElementById("settings-modal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) {
        closeSettings();
    }
});

// Keyboard shortcut: Escape to close modal/menus
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeAllMenus();
        closeSettings();
    }
});

// Click outside to close context menus
document.addEventListener("click", (e) => {
    if (!e.target.closest(".robot-menu-btn") && !e.target.closest(".robot-context-menu")) {
        closeAllMenus();
    }
});

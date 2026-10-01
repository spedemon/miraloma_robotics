/**
 * Mira Swarm Controller — Client-Side Application
 *
 * Manages WebSocket connection to the Flask server, handles robot
 * selection, slider control, gesture toggling, and console logging.
 */

// ---------------------------------------------------------------------------
// Arm Geometry & IK/FK (mirrored from robotarm_mcu/include/config.h)
// ---------------------------------------------------------------------------

const ARM_BASE_HEIGHT = 22.0;   // d0: base pivot to shoulder pivot (mm)
const ARM_LINK1_LENGTH = 40.0;   // L1: shoulder pivot to elbow pivot (mm)
const ARM_LINK2_LENGTH = 86.0;   // L2: elbow pivot to end effector (mm)

// Servo ↔ geometric angle mapping (from config.h)
const SERVO_BASE_OFFSET = 0.0;
const SERVO_BASE_DIRECTION = 1.0;
const SERVO_SHOULDER_OFFSET = 90.0;
const SERVO_SHOULDER_DIRECTION = -1.0;
const SERVO_ELBOW_OFFSET = 0.0;
const SERVO_ELBOW_DIRECTION = -1.0;

// Joint limits (servo degrees, from config.h)
const JOINT_BASE_MIN = -90;
const JOINT_BASE_MAX = 90;
const JOINT_SHOULDER_MIN = -109;
const JOINT_SHOULDER_MAX = 104;
const JOINT_ELBOW_MIN = -100;
const JOINT_ELBOW_MAX = 100;
const GRIP_OPEN_ANGLE = -30;
const GRIP_CLOSED_ANGLE = 45;

const DEG2RAD = Math.PI / 180.0;
const RAD2DEG = 180.0 / Math.PI;

function iconSvg(name, className = "ui-icon") {
    return `<svg class="${className}" aria-hidden="true"><use href="/static/icons.svg#${name}"></use></svg>`;
}

function setSvgIcon(element, name) {
    element.innerHTML = `<use href="/static/icons.svg#${name}"></use>`;
}

/**
 * Forward Kinematics: servo angles (degrees) → Cartesian position (mm).
 * Mirrors ArmController::forwardKinematics() from ArmController.cpp.
 */
function fk(baseServoDeg, shoulderServoDeg, elbowServoDeg) {
    const L1 = ARM_LINK1_LENGTH;
    const L2 = ARM_LINK2_LENGTH;
    const d0 = ARM_BASE_HEIGHT;

    // Servo → geometric angles (radians)
    const baseGeo = ((baseServoDeg - SERVO_BASE_OFFSET) / SERVO_BASE_DIRECTION) * DEG2RAD;
    const shoulderGeo = ((shoulderServoDeg - SERVO_SHOULDER_OFFSET) / SERVO_SHOULDER_DIRECTION) * DEG2RAD;
    const elbowGeo = ((elbowServoDeg - SERVO_ELBOW_OFFSET) / SERVO_ELBOW_DIRECTION) * DEG2RAD;

    // End-effector in the vertical plane
    const r = L1 * Math.cos(shoulderGeo) + L2 * Math.cos(shoulderGeo + elbowGeo);
    const zEff = L1 * Math.sin(shoulderGeo) + L2 * Math.sin(shoulderGeo + elbowGeo);

    return {
        x: r * Math.cos(baseGeo),
        y: r * Math.sin(baseGeo),
        z: zEff + d0,
    };
}

function stepXYZRobotJoint(current, target, velocity, dt) {
    const error = target - current;
    const absError = Math.abs(error);
    let desiredSpeed = Math.min(
        XYZ_MOTION_MAX_SPEED,
        Math.sqrt(2 * XYZ_MOTION_ACCEL * absError),
    );
    let desiredVelocity = error < 0 ? -desiredSpeed : desiredSpeed;
    if (absError <= XYZ_MOTION_POSITION_EPSILON) desiredVelocity = 0;

    const maxVelocityChange = XYZ_MOTION_ACCEL * dt;
    const velocityChange = Math.max(
        -maxVelocityChange,
        Math.min(maxVelocityChange, desiredVelocity - velocity),
    );
    const nextVelocity = velocity + velocityChange;
    const step = nextVelocity * dt;
    if (absError <= XYZ_MOTION_POSITION_EPSILON
        && Math.abs(nextVelocity) <= XYZ_MOTION_VELOCITY_EPSILON) {
        return { position: target, velocity: 0, settled: true };
    }
    const position = current + step;
    return {
        position,
        velocity: nextVelocity,
        settled: Math.abs(target - position) <= XYZ_MOTION_POSITION_EPSILON
            && Math.abs(nextVelocity) <= XYZ_MOTION_VELOCITY_EPSILON,
    };
}

function updateXYZRobotModel(nowMs) {
    if (xyzRobotMotionLastMs === null) xyzRobotMotionLastMs = nowMs;
    let remainingTime = Math.min(0.05, Math.max(0.001, (nowMs - xyzRobotMotionLastMs) / 1000));
    xyzRobotMotionLastMs = nowMs;
    let settled = false;

    // Match the firmware's 5 ms control cadence even though browsers usually
    // render at ~16 ms. Substeps keep the estimated pose and arrival time close
    // to the physical follower instead of making them frame-rate dependent.
    while (remainingTime > 0) {
        const dt = Math.min(0.005, remainingTime);
        remainingTime -= dt;
        settled = true;
        ["base", "shoulder", "elbow"].forEach((joint) => {
            const next = stepXYZRobotJoint(
                xyzRobotJoints[joint],
                xyzRobotTargetJoints[joint],
                xyzRobotJointVelocities[joint],
                dt,
            );
            xyzRobotJoints[joint] = next.position;
            xyzRobotJointVelocities[joint] = next.velocity;
            settled = settled && next.settled;
        });
    }

    lastValidCartesianTarget = fk(
        xyzRobotJoints.base,
        xyzRobotJoints.shoulder,
        xyzRobotJoints.elbow,
    );
    scheduleXYZWorkspaceDraw();

    if (settled) {
        xyzRobotMotionFrame = null;
        xyzRobotMotionLastMs = null;
    } else {
        xyzRobotMotionFrame = requestAnimationFrame(updateXYZRobotModel);
    }
}

function setXYZRobotTarget(joints, instant = false) {
    xyzRobotTargetJoints = {
        base: joints.base,
        shoulder: joints.shoulder,
        elbow: joints.elbow,
    };
    if (instant) {
        xyzRobotJoints = { ...xyzRobotTargetJoints };
        xyzRobotJointVelocities = { base: 0, shoulder: 0, elbow: 0 };
        lastValidCartesianTarget = fk(
            xyzRobotJoints.base,
            xyzRobotJoints.shoulder,
            xyzRobotJoints.elbow,
        );
        scheduleXYZWorkspaceDraw();
        return;
    }
    if (xyzRobotMotionFrame === null) {
        xyzRobotMotionLastMs = null;
        xyzRobotMotionFrame = requestAnimationFrame(updateXYZRobotModel);
    }
}

/** Solve IK and retain a user-facing reason when the target is invalid. */
function solveCartesianTarget(x, y, z) {
    const L1 = ARM_LINK1_LENGTH;
    const L2 = ARM_LINK2_LENGTH;
    const d0 = ARM_BASE_HEIGHT;

    if (![x, y, z].every(Number.isFinite)) {
        return { valid: false, reason: "Enter a number for X, Y, and Z." };
    }
    if (x < -126 || x > 126 || y < -126 || y > 126 || z < 0 || z > 148) {
        return { valid: false, reason: "The target is outside the displayed XYZ workspace." };
    }

    // Treat signed zero as the centerline so typing "-0" cannot request a
    // spurious 180-degree base rotation.
    const safeX = Math.abs(x) < 0.0001 ? 0 : x;
    const safeY = Math.abs(y) < 0.0001 ? 0 : y;

    // Base angle (top-down view)
    const baseGeo = Math.atan2(safeY, safeX);

    // 2-link planar IK in the vertical plane
    const r = Math.sqrt(safeX * safeX + safeY * safeY);
    const zEff = z - d0;

    const distSq = r * r + zEff * zEff;
    const D = (distSq - L1 * L1 - L2 * L2) / (2.0 * L1 * L2);

    if (D > 1.0) {
        return { valid: false, reason: "The target is beyond the arm's maximum reach." };
    }
    if (D < -1.0) {
        return { valid: false, reason: "The target is too close to the shoulder for the arm to fold there." };
    }

    // Elbow angle (elbow-down solution)
    const elbowGeo = Math.atan2(-Math.sqrt(1.0 - D * D), D);

    // Shoulder angle
    const shoulderGeo = Math.atan2(zEff, r)
        - Math.atan2(L2 * Math.sin(elbowGeo), L1 + L2 * Math.cos(elbowGeo));

    // Geometric → servo angles
    const baseAngle = SERVO_BASE_OFFSET + SERVO_BASE_DIRECTION * (baseGeo * RAD2DEG);
    const shoulderAngle = SERVO_SHOULDER_OFFSET + SERVO_SHOULDER_DIRECTION * (shoulderGeo * RAD2DEG);
    const elbowAngle = SERVO_ELBOW_OFFSET + SERVO_ELBOW_DIRECTION * (elbowGeo * RAD2DEG);

    // Check joint limits
    if (baseAngle < JOINT_BASE_MIN || baseAngle > JOINT_BASE_MAX) {
        return { valid: false, reason: "The base cannot rotate far enough to face that target." };
    }
    if (shoulderAngle < JOINT_SHOULDER_MIN || shoulderAngle > JOINT_SHOULDER_MAX) {
        return { valid: false, reason: "That target would move the shoulder beyond its safe limit." };
    }
    if (elbowAngle < JOINT_ELBOW_MIN || elbowAngle > JOINT_ELBOW_MAX) {
        return { valid: false, reason: "That target would move the elbow beyond its safe limit." };
    }

    return {
        valid: true,
        joints: { base: baseAngle, shoulder: shoulderAngle, elbow: elbowAngle },
        reason: "",
    };
}

/**
 * Inverse Kinematics: Cartesian position (mm) → servo angles (degrees).
 * Mirrors ArmController::solve() from ArmController.cpp.
 */
function ik(x, y, z) {
    const solution = solveCartesianTarget(x, y, z);
    return solution.valid ? solution.joints : null;
}

// ---------------------------------------------------------------------------
// Gesture definitions
// ---------------------------------------------------------------------------

const GESTURES = [
    { id: "dance", label: "Dance", icon: "dance", continuous: true },
    { id: "break", label: "Break", icon: "dance", continuous: true },
    { id: "crab", label: "Crab", icon: "crab", continuous: true },
    { id: "circle", label: "Side Circle", icon: "circle", continuous: true },
    { id: "square", label: "Side Square", icon: "square", continuous: true },
    { id: "triangle", label: "Side Triangle", icon: "triangle", continuous: true },
    { id: "fcircle", label: "Front Circle", icon: "circle", continuous: true },
    { id: "fsquare", label: "Front Square", icon: "target", continuous: true },
    { id: "ftriangle", label: "Front Triangle", icon: "triangle", continuous: true },
    { id: "bow", label: "Bow", icon: "bow", continuous: false },
    { id: "wave", label: "Wave", icon: "wave", continuous: true },
];

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let socket = null;
let robots = [];
let selectedTarget = null;  // null = all robots, or { name, mac, masterName }
let activeGesture = null;   // gesture id currently running
let serialConnected = false;
let connectedDevices = [];
let updateDevices = [];
let setupPromptedPorts = new Set();
let firmwarePrompted = new Set();
let deviceModalMode = null;
let eraseTarget = null;
let deviceOperationActive = false;
let openMenuMac = null;     // MAC of robot whose context menu is open
let deviceType = 'master';  // 'master' or 'robot' — set by server
let renamingMac = null;     // MAC of robot currently being renamed (blocks re-render)
let pendingRender = false;  // true if a render was skipped during rename
let calibrationOpen = false; // true when calibration panel is visible
let calibrationOpening = false; // true while the robot is returning Home
let calibrationOpenTimer = null;
let calibrationLoadPending = false; // true while waiting for cal_get
let calibrationLoadTimer = null;
let calibrationAtHome = true; // false while a claw test/preview is away from Home
let calibrationGripTestPosition = "closed";
let loadedCalibration = { base: 0, shoulder: 0, elbow: 0, grip: 0 };
let customGestures = [];     // Array of custom gesture names from robot

// Control mode
let controlMode = 'joint';  // 'cartesian' or 'joint'
let lastValidCartesianTarget = fk(0, 0, 0);
let xyzWorkspaceInitialized = false;
let xyzWorkspaceDrawPending = false;
let xyzReachableVolumePoints = null;
const XYZ_DEFAULT_VOLUME_ZOOM = 1.45;
const XYZ_DEFAULT_VOLUME_YAW = -Math.PI / 4;
const XYZ_DEFAULT_VOLUME_ELEVATION = 0.30;
let xyzVolumeZoom = XYZ_DEFAULT_VOLUME_ZOOM;
let xyzVolumeYaw = XYZ_DEFAULT_VOLUME_YAW;
let xyzVolumeElevation = XYZ_DEFAULT_VOLUME_ELEVATION;
let xyzLastSendMs = 0;
let xyzPendingSendTimer = null;
let xyzLastSentTargetKey = null;
let xyzDragFilteredTarget = null;
let xyzPositionNotice = "";
const XYZ_LIVE_SEND_MS = 50;
const XYZ_DRAG_FILTER_ALPHA = 0.42;
const XYZ_MOTION_MAX_SPEED = 120.0;
const XYZ_MOTION_ACCEL = 300.0;
const XYZ_MOTION_POSITION_EPSILON = 0.10;
const XYZ_MOTION_VELOCITY_EPSILON = 0.01;
let xyzRobotJoints = { base: 0, shoulder: 0, elbow: 0 };
let xyzRobotTargetJoints = { base: 0, shoulder: 0, elbow: 0 };
let xyzRobotJointVelocities = { base: 0, shoulder: 0, elbow: 0 };
let xyzRobotMotionFrame = null;
let xyzRobotMotionLastMs = null;

// Slider throttle
let sliderThrottleTimer = null;
let gripThrottleTimer = null;
const SLIDER_THROTTLE_MS = 100;

// Slider idle → sleep: power off servos after inactivity
let sliderIdleTimer = null;
const SLIDER_IDLE_MS = 2500;  // 2 seconds of no slider activity → sleep

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

    socket.on("device_inventory", (data) => {
        connectedDevices = data.devices || [];
        serialConnected = connectedDevices.some((device) => device.state === "connected");
        deviceType = connectedDevices.some((device) => device.role === "robot") ? "robot" : "master";
        updateSerialUI({ connected: serialConnected });
        renderDevices();
        renderDeviceSettings();
        refreshUpdates(false);

        // A board which read-only inspection proves has no working Mira image
        // cannot identify its intended role. Bring that choice to the user.
        const presentPorts = new Set(connectedDevices.map((device) => device.port));
        if (!deviceOperationActive) {
            setupPromptedPorts = new Set([...setupPromptedPorts].filter((port) => presentPorts.has(port)));
        }
        const presentIds = new Set(connectedDevices.filter((device) => device.deviceId).map((device) => device.deviceId));
        firmwarePrompted = new Set(
            [...firmwarePrompted].filter((key) => presentIds.has(key.split("|")[0]))
        );
        const newBoard = connectedDevices.find(
            (device) => device.state === "unrecognized" && !setupPromptedPorts.has(device.port)
        );
        if (newBoard && !deviceOperationActive) {
            setupPromptedPorts.add(newBoard.port);
            openProvisioningModal();
        }
    });

    socket.on("update_status", (data) => {
        deviceOperationActive = ["preparing", "flashing", "erasing", "restarting"].includes(data.state);
        renderUpdateProgress(data);
        if (data.state === "complete" && data.operation === "erase"
            && connectedDevices.some((device) => device.state === "unrecognized")) {
            const newBoard = connectedDevices.find((device) => device.state === "unrecognized");
            setupPromptedPorts.delete(newBoard.port);
            openProvisioningModal();
        }
        if (data.state === "complete") refreshUpdates(false);
    });

    socket.on("robot_list", (data) => {
        robots = data;
        renderRobotList();
    });

    socket.on("console_line", (data) => {
        addConsoleLine(data.text, data.type, data.time);
    });

    socket.on("calibration_values", (data) => {
        if (!calibrationOpen || !calibrationLoadPending) return;

        const selectedNames = selectedTarget ? [
            selectedTarget.mac,
            selectedTarget.masterName,
            selectedTarget.name,
        ] : [];
        if (data.target && !selectedNames.includes(data.target)) return;

        loadedCalibration = {
            base: data.base,
            shoulder: data.shoulder,
            elbow: data.elbow,
            grip: data.grip,
        };
        Object.entries(loadedCalibration).forEach(([joint, value]) => {
            document.getElementById(`cal-${joint}`).value = value;
        });
        calibrationLoadPending = false;
        if (calibrationLoadTimer) clearTimeout(calibrationLoadTimer);
        calibrationLoadTimer = null;
        setCalibrationControlsLoading(false);
        updateCalValues();
    });

    socket.on("device_type", (data) => {
        deviceType = data.type;
        renderRobotList();  // re-render to show/hide rename option
        // Query custom gestures when in robot mode
        if (deviceType === "robot") {
            sendCommand("seq_list");
        }
    });

    socket.on("upload_result", (data) => {
        handleUploadResult(data);
    });

    socket.on("custom_gestures", (data) => {
        customGestures = data.names || [];
        renderCustomGestures();
    });

    socket.on("delete_result", (data) => {
        handleDeleteResult(data);
    });
}

// ---------------------------------------------------------------------------
// Serial UI
// ---------------------------------------------------------------------------

function updateSerialUI(data) {
    const badge = document.getElementById("serial-badge");
    const label = document.getElementById("serial-label");
    const banner = document.getElementById("disconnected-banner");
    const message = document.getElementById("disconnected-message");
    const newBoards = connectedDevices.filter((device) => device.state === "unrecognized");
    const checkingBoards = connectedDevices.filter((device) => ["probing", "inspecting"].includes(device.state));
    const failedBoards = connectedDevices.filter((device) => device.state === "inspection_failed");
    const repairBoards = connectedDevices.filter((device) => device.state === "repair");
    const nearbyBluetooth = connectedDevices.filter(
        (device) => device.transport === "ble" && device.state === "available"
    );

    badge.disabled = !data.connected && !newBoards.length && !nearbyBluetooth.length;
    badge.classList.toggle("attention", newBoards.length > 0 || failedBoards.length > 0);
    if (newBoards.length) {
        badge.classList.remove("connected");
        label.textContent = newBoards.length === 1 ? "New USB board found" : `${newBoards.length} new USB boards found`;
        message.textContent = "A new ESP32-C3 board is ready to program. Choose whether it will be a Robot or a Wireless board.";
        banner.style.display = "flex";
    } else if (data.connected) {
        badge.classList.add("connected");
        const count = connectedDevices.filter((device) => device.state === "connected").length;
        label.textContent = count === 1 ? "1 device connected" : `${count || 1} devices connected`;
        banner.style.display = "none";
    } else if (nearbyBluetooth.length) {
        badge.classList.remove("connected");
        label.textContent = nearbyBluetooth.length === 1
            ? "Bluetooth robot nearby"
            : `${nearbyBluetooth.length} Bluetooth robots nearby`;
        message.textContent = "A Mira robot is nearby. Open the connection menu to connect over Bluetooth.";
        banner.style.display = "flex";
    } else if (checkingBoards.length) {
        badge.classList.remove("connected");
        label.textContent = "Checking USB board…";
        message.textContent = checkingBoards.some((device) => device.state === "inspecting")
            ? "Mira is safely reading the board to identify the software already installed."
            : "Mira found a USB board and is asking it to identify itself.";
        banner.style.display = "flex";
    } else if (repairBoards.length) {
        badge.classList.remove("connected");
        label.textContent = `${roleLabel(repairBoards[0].role)} needs repair`;
        message.textContent = "Mira recognized the installed software, but it did not start correctly.";
        banner.style.display = "flex";
    } else if (failedBoards.length) {
        badge.classList.remove("connected");
        label.textContent = "USB board needs attention";
        message.textContent = failedBoards[0].detail || "Mira could not identify this USB board. Reconnect it and try again.";
        banner.style.display = "flex";
    } else {
        badge.classList.remove("connected");
        label.textContent = "Looking for robots…";
        message.textContent = window.MiraAndroid
            ? "Looking for robots over Bluetooth…"
            : "Looking for robots over Bluetooth and USB…";
        banner.style.display = "flex";
    }
}

// ---------------------------------------------------------------------------
// Automatic device modals
// ---------------------------------------------------------------------------

function openProvisioningModal() {
    deviceModalMode = "provisioning";
    const title = document.getElementById("devices-modal-title");
    const description = document.getElementById("devices-modal-description");
    const board = connectedDevices.find((device) => device.state === "unrecognized");
    title.textContent = board?.classification === "other_firmware"
        ? "Set up this ESP32-C3 board"
        : "Set up your new USB board";
    description.textContent = board?.classification === "other_firmware"
        ? "This ESP32-C3 contains software that is not from Mira. Choose what the board will become. Its existing software will be replaced."
        : board?.classification === "corrupt"
            ? "Mira found an ESP32-C3 whose software is incomplete or damaged. Choose what the board will become. Mira will install fresh firmware."
            : "Mira software was not found on this ESP32-C3. Choose what the board will become. Mira will install the correct firmware automatically.";
    document.getElementById("device-list").style.display = "grid";
    document.getElementById("update-progress").style.display = "none";
    document.getElementById("settings-modal").classList.add("visible");
    renderDevices();
}

function openUpdateProgress(role) {
    deviceModalMode = "progress";
    document.getElementById("devices-modal-title").textContent = `Updating ${roleLabel(role)}`;
    document.getElementById("devices-modal-description").textContent = "Mira is preparing the board and installing its firmware automatically.";
    document.getElementById("device-list").style.display = "none";
    document.getElementById("update-progress").style.display = "block";
    document.getElementById("update-message").textContent = "Preparing the update…";
    document.getElementById("update-progress-bar").style.width = "2%";
    document.getElementById("settings-modal").classList.add("visible");
}

function openEraseProgress(role) {
    deviceModalMode = "progress";
    document.getElementById("devices-modal-title").textContent = `Erasing ${roleLabel(role)}`;
    document.getElementById("devices-modal-description").textContent = "Keep the USB cable connected. Mira will offer new firmware choices when the board is ready.";
    document.getElementById("device-list").style.display = "none";
    document.getElementById("update-progress").style.display = "block";
    document.getElementById("update-message").textContent = "Preparing to erase the board…";
    document.getElementById("update-progress-bar").style.width = "2%";
    document.getElementById("settings-modal").classList.add("visible");
}

function closeSettings() {
    deviceModalMode = null;
    document.getElementById("settings-modal").classList.remove("visible");
}

function roleLabel(role) {
    return role === "wireless_controller" ? "Wireless board" : "Robot";
}

function openDeviceSettings() {
    if (connectedDevices.some((device) => device.state === "unrecognized")) {
        openProvisioningModal();
        return;
    }
    if (!connectedDevices.some((device) => device.state === "connected" || device.transport === "ble")) return;
    renderDeviceSettings();
    document.getElementById("device-settings-modal").classList.add("visible");
}

function closeDeviceSettings() {
    document.getElementById("device-settings-modal").classList.remove("visible");
}

function renderDeviceSettings() {
    const list = document.getElementById("device-settings-list");
    if (!list) return;
    const devices = connectedDevices.filter(
        (device) => device.state === "connected" || device.transport === "ble"
    );
    if (!devices.length) {
        list.innerHTML = '<div class="device-empty">No Mira devices are nearby.</div>';
        return;
    }
    list.innerHTML = devices.map((device) => {
        const associatedRobot = robots.find((robot) => robot.mac === device.deviceId);
        const deviceName = device.name || associatedRobot?.name;
        const isBluetooth = device.transport === "ble";
        const isConnected = device.state === "connected";
        const bluetoothAction = isBluetooth
            ? `<div class="device-erase-action">
                <div><strong>${isConnected ? "Bluetooth connected" : device.state === "connecting" ? "Connecting…" : "Bluetooth available"}</strong><br><span>${isConnected ? "Control this robot without a cable." : "Connect directly to this robot."}</span></div>
                <button class="btn ${isConnected ? "" : "btn-primary"}" ${device.state === "connecting" ? "disabled" : ""}
                    onclick="${isConnected ? "disconnectBluetoothDevice" : "connectBluetoothDevice"}('${escapeHtml(device.address || device.port.replace(/^ble:/, ""))}')">
                    ${isConnected ? "Disconnect" : device.state === "connecting" ? "Connecting…" : "Connect"}
                </button>
            </div>`
            : `<div class="device-erase-action">
                <div><strong>Erase this board</strong><br><span>Remove its firmware so it can be programmed for a different purpose.</span></div>
                <button class="btn btn-danger" onclick="confirmEraseDevice('${escapeHtml(device.deviceId)}')">Erase firmware…</button>
            </div>`;
        return `
        <div class="device-info-card">
            <div class="device-card-title">${escapeHtml(deviceName || device.name || roleLabel(device.role))}</div>
            <dl class="device-facts">
                <div><dt>Firmware type</dt><dd>${roleLabel(device.role)}</dd></div>
                <div><dt>Firmware version</dt><dd>${escapeHtml(device.firmware || "Unknown")}</dd></div>
                <div><dt>Connection</dt><dd>${isBluetooth ? "Bluetooth" : "USB"}</dd></div>
                ${device.deviceId ? `<div><dt>Robot ID</dt><dd class="device-id-value">${escapeHtml(device.deviceId)}</dd></div>` : ""}
                ${deviceName ? `<div><dt>Name</dt><dd>${escapeHtml(deviceName)}</dd></div>` : ""}
            </dl>
            ${bluetoothAction}
        </div>
    `;
    }).join("");
}

async function connectBluetoothDevice(address) {
    const res = await fetch("/api/ble/connect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address }),
    });
    const data = await res.json();
    if (!res.ok) addConsoleLine(data.error || "Bluetooth connection failed", "error");
}

async function disconnectBluetoothDevice(address) {
    await fetch("/api/ble/disconnect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address }),
    });
}

function confirmEraseDevice(deviceId) {
    const device = connectedDevices.find((item) => item.deviceId === deviceId);
    if (!device) return;
    eraseTarget = device;
    document.getElementById("erase-device-description").textContent = `You are about to erase this ${roleLabel(device.role).toLowerCase()} (${device.deviceId}).`;
    document.getElementById("erase-device-modal").classList.add("visible");
}

function closeEraseDeviceModal() {
    eraseTarget = null;
    document.getElementById("erase-device-modal").classList.remove("visible");
}

async function eraseSelectedDevice() {
    if (!eraseTarget) return;
    const target = eraseTarget;
    closeEraseDeviceModal();
    closeDeviceSettings();
    deviceOperationActive = true;
    openEraseProgress(target.role);
    const res = await fetch("/api/devices/erase", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deviceId: target.deviceId }),
    });
    const data = await res.json();
    if (!res.ok) {
        deviceOperationActive = false;
        renderUpdateProgress({ state: "failed", progress: 0, message: data.error || "The board could not be erased." });
        addConsoleLine(data.error || "The board could not be erased", "error");
    }
}

function renderDevices() {
    const list = document.getElementById("device-list");
    if (!list) return;
    const devices = connectedDevices.filter((device) => device.state === "unrecognized");
    if (!devices.length) {
        list.innerHTML = '<div class="device-empty">The new board is no longer connected.</div>';
        return;
    }
    list.innerHTML = devices.map((device, index) => `
        <div class="device-card">
            <div class="device-card-main">
                <div class="device-card-title">${device.role ? roleLabel(device.role) : `New ESP32-C3 board${devices.length > 1 ? ` ${index + 1}` : ""}`}</div>
                <div class="device-card-detail">${device.classification === "other_firmware" ? "Existing non-Mira software will be replaced" : device.classification === "corrupt" ? "Existing software is incomplete or damaged" : "Mira software was not found"}</div>
            </div>
            <div class="device-setup-actions"><button class="btn" onclick="startFirmwareUpdate('', 'robot', '${escapeHtml(device.port)}')">${device.classification === "other_firmware" ? "Replace with Robot software" : "Program as Robot"}</button> <button class="btn btn-primary" onclick="startFirmwareUpdate('', 'wireless_controller', '${escapeHtml(device.port)}')">${device.classification === "other_firmware" ? "Replace with Wireless board software" : "Program as Wireless board"}</button></div>
        </div>
    `).join("");
}

async function refreshUpdates(force = false) {
    try {
        const res = await fetch(`/api/updates${force ? "?refresh=1" : ""}`);
        const data = await res.json();
        updateDevices = data.devices || [];
        renderUpdateProgress(data.update || { state: "idle" });
        maybePromptFirmwareUpdate();
    } catch (error) {
        // Update checks retry automatically on the next device event.
    }
}

async function startFirmwareUpdate(deviceId, role, port = null) {
    closeFirmwareUpdateModal();
    deviceOperationActive = true;
    openUpdateProgress(role);
    const res = await fetch("/api/updates/start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deviceId, role, port }),
    });
    const data = await res.json();
    if (!res.ok) {
        deviceOperationActive = false;
        renderUpdateProgress({ state: "failed", progress: 0, message: data.error || "The update could not start." });
        addConsoleLine(data.error || "The update could not start", "error");
    }
}

function renderUpdateProgress(update) {
    const box = document.getElementById("update-progress");
    if (!box) return;
    if (deviceModalMode !== "progress") {
        box.style.display = "none";
        return;
    }
    const active = update && update.state && update.state !== "idle";
    box.style.display = active ? "block" : "none";
    if (!active) return;
    document.getElementById("update-message").textContent = update.message || "";
    document.getElementById("update-progress-bar").style.width = `${update.progress || 0}%`;
    box.classList.toggle("update-failed", update.state === "failed");
}

function maybePromptFirmwareUpdate() {
    // Updating an ESP32-C3 temporarily removes it from the USB inventory. Do
    // not reopen the update prompt over the active progress (or failure)
    // dialog when the board disappears and reconnects during that handoff.
    if (deviceOperationActive || deviceModalMode === "progress") return;
    if (connectedDevices.some((item) => item.state === "unrecognized")) return;
    const device = updateDevices.find((item) => {
        const key = `${item.deviceId}|${item.latest}`;
        return item.updateAvailable && item.canUpdate && !firmwarePrompted.has(key);
    });
    if (!device) return;
    const key = `${device.deviceId}|${device.latest}`;
    firmwarePrompted.add(key);
    const label = roleLabel(device.role);
    const modal = document.getElementById("firmware-update-modal");
    document.getElementById("firmware-update-title").textContent = device.repairRequired
        ? `${label} software needs repair`
        : `${label} update available`;
    document.getElementById("firmware-update-description").textContent = device.repairRequired
        ? `Mira found ${label.toLowerCase()} firmware on this board, but it did not start correctly. Mira can reinstall it safely.`
        : device.legacy
        ? `This ${label.toLowerCase()} needs a one-time update before using the new automatic connection features. Keep the USB cable connected until the update finishes.`
        : `Firmware ${device.latest} is available for this ${label.toLowerCase()}. Keep the USB cable connected until the update finishes.`;
    const button = document.getElementById("firmware-update-button");
    button.textContent = device.repairRequired ? `Repair ${label}` : `Update ${label}`;
    button.onclick = () => startFirmwareUpdate(device.deviceId, device.role);
    modal.classList.add("visible");
}

function deferFirmwareUpdate() {
    closeFirmwareUpdateModal();
    maybePromptFirmwareUpdate();
}

function closeFirmwareUpdateModal() {
    document.getElementById("firmware-update-modal").classList.remove("visible");
}

// ---------------------------------------------------------------------------
// Robot List
// ---------------------------------------------------------------------------

function renderRobotList() {
    // Skip re-render while a rename is in progress to avoid destroying
    // the inline <input> (which would trigger blur → auto-save).
    if (renamingMac) {
        pendingRender = true;
        return;
    }

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
                <div class="robot-mac">${robot.online ? (robot.connection || "Connected") : "Disconnected — reconnect its cable or controller"}</div>
            </div>
            <button class="robot-menu-btn ${menuOpen ? "open" : ""}" data-mac="${robot.mac}" title="Actions" aria-label="Robot actions">${iconSvg("menu", "ui-icon")}</button>
            <div class="robot-context-menu ${menuOpen ? "visible" : ""}" data-mac="${robot.mac}">
                <button class="robot-context-item" data-action="rename" data-mac="${robot.mac}">
                    ${iconSvg("edit", "ctx-icon")} Rename
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
    updateCalibrateButton();

    // Query custom gestures for this robot
    if (selectedTarget) {
        sendCommand("seq_list");
    } else {
        customGestures = [];
        renderCustomGestures();
    }
}

function selectAllRobots() {
    selectedTarget = null;

    document.getElementById("all-robots-btn").classList.add("active");
    renderRobotList();
    updateTargetBanner();
    updateCalibrateButton();
    closeCalibration();  // Close calibration panel when deselecting
    customGestures = [];
    renderCustomGestures();
}

function updateTargetBanner() {
    const nameEl = document.getElementById("target-name");
    const badgeEl = document.getElementById("target-badge");

    if (selectedTarget) {
        nameEl.textContent = selectedTarget.name;
        nameEl.className = "target-name single";
        badgeEl.textContent = "THIS ROBOT";
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

    // Block re-renders while the user is typing
    renamingMac = robot.mac;
    pendingRender = false;

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

        // Unblock re-renders
        renamingMac = null;

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
        }

        // Flush any render that was deferred while we were renaming
        if (pendingRender) {
            pendingRender = false;
            renderRobotList();
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

/** Reset all UI sliders to the home position (grip closed at 45°). */
function resetSlidersToHome(instantRobotModel = false) {
    // Joint sliders
    document.getElementById("slider-base").value = 0;
    document.getElementById("slider-shoulder").value = 0;
    document.getElementById("slider-elbow").value = 0;
    document.getElementById("slider-grip-joint").value = GRIP_CLOSED_ANGLE;
    document.getElementById("slider-grip").value = GRIP_CLOSED_ANGLE;
    // Cartesian sliders via FK
    const homePos = fk(0, 0, 0);
    document.getElementById("slider-x").value = homePos.x.toFixed(1);
    document.getElementById("slider-y").value = homePos.y.toFixed(1);
    document.getElementById("slider-z").value = homePos.z.toFixed(1);
    xyzPositionNotice = "";
    setXYZRobotTarget({ base: 0, shoulder: 0, elbow: 0 }, instantRobotModel);
    updateSliderValues();
    updateXYZWorkspace();
}

function sendHome() {
    sendCommand("home");
    // Reset sliders to home position
    resetSlidersToHome();
    // Auto-sleep after idle period (gives servos time to reach home)
    resetSliderIdleTimer();
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
    if (kfPlaying) kfPause();
    sendCommand("stop");
    setActiveGesture(null);
    // MCU smooth-homes on stop — keep sliders in sync
    resetSlidersToHome();
}

function sendCartesianMove(force = true, continuous = false) {
    const x = parseFloat(document.getElementById("slider-x").value);
    const y = parseFloat(document.getElementById("slider-y").value);
    const z = parseFloat(document.getElementById("slider-z").value);
    const solution = solveCartesianTarget(x, y, z);
    if (!solution.valid) {
        updateXYZWorkspace();
        return false;
    }
    const command = continuous ? "track" : "smmove";
    const targetKey = `${getTargetName()}:${command}:${x.toFixed(1)},${y.toFixed(1)},${z.toFixed(1)}`;
    if (!force && targetKey === xyzLastSentTargetKey) return false;

    sendCommand(`${command} ${x.toFixed(1)} ${y.toFixed(1)} ${z.toFixed(1)}`);
    xyzLastSentTargetKey = targetKey;
    xyzLastSendMs = performance.now();
    setXYZRobotTarget(solution.joints);
    syncCartesianToJoint();
    updateXYZWorkspace();
    resetSliderIdleTimer();
    return true;
}

function scheduleLiveCartesianMove(immediate = false) {
    const target = getCartesianInputPosition();
    if (!solveCartesianTarget(target.x, target.y, target.z).valid) return;

    const now = performance.now();
    const elapsed = now - xyzLastSendMs;
    if (immediate || elapsed >= XYZ_LIVE_SEND_MS) {
        if (xyzPendingSendTimer) clearTimeout(xyzPendingSendTimer);
        xyzPendingSendTimer = null;
        sendCartesianMove(false, true);
        return;
    }

    if (xyzPendingSendTimer) clearTimeout(xyzPendingSendTimer);
    xyzPendingSendTimer = setTimeout(() => {
        xyzPendingSendTimer = null;
        sendCartesianMove(false, true);
    }, XYZ_LIVE_SEND_MS - elapsed);
}

function sendJointMove(joint) {
    const angle = parseFloat(document.getElementById(`slider-${joint}`).value);
    sendCommand(`smset ${joint} ${angle}`);
    setXYZRobotTarget({ ...xyzRobotTargetJoints, [joint]: angle });
}

function sendGrip() {
    const sliderId = controlMode === 'joint' ? "slider-grip-joint" : "slider-grip";
    const grip = parseFloat(document.getElementById(sliderId).value);
    sendCommand(`smset grip ${grip}`);
}

// ---------------------------------------------------------------------------
// Control Mode Toggle
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
    if (mode === 'cartesian') requestAnimationFrame(updateXYZWorkspace);
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
    return result !== null;
}

/**
 * Sync Joint slider values → Cartesian sliders via FK.
 * Called when switching from Joint to Cartesian mode,
 * and in the background when Joint sliders change.
 */
function syncJointToCartesian() {
    const base = parseFloat(document.getElementById("slider-base").value);
    const shoulder = parseFloat(document.getElementById("slider-shoulder").value);
    const elbow = parseFloat(document.getElementById("slider-elbow").value);

    const pos = fk(base, shoulder, elbow);

    // Clamp to slider min/max to avoid out-of-range values
    const sliderX = document.getElementById("slider-x");
    const sliderY = document.getElementById("slider-y");
    const sliderZ = document.getElementById("slider-z");

    sliderX.value = Math.max(sliderX.min, Math.min(sliderX.max, pos.x.toFixed(1)));
    sliderY.value = Math.max(sliderY.min, Math.min(sliderY.max, pos.y.toFixed(1)));
    sliderZ.value = Math.max(sliderZ.min, Math.min(sliderZ.max, pos.z.toFixed(1)));
    xyzPositionNotice = "";
    // Sync grip
    document.getElementById("slider-grip").value =
        document.getElementById("slider-grip-joint").value;
    updateSliderValues();
    updateXYZWorkspace();
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

        // Snap the starting value to the nearest multiple of tickStep at or above min.
        // This ensures tick values align with multiples of labelStep (e.g. 0, ±30, ±60)
        // even when min isn't itself a multiple (e.g. -109, -100, -126, -104).
        const start = Math.ceil(min / tickStep) * tickStep;

        for (let v = start; v <= max; v += tickStep) {
            // Round to avoid floating point drift
            const val = Math.round(v * 100) / 100;
            const reversed = container.dataset.reversed === "true";
            const pct = reversed
                ? ((max - val) / range) * 100
                : ((val - min) / range) * 100;
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
                label.textContent = reversed ? -val : val;
                tick.appendChild(label);
            }

            container.appendChild(tick);
        }
    });
}

// ---------------------------------------------------------------------------
// XYZ Workspace Navigator
// ---------------------------------------------------------------------------

const XYZ_PLANE_DEFS = {
    xy: { axisA: "x", axisB: "y", fixed: "z", rangeA: [-126, 126], rangeB: [-126, 126], labelA: "X", labelB: "Y" },
    xz: { axisA: "x", axisB: "z", fixed: "y", rangeA: [-126, 126], rangeB: [0, 148], labelA: "X", labelB: "Z" },
    yz: { axisA: "y", axisB: "z", fixed: "x", rangeA: [-126, 126], rangeB: [0, 148], labelA: "Y", labelB: "Z" },
};

function getCartesianInputPosition() {
    return {
        x: parseFloat(document.getElementById("slider-x").value),
        y: parseFloat(document.getElementById("slider-y").value),
        z: parseFloat(document.getElementById("slider-z").value),
    };
}

function roundCartesianInput(value) {
    return Math.round(value * 2) / 2;
}

function setCartesianInputPosition(position) {
    ["x", "y", "z"].forEach((axis) => {
        document.getElementById(`slider-${axis}`).value = roundCartesianInput(position[axis]).toFixed(1);
    });
    updateSliderValues();
    const result = ik(position.x, position.y, position.z);
    if (result) {
        document.getElementById("slider-base").value = result.base.toFixed(1);
        document.getElementById("slider-shoulder").value = result.shoulder.toFixed(1);
        document.getElementById("slider-elbow").value = result.elbow.toFixed(1);
    }
    updateXYZWorkspace();
}

function xyzCanvasMetrics(canvas) {
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return null;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.round(rect.width);
    const height = Math.round(rect.height);
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
    }
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { context, width, height };
}

function xyzScale(value, range, start, length) {
    return start + ((value - range[0]) / (range[1] - range[0])) * length;
}

function xyzUnscale(pixel, range, start, length) {
    return range[0] + ((pixel - start) / length) * (range[1] - range[0]);
}

function xyzTargetForPlane(definition, axisA, axisB, fixedPosition) {
    const target = { ...fixedPosition };
    target[definition.axisA] = axisA;
    target[definition.axisB] = axisB;
    return target;
}

/** Find the closest reachable half-millimeter target in one projection plane. */
function nearestReachableTargetInPlane(key, requestedTarget) {
    const definition = XYZ_PLANE_DEFS[key];
    let nearest = null;
    let nearestDistanceSq = Infinity;

    const consider = (axisA, axisB) => {
        const candidate = xyzTargetForPlane(definition, axisA, axisB, requestedTarget);
        if (!solveCartesianTarget(candidate.x, candidate.y, candidate.z).valid) return;
        const deltaA = axisA - requestedTarget[definition.axisA];
        const deltaB = axisB - requestedTarget[definition.axisB];
        const distanceSq = deltaA * deltaA + deltaB * deltaB;
        if (distanceSq < nearestDistanceSq) {
            nearest = candidate;
            nearestDistanceSq = distanceSq;
        }
    };

    // Start with the current safe position when it belongs to this slice,
    // then locate and refine the closest reachable region.
    if (Math.abs(lastValidCartesianTarget[definition.fixed] - requestedTarget[definition.fixed]) < 0.001) {
        consider(
            roundCartesianInput(lastValidCartesianTarget[definition.axisA]),
            roundCartesianInput(lastValidCartesianTarget[definition.axisB]),
        );
    }
    const coarseStep = 2;
    for (let axisB = definition.rangeB[0]; axisB <= definition.rangeB[1]; axisB += coarseStep) {
        for (let axisA = definition.rangeA[0]; axisA <= definition.rangeA[1]; axisA += coarseStep) {
            consider(axisA, axisB);
        }
    }
    if (!nearest) return null;

    const coarseA = nearest[definition.axisA];
    const coarseB = nearest[definition.axisB];
    for (let axisB = coarseB - coarseStep; axisB <= coarseB + coarseStep; axisB += 0.5) {
        if (axisB < definition.rangeB[0] || axisB > definition.rangeB[1]) continue;
        for (let axisA = coarseA - coarseStep; axisA <= coarseA + coarseStep; axisA += 0.5) {
            if (axisA < definition.rangeA[0] || axisA > definition.rangeA[1]) continue;
            consider(axisA, axisB);
        }
    }
    return nearest;
}

function xyzDrawMarker(context, x, y, color, current = false) {
    context.save();
    context.strokeStyle = color;
    context.fillStyle = "rgba(255, 255, 255, 0.9)";
    context.lineWidth = 2;
    if (current) {
        context.beginPath();
        context.arc(x, y, 4.5, 0, Math.PI * 2);
        context.fill();
        context.stroke();
    } else {
        context.beginPath();
        context.moveTo(x - 7, y);
        context.lineTo(x + 7, y);
        context.moveTo(x, y - 7);
        context.lineTo(x, y + 7);
        context.stroke();
    }
    context.restore();
}

function drawXYZPlane(key) {
    const canvas = document.getElementById(`xyz-plane-${key}`);
    const metrics = xyzCanvasMetrics(canvas);
    if (!metrics) return;

    const { context, width, height } = metrics;
    const definition = XYZ_PLANE_DEFS[key];
    const target = getCartesianInputPosition();
    const pad = { left: 25, right: 8, top: 7, bottom: 21 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const computed = getComputedStyle(document.documentElement);
    const validColor = "rgba(34, 197, 94, 0.24)";
    const gridColor = "rgba(67, 56, 202, 0.14)";
    const textColor = computed.getPropertyValue("--text-muted").trim();
    const targetColor = solveCartesianTarget(target.x, target.y, target.z).valid
        ? computed.getPropertyValue("--accent-blue").trim()
        : computed.getPropertyValue("--accent-red").trim();

    context.clearRect(0, 0, width, height);
    const sampleStep = 3;
    context.fillStyle = validColor;
    for (let py = pad.top; py < pad.top + plotHeight; py += sampleStep) {
        for (let px = pad.left; px < pad.left + plotWidth; px += sampleStep) {
            const axisA = xyzUnscale(px, definition.rangeA, pad.left, plotWidth);
            const axisB = xyzUnscale(pad.top + plotHeight - py, definition.rangeB, 0, plotHeight);
            const sample = xyzTargetForPlane(definition, axisA, axisB, target);
            if (solveCartesianTarget(sample.x, sample.y, sample.z).valid) {
                context.fillRect(px, py, sampleStep + 0.5, sampleStep + 0.5);
            }
        }
    }

    context.strokeStyle = gridColor;
    context.lineWidth = 1;
    const zeroA = xyzScale(0, definition.rangeA, pad.left, plotWidth);
    if (zeroA >= pad.left && zeroA <= pad.left + plotWidth) {
        context.beginPath();
        context.moveTo(zeroA, pad.top);
        context.lineTo(zeroA, pad.top + plotHeight);
        context.stroke();
    }
    const zeroB = pad.top + plotHeight - xyzScale(0, definition.rangeB, 0, plotHeight);
    if (zeroB >= pad.top && zeroB <= pad.top + plotHeight) {
        context.beginPath();
        context.moveTo(pad.left, zeroB);
        context.lineTo(pad.left + plotWidth, zeroB);
        context.stroke();
    }
    context.strokeRect(pad.left + 0.5, pad.top + 0.5, plotWidth - 1, plotHeight - 1);

    context.fillStyle = textColor;
    context.font = "700 9px Nunito, sans-serif";
    context.fillText(definition.labelA, width - 14, height - 5);
    context.fillText(definition.labelB, 7, 13);

    const drawPositionMarker = (position, color, current) => {
        const axisA = position[definition.axisA];
        const axisB = position[definition.axisB];
        if (axisA < definition.rangeA[0] || axisA > definition.rangeA[1]
            || axisB < definition.rangeB[0] || axisB > definition.rangeB[1]) return;
        const markerX = xyzScale(axisA, definition.rangeA, pad.left, plotWidth);
        const markerY = pad.top + plotHeight - xyzScale(axisB, definition.rangeB, 0, plotHeight);
        xyzDrawMarker(context, markerX, markerY, color, current);
    };

    drawPositionMarker(lastValidCartesianTarget, computed.getPropertyValue("--text-primary").trim(), true);
    drawPositionMarker(target, targetColor, false);
}

function buildXYZReachableVolume() {
    if (xyzReachableVolumePoints) return xyzReachableVolumePoints;
    xyzReachableVolumePoints = [];
    for (let z = 8; z <= 148; z += 10) {
        for (let y = -120; y <= 120; y += 10) {
            for (let x = -120; x <= 120; x += 10) {
                if (solveCartesianTarget(x, y, z).valid) {
                    xyzReachableVolumePoints.push({ x, y, z, depth: x + y });
                }
            }
        }
    }
    xyzReachableVolumePoints.sort((a, b) => a.depth - b.depth);
    return xyzReachableVolumePoints;
}

function xyzArmGeometry(joints) {
    const baseGeo = joints.base * DEG2RAD;
    const shoulderGeo = ((joints.shoulder - SERVO_SHOULDER_OFFSET)
        / SERVO_SHOULDER_DIRECTION) * DEG2RAD;
    const elbowGeo = ((joints.elbow - SERVO_ELBOW_OFFSET)
        / SERVO_ELBOW_DIRECTION) * DEG2RAD;
    const shoulder = { x: 0, y: 0, z: ARM_BASE_HEIGHT };
    const elbowRadius = ARM_LINK1_LENGTH * Math.cos(shoulderGeo);
    const elbow = {
        x: elbowRadius * Math.cos(baseGeo),
        y: elbowRadius * Math.sin(baseGeo),
        z: ARM_BASE_HEIGHT + ARM_LINK1_LENGTH * Math.sin(shoulderGeo),
    };
    const end = fk(joints.base, joints.shoulder, joints.elbow);
    return { base: { x: 0, y: 0, z: 0 }, shoulder, elbow, end };
}

function drawXYZRobotSchematic(context, project, computed) {
    const arm = xyzArmGeometry(xyzRobotJoints);
    const base = project(arm.base);
    const shoulder = project(arm.shoulder);
    const elbow = project(arm.elbow);
    const end = project(arm.end);
    const outline = "rgba(15, 23, 42, 0.82)";
    const linkColor = computed.getPropertyValue("--text-primary").trim();
    const jointColor = computed.getPropertyValue("--accent-blue").trim();

    const strokeSegment = (from, to, width) => {
        context.strokeStyle = outline;
        context.lineWidth = width + 3;
        context.beginPath();
        context.moveTo(from.x, from.y);
        context.lineTo(to.x, to.y);
        context.stroke();
        context.strokeStyle = linkColor;
        context.lineWidth = width;
        context.beginPath();
        context.moveTo(from.x, from.y);
        context.lineTo(to.x, to.y);
        context.stroke();
    };

    context.save();
    context.lineCap = "round";
    context.lineJoin = "round";
    strokeSegment(base, shoulder, 7);
    strokeSegment(shoulder, elbow, 6);
    strokeSegment(elbow, end, 5);

    [shoulder, elbow].forEach((joint) => {
        context.fillStyle = outline;
        context.beginPath();
        context.arc(joint.x, joint.y, 6, 0, Math.PI * 2);
        context.fill();
        context.fillStyle = jointColor;
        context.beginPath();
        context.arc(joint.x, joint.y, 3.2, 0, Math.PI * 2);
        context.fill();
    });

    // A compact two-finger claw at the FK endpoint makes the arm's pose and
    // orientation legible without obscuring the workspace volume.
    const linkDx = end.x - elbow.x;
    const linkDy = end.y - elbow.y;
    const length = Math.max(1, Math.hypot(linkDx, linkDy));
    const forwardX = linkDx / length;
    const forwardY = linkDy / length;
    const sideX = -forwardY;
    const sideY = forwardX;
    context.strokeStyle = outline;
    context.lineWidth = 3;
    [-1, 1].forEach((side) => {
        context.beginPath();
        context.moveTo(end.x, end.y);
        context.lineTo(end.x + forwardX * 8 + sideX * side * 5,
            end.y + forwardY * 8 + sideY * side * 5);
        context.stroke();
    });
    context.restore();
}

function drawXYZVolume() {
    const canvas = document.getElementById("xyz-volume-canvas");
    const metrics = xyzCanvasMetrics(canvas);
    if (!metrics) return;
    const { context, width, height } = metrics;
    const computed = getComputedStyle(document.documentElement);
    const scale = Math.min(width / 350, height / 265) * xyzVolumeZoom;
    const originX = width * 0.5;
    const originY = height * 0.82;
    const cosYaw = Math.cos(xyzVolumeYaw);
    const sinYaw = Math.sin(xyzVolumeYaw);
    const project = (point) => {
        const rotatedX = point.x * cosYaw - point.y * sinYaw;
        const rotatedDepth = point.x * sinYaw + point.y * cosYaw;
        return {
            x: originX + rotatedX * 0.82 * scale,
            y: originY + rotatedDepth * xyzVolumeElevation * scale - point.z * 0.72 * scale,
        };
    };

    context.clearRect(0, 0, width, height);
    context.fillStyle = computed.getPropertyValue("--accent-green").trim();
    context.globalAlpha = 0.23;
    buildXYZReachableVolume().forEach((point) => {
        const projected = project(point);
        context.fillRect(projected.x, projected.y, 2, 2);
    });
    context.globalAlpha = 1;

    const origin = project({ x: 0, y: 0, z: 0 });
    const axes = [
        [project({ x: 75, y: 0, z: 0 }), "X"],
        [project({ x: 0, y: 75, z: 0 }), "Y"],
        [project({ x: 0, y: 0, z: 100 }), "Z"],
    ];
    context.strokeStyle = "rgba(67, 56, 202, 0.20)";
    context.fillStyle = computed.getPropertyValue("--text-muted").trim();
    context.font = "700 9px Nunito, sans-serif";
    axes.forEach(([end, label]) => {
        context.beginPath();
        context.moveTo(origin.x, origin.y);
        context.lineTo(end.x, end.y);
        context.stroke();
        context.fillText(label, end.x + 3, end.y);
    });

    drawXYZRobotSchematic(context, project, computed);

    const target = getCartesianInputPosition();
    const currentProjected = project(lastValidCartesianTarget);
    xyzDrawMarker(context, currentProjected.x, currentProjected.y,
        computed.getPropertyValue("--text-primary").trim(), true);
    if ([target.x, target.y, target.z].every(Number.isFinite)) {
        const targetProjected = project(target);
        const targetColor = solveCartesianTarget(target.x, target.y, target.z).valid
            ? computed.getPropertyValue("--accent-blue").trim()
            : computed.getPropertyValue("--accent-red").trim();
        xyzDrawMarker(context, targetProjected.x, targetProjected.y, targetColor, false);
    }

    document.getElementById("xyz-volume-zoom").textContent = `${Math.round(xyzVolumeZoom * 100)}%`;
}

function clampXYZVolumeZoom(zoom) {
    return Math.max(0.70, Math.min(2.50, zoom));
}

function adjustXYZVolumeZoom(delta) {
    xyzVolumeZoom = clampXYZVolumeZoom(xyzVolumeZoom + delta);
    scheduleXYZWorkspaceDraw();
}

function resetXYZVolumeView() {
    xyzVolumeZoom = XYZ_DEFAULT_VOLUME_ZOOM;
    xyzVolumeYaw = XYZ_DEFAULT_VOLUME_YAW;
    xyzVolumeElevation = XYZ_DEFAULT_VOLUME_ELEVATION;
    scheduleXYZWorkspaceDraw();
}

function scheduleXYZWorkspaceDraw() {
    if (!xyzWorkspaceInitialized || xyzWorkspaceDrawPending) return;
    xyzWorkspaceDrawPending = true;
    requestAnimationFrame(() => {
        xyzWorkspaceDrawPending = false;
        drawXYZPlane("xy");
        drawXYZPlane("xz");
        drawXYZPlane("yz");
        drawXYZVolume();
    });
}

function updateXYZWorkspace() {
    if (!xyzWorkspaceInitialized) return;
    const target = getCartesianInputPosition();
    const validation = solveCartesianTarget(target.x, target.y, target.z);
    const validity = document.getElementById("xyz-validity");
    const reason = document.getElementById("xyz-invalid-reason");
    const moveButton = document.getElementById("xyz-move-btn");

    const adjusted = validation.valid && Boolean(xyzPositionNotice);
    validity.textContent = adjusted
        ? xyzPositionNotice
        : (validation.valid ? "Reachable position" : "Position not reachable");
    validity.classList.toggle("valid", validation.valid && !adjusted);
    validity.classList.toggle("invalid", !validation.valid || adjusted);
    reason.hidden = validation.valid;
    reason.textContent = validation.valid ? "" : validation.reason;
    moveButton.disabled = !validation.valid;
    ["x", "y", "z"].forEach((axis) => {
        document.getElementById(`slider-${axis}`).setAttribute("aria-invalid", validation.valid ? "false" : "true");
    });

    document.getElementById("xyz-slice-xy").textContent = `Z = ${Number.isFinite(target.z) ? target.z.toFixed(1) : "—"} mm`;
    document.getElementById("xyz-slice-xz").textContent = `Y = ${Number.isFinite(target.y) ? target.y.toFixed(1) : "—"} mm`;
    document.getElementById("xyz-slice-yz").textContent = `X = ${Number.isFinite(target.x) ? target.x.toFixed(1) : "—"} mm`;
    scheduleXYZWorkspaceDraw();
}

function updateCartesianFromPlane(key, event, resetFilter = false) {
    const canvas = document.getElementById(`xyz-plane-${key}`);
    const definition = XYZ_PLANE_DEFS[key];
    const rect = canvas.getBoundingClientRect();
    const pad = { left: 25, right: 8, top: 7, bottom: 21 };
    const plotWidth = rect.width - pad.left - pad.right;
    const plotHeight = rect.height - pad.top - pad.bottom;
    const localX = Math.max(pad.left, Math.min(pad.left + plotWidth, event.clientX - rect.left));
    const localY = Math.max(pad.top, Math.min(pad.top + plotHeight, event.clientY - rect.top));
    const target = getCartesianInputPosition();
    target[definition.axisA] = xyzUnscale(localX, definition.rangeA, pad.left, plotWidth);
    target[definition.axisB] = xyzUnscale(pad.top + plotHeight - localY, definition.rangeB, 0, plotHeight);
    if (resetFilter || !xyzDragFilteredTarget) {
        xyzDragFilteredTarget = { ...target };
    } else {
        [definition.axisA, definition.axisB].forEach((axis) => {
            xyzDragFilteredTarget[axis] += XYZ_DRAG_FILTER_ALPHA
                * (target[axis] - xyzDragFilteredTarget[axis]);
        });
        xyzDragFilteredTarget[definition.fixed] = target[definition.fixed];
    }
    let moveTarget = xyzDragFilteredTarget;
    xyzPositionNotice = "";
    if (!solveCartesianTarget(moveTarget.x, moveTarget.y, moveTarget.z).valid) {
        const nearest = nearestReachableTargetInPlane(key, moveTarget);
        if (nearest) {
            moveTarget = nearest;
            xyzPositionNotice = "Position not reachable — going to the nearest reachable position.";
        }
    }
    setCartesianInputPosition(moveTarget);
    scheduleLiveCartesianMove();
}

function initXYZWorkspace() {
    if (xyzWorkspaceInitialized) return;
    xyzWorkspaceInitialized = true;

    Object.keys(XYZ_PLANE_DEFS).forEach((key) => {
        const canvas = document.getElementById(`xyz-plane-${key}`);
        let dragging = false;
        canvas.addEventListener("pointerdown", (event) => {
            dragging = true;
            canvas.setPointerCapture(event.pointerId);
            updateCartesianFromPlane(key, event, true);
            scheduleLiveCartesianMove(true);
        });
        canvas.addEventListener("pointermove", (event) => {
            if (dragging) updateCartesianFromPlane(key, event);
        });
        const stopDragging = (event) => {
            if (dragging) {
                updateCartesianFromPlane(key, event, true);
                scheduleLiveCartesianMove(true);
            }
            dragging = false;
            xyzDragFilteredTarget = null;
        };
        canvas.addEventListener("pointerup", stopDragging);
        canvas.addEventListener("pointercancel", () => {
            dragging = false;
            xyzDragFilteredTarget = null;
        });
    });

    const volumeCanvas = document.getElementById("xyz-volume-canvas");
    let rotating = false;
    let previousPointerX = 0;
    let previousPointerY = 0;
    volumeCanvas.addEventListener("pointerdown", (event) => {
        rotating = true;
        previousPointerX = event.clientX;
        previousPointerY = event.clientY;
        volumeCanvas.classList.add("dragging");
        volumeCanvas.setPointerCapture(event.pointerId);
    });
    volumeCanvas.addEventListener("pointermove", (event) => {
        if (!rotating) return;
        const deltaX = event.clientX - previousPointerX;
        const deltaY = event.clientY - previousPointerY;
        previousPointerX = event.clientX;
        previousPointerY = event.clientY;
        xyzVolumeYaw += deltaX * 0.012;
        xyzVolumeElevation = Math.max(0.08, Math.min(0.62,
            xyzVolumeElevation + deltaY * 0.004));
        scheduleXYZWorkspaceDraw();
    });
    const stopRotating = () => {
        rotating = false;
        volumeCanvas.classList.remove("dragging");
    };
    volumeCanvas.addEventListener("pointerup", stopRotating);
    volumeCanvas.addEventListener("pointercancel", stopRotating);
    volumeCanvas.addEventListener("dblclick", resetXYZVolumeView);
    volumeCanvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        const zoomFactor = Math.exp(-event.deltaY * 0.0015);
        xyzVolumeZoom = clampXYZVolumeZoom(xyzVolumeZoom * zoomFactor);
        scheduleXYZWorkspaceDraw();
    }, { passive: false });

    ["x", "y", "z"].forEach((axis) => {
        const input = document.getElementById(`slider-${axis}`);
        input.addEventListener("input", () => {
            xyzPositionNotice = "";
            const target = getCartesianInputPosition();
            const result = ik(target.x, target.y, target.z);
            if (result) {
                document.getElementById("slider-base").value = result.base.toFixed(1);
                document.getElementById("slider-shoulder").value = result.shoulder.toFixed(1);
                document.getElementById("slider-elbow").value = result.elbow.toFixed(1);
            }
            updateXYZWorkspace();
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !document.getElementById("xyz-move-btn").disabled) {
                sendCartesianMove();
            }
        });
    });

    const workspace = document.getElementById("sliders-cartesian");
    if (window.ResizeObserver) {
        new ResizeObserver(scheduleXYZWorkspaceDraw).observe(workspace);
    } else {
        window.addEventListener("resize", scheduleXYZWorkspaceDraw);
    }
    updateXYZWorkspace();
}

// ---------------------------------------------------------------------------
// Sliders
// ---------------------------------------------------------------------------

function initSliders() {
    initXYZWorkspace();

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
    updateGripValue("slider-grip", "value-grip");

    // Joint
    updateDirectionalValue("slider-base", "value-base", "right", "left", "Centered");
    updateDirectionalValue("slider-shoulder", "value-shoulder", "up", "down", "Level");
    updateDirectionalValue("slider-elbow", "value-elbow", "up", "down", "Level");
    updateGripValue("slider-grip-joint", "value-grip-joint");
}

function updateDirectionalValue(sliderId, valueId, negativeDirection, positiveDirection, centerLabel) {
    const slider = document.getElementById(sliderId);
    const value = parseFloat(slider.value);
    const label = Math.abs(value) < 0.5
        ? centerLabel
        : `${Math.abs(value).toFixed(0)}° ${value < 0 ? negativeDirection : positiveDirection}`;
    document.getElementById(valueId).textContent = label;
    slider.setAttribute("aria-valuetext", label);
}

function gripStateLabel(angle) {
    if (angle < GRIP_OPEN_ANGLE) return "Extra open";
    if (angle === GRIP_OPEN_ANGLE) return "Open";
    if (angle > GRIP_CLOSED_ANGLE) return "Extra closed";
    if (angle === GRIP_CLOSED_ANGLE) return "Closed";
    const closedPercent = Math.round(
        ((angle - GRIP_OPEN_ANGLE) / (GRIP_CLOSED_ANGLE - GRIP_OPEN_ANGLE)) * 100
    );
    return `${closedPercent}% closed`;
}

function updateGripValue(sliderId, valueId) {
    const slider = document.getElementById(sliderId);
    const label = gripStateLabel(parseFloat(slider.value));
    document.getElementById(valueId).textContent = label;
    slider.setAttribute("aria-valuetext", label);
}

function throttledSend(fn) {
    if (sliderThrottleTimer) clearTimeout(sliderThrottleTimer);
    sliderThrottleTimer = setTimeout(() => {
        fn();
        sliderThrottleTimer = null;
    }, SLIDER_THROTTLE_MS);
    resetSliderIdleTimer();
}

function throttledSendGrip() {
    if (gripThrottleTimer) clearTimeout(gripThrottleTimer);
    gripThrottleTimer = setTimeout(() => {
        sendGrip();
        gripThrottleTimer = null;
    }, SLIDER_THROTTLE_MS);
    resetSliderIdleTimer();
}

/**
 * Reset the slider idle timer. After SLIDER_IDLE_MS of no slider
 * activity, sends a 'sleep' command to disable servo PWM.
 * The MCU auto-wakes on the next servo command.
 */
function resetSliderIdleTimer() {
    if (sliderIdleTimer) clearTimeout(sliderIdleTimer);
    sliderIdleTimer = setTimeout(() => {
        sendCommand('sleep');
        sliderIdleTimer = null;
    }, SLIDER_IDLE_MS);
}

/** Cancel any pending slider idle timer (e.g. when a gesture or playback starts). */
function clearSliderIdleTimer() {
    if (sliderIdleTimer) {
        clearTimeout(sliderIdleTimer);
        sliderIdleTimer = null;
    }
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
        btn.innerHTML = `${iconSvg("play", "play-icon")} ${iconSvg(g.icon, "gesture-symbol")}<span>${g.label}</span>`;

        btn.addEventListener("click", () => {
            toggleGesture(g);
        });

        grid.appendChild(btn);
    });
}

function toggleGesture(gesture) {
    if (kfPlaying) kfPause();
    clearSliderIdleTimer();  // Don't sleep during gesture playback
    if (gesture.continuous) {
        if (activeGesture === gesture.id) {
            // Stop it
            sendCommand(`gesture ${gesture.id} stop`);
            setActiveGesture(null);
        } else {
            // Start new — MCU handles smooth transition from previous gesture
            sendCommand(`gesture ${gesture.id}`);
            setActiveGesture(gesture.id);
        }
    } else {
        // One-shot: just start it — MCU handles stopping previous gesture
        sendCommand(`gesture ${gesture.id}`);
        setActiveGesture(null);  // One-shots don't stay "active" in UI
    }
}

function setActiveGesture(id) {
    activeGesture = id;

    GESTURES.forEach((g) => {
        const btn = document.getElementById(`gesture-${g.id}`);
        if (!btn) return;

        if (g.id === id) {
            btn.classList.add("active");
            btn.innerHTML = `${iconSvg("stop", "play-icon")} ${iconSvg(g.icon, "gesture-symbol")}<span>${g.label}</span>`;
        } else {
            btn.classList.remove("active");
            btn.innerHTML = `${iconSvg("play", "play-icon")} ${iconSvg(g.icon, "gesture-symbol")}<span>${g.label}</span>`;
        }
    });

    // Update custom gesture buttons
    customGestures.forEach(name => {
        const btn = document.getElementById(`gesture-custom-${name}`);
        if (!btn) return;
        if (name === id) {
            btn.classList.add("active");
            btn.innerHTML = `${iconSvg("stop", "play-icon")} ${iconSvg("spark", "gesture-symbol")}<span>${name}</span>`;
        } else {
            btn.classList.remove("active");
            btn.innerHTML = `${iconSvg("play", "play-icon")} ${iconSvg("spark", "gesture-symbol")}<span>${name}</span>`;
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
// Parent- and kid-friendly help
// ---------------------------------------------------------------------------

const HELP_TOPICS = new Set(["start", "move", "animate", "calibrate", "dance"]);

function openHelp(topic = "start") {
    document.getElementById("help-modal").classList.add("visible");
    showHelpTopic(topic);
}

function closeHelp() {
    document.getElementById("help-modal").classList.remove("visible");
}

function showHelpTopic(topic) {
    const selected = HELP_TOPICS.has(topic) ? topic : "start";
    document.querySelectorAll("[data-help-topic]").forEach(section => {
        section.classList.toggle("active", section.dataset.helpTopic === selected);
    });
    document.querySelectorAll("[data-help-tab]").forEach(button => {
        const active = button.dataset.helpTab === selected;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
    });
}

// ---------------------------------------------------------------------------
// Servo Calibration
// ---------------------------------------------------------------------------

let calThrottleTimers = {};  // per-joint throttle timers for calibration sliders

/** Show/hide the Calibrate button based on whether a single robot is selected. */
function updateCalibrateButton() {
    const btn = document.getElementById("btn-calibrate");
    if (btn) {
        btn.style.display = selectedTarget ? "" : "none";
    }
    
    const uploadBtn = document.getElementById("kf-upload-btn");
    if (uploadBtn) {
        const canUpload = deviceType === "robot" || selectedTarget !== null;
        uploadBtn.style.display = canUpload ? "" : "none";
    }
}

/** Toggle calibration panel — open if closed, cancel if open. */
function toggleCalibration() {
    if (calibrationOpening) return;
    if (calibrationOpen) {
        calCancel();
    } else {
        openCalibration();
    }
}

function setCalibrationControlsLoading(loading) {
    const controlsDisabled = loading || calibrationOpening;
    document.querySelectorAll("#calibration-sliders input").forEach(input => {
        input.disabled = controlsDisabled;
    });
    document.getElementById("calibration-card").setAttribute("aria-busy", controlsDisabled ? "true" : "false");
    updateCalibrationActionState();
}

function calibrationPreviewPending() {
    return Object.values(calThrottleTimers).some(timer => timer !== null && timer !== undefined);
}

function updateCalibrationActionState() {
    const controlsDisabled = calibrationOpening || calibrationLoadPending || calibrationPreviewPending();
    document.getElementById("cal-apply").disabled = controlsDisabled || !calibrationAtHome;
    document.getElementById("cal-reset").disabled = controlsDisabled;
    document.querySelectorAll(".btn-claw-test").forEach(button => {
        button.disabled = controlsDisabled;
    });
}

function setCalibrationGripTestPosition(position) {
    calibrationGripTestPosition = position;
    document.querySelectorAll(".btn-claw-test").forEach(button => {
        const active = button.dataset.position === position;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
    });
}

function clearCalibrationPreviewTimers() {
    Object.values(calThrottleTimers).forEach(timer => {
        if (timer) clearTimeout(timer);
    });
    calThrottleTimers = {};
}

/** Reveal calibration immediately while Home and saved offsets are prepared. */
function openCalibration() {
    calibrationOpening = true;
    calibrationAtHome = false;
    document.getElementById("btn-calibrate").disabled = true;

    // Give immediate visual feedback. Controls remain disabled until both the
    // Home move and the calibration-value request have had time to complete.
    revealCalibration();
    sendHome();
    loadCalibrationValues();
    addConsoleLine("Returning Home before calibration…", "system");

    if (calibrationOpenTimer) clearTimeout(calibrationOpenTimer);
    calibrationOpenTimer = setTimeout(() => {
        calibrationOpenTimer = null;
        calibrationOpening = false;
        calibrationAtHome = true;
        document.getElementById("btn-calibrate").disabled = false;
        setCalibrationControlsLoading(calibrationLoadPending);
    }, 900);
}

function revealCalibration() {
    calibrationOpen = true;
    calibrationLoadPending = true;
    setCalibrationGripTestPosition("closed");
    document.getElementById("calibration-card").style.display = "";

    // Show a neutral value until the device replies with its saved offsets.
    ["cal-base", "cal-shoulder", "cal-elbow", "cal-grip"].forEach(id => {
        document.getElementById(id).value = 0;
    });
    loadedCalibration = { base: 0, shoulder: 0, elbow: 0, grip: 0 };
    updateCalValues();
    setCalibrationControlsLoading(true);

    // Re-init tick marks for calibration sliders (they're dynamically shown)
    initSliderTicks();

    addConsoleLine("Calibration mode: adjust sliders until robot is in home position", "system");
}

function loadCalibrationValues() {
    // Preserve command ordering: request Home before reading saved offsets.
    sendCommand("cal_get");

    if (calibrationLoadTimer) clearTimeout(calibrationLoadTimer);
    calibrationLoadTimer = setTimeout(() => {
        if (!calibrationOpen || !calibrationLoadPending) return;
        calibrationLoadPending = false;
        calibrationLoadTimer = null;
        setCalibrationControlsLoading(false);
        addConsoleLine("Could not read saved calibration; showing zero values", "warning");
    }, 1500);
}

/** Persist the already-previewed pose without issuing another movement. */
function calApply() {
    if (calibrationLoadPending || calibrationPreviewPending() || !calibrationAtHome) return;

    const base = parseFloat(document.getElementById("cal-base").value);
    const shoulder = parseFloat(document.getElementById("cal-shoulder").value);
    const elbow = parseFloat(document.getElementById("cal-elbow").value);
    const grip = parseFloat(document.getElementById("cal-grip").value);

    sendCommand(`cal_set ${base} ${shoulder} ${elbow} ${grip}`);
    closeCalibration();
    addConsoleLine("Calibration saved; robot remains in its aligned Home pose", "system");
}

/** Reset calibration to zero on the robot. */
function calReset() {
    clearCalibrationPreviewTimers();
    calibrationAtHome = false;
    setCalibrationGripTestPosition("closed");
    sendCommand("cal_reset");
    calibrationLoadPending = false;
    if (calibrationLoadTimer) clearTimeout(calibrationLoadTimer);
    calibrationLoadTimer = null;
    setCalibrationControlsLoading(false);
    loadedCalibration = { base: 0, shoulder: 0, elbow: 0, grip: 0 };

    // Reset sliders to zero
    ["cal-base", "cal-shoulder", "cal-elbow", "cal-grip"].forEach(id => {
        document.getElementById(id).value = 0;
    });
    updateCalValues();

    // Re-home with cleared offsets
    setTimeout(() => {
        sendCommand("home");
        calibrationAtHome = true;
        updateCalibrationActionState();
    }, 100);
    updateCalibrationActionState();
}

/** Preview the candidate grip calibration at a known open or closed pose. */
function calGripTest(position) {
    const candidateOffset = parseFloat(document.getElementById("cal-grip").value);
    sendCommand(`cal_preview grip ${candidateOffset} ${position}`);
    setCalibrationGripTestPosition(position);
    calibrationAtHome = position === "closed";
    updateCalibrationActionState();
    resetSliderIdleTimer();
}

/** Cancel calibration without saving. */
function calCancel() {
    closeCalibration();
    // Return to home (offsets unchanged from before calibration)
    sendCommand("home");
    resetSlidersToHome();
    resetSliderIdleTimer();
}

/** Close the calibration panel. */
function closeCalibration() {
    if (calibrationOpenTimer) clearTimeout(calibrationOpenTimer);
    calibrationOpenTimer = null;
    calibrationOpening = false;
    const calibrateButton = document.getElementById("btn-calibrate");
    if (calibrateButton) calibrateButton.disabled = false;
    clearCalibrationPreviewTimers();
    calibrationOpen = false;
    calibrationLoadPending = false;
    calibrationAtHome = true;
    setCalibrationGripTestPosition("closed");
    if (calibrationLoadTimer) clearTimeout(calibrationLoadTimer);
    calibrationLoadTimer = null;
    setCalibrationControlsLoading(false);
    document.getElementById("calibration-card").style.display = "none";
}

/** Update the displayed values next to each calibration slider. */
function updateCalValues() {
    document.getElementById("value-cal-base").textContent =
        parseFloat(document.getElementById("cal-base").value).toFixed(1);
    document.getElementById("value-cal-shoulder").textContent =
        parseFloat(document.getElementById("cal-shoulder").value).toFixed(1);
    document.getElementById("value-cal-elbow").textContent =
        parseFloat(document.getElementById("cal-elbow").value).toFixed(1);
    document.getElementById("value-cal-grip").textContent =
        parseFloat(document.getElementById("cal-grip").value).toFixed(1);
}

/** Wire up calibration slider input events. */
function initCalibrationSliders() {
    // Arm offsets are previewed at Home. Grip uses whichever exclusive test
    // pose is active so moving its slider never jumps between open and closed.
    const joints = [
        { id: "cal-base", joint: "base" },
        { id: "cal-shoulder", joint: "shoulder" },
        { id: "cal-elbow", joint: "elbow" },
        { id: "cal-grip", joint: "grip" },
    ];

    joints.forEach(({ id, joint }) => {
        document.getElementById(id).addEventListener("input", () => {
            calibrationLoadPending = false;
            calibrationAtHome = false;
            updateCalValues();

            // Throttled instant servo move so the user can see the effect
            if (calThrottleTimers[joint]) clearTimeout(calThrottleTimers[joint]);
            calThrottleTimers[joint] = setTimeout(() => {
                const offset = parseFloat(document.getElementById(id).value);
                // The firmware also applies its saved offset. Subtract the
                // loaded value so the slider represents the desired total.
                const pose = joint === "grip" ? calibrationGripTestPosition : "home";
                sendCommand(`cal_preview ${joint} ${offset} ${pose}`);
                calThrottleTimers[joint] = null;
                calibrationAtHome = calibrationGripTestPosition === "closed";
                updateCalibrationActionState();
            }, SLIDER_THROTTLE_MS);
            updateCalibrationActionState();

            resetSliderIdleTimer();
        });
    });
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

function kfAutosave() {
    fetch("/api/sequence/autosave", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyframes })
    }).catch(e => console.error("Autosave failed", e));
}

async function kfAutoload() {
    try {
        const res = await fetch("/api/sequence/autoload?t=" + new Date().getTime(), { cache: "no-store" });
        const data = await res.json();
        if (data && data.keyframes && data.keyframes.length > 0) {
            keyframes = data.keyframes;
            kfRender();
            addConsoleLine(`Loaded autosaved sequence (${keyframes.length} keyframes)`, "system");
        }
    } catch (e) {
        console.error("Autoload failed", e);
    }
}

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
        base = result.base;
        shoulder = result.shoulder;
        elbow = result.elbow;
        grip = parseFloat(document.getElementById("slider-grip").value);
    } else {
        base = parseFloat(document.getElementById("slider-base").value);
        shoulder = parseFloat(document.getElementById("slider-shoulder").value);
        elbow = parseFloat(document.getElementById("slider-elbow").value);
        grip = parseFloat(document.getElementById("slider-grip-joint").value);
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
    kfAutosave();
    addConsoleLine(`Keyframe ${keyframes.length} added: B=${kf.base.toFixed(1)} S=${kf.shoulder.toFixed(1)} E=${kf.elbow.toFixed(1)} G=${kf.grip.toFixed(0)} (${kf.durationMs}ms)`, "system");
}

function kfRemoveKeyframe(index) {
    if (kfPlaying) return;
    keyframes.splice(index, 1);
    kfRender();
    kfAutosave();
}

function kfClear() {
    if (keyframes.length === 0) return;
    document.getElementById("confirm-clear-modal").classList.add("visible");
}

function closeConfirmClearModal() {
    document.getElementById("confirm-clear-modal").classList.remove("visible");
}

function executeKfClear() {
    closeConfirmClearModal();
    if (kfPlaying) kfPause();
    keyframes = [];
    kfPlayheadTimeMs = 0;
    kfRender();
    kfAutosave();
    addConsoleLine("Cleared all keyframes", "system");
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
                del.innerHTML = iconSvg("close", "ui-icon");
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
                        kfAutosave();
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
        kfAutosave();
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
        if (save) kfAutosave();
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
    clearSliderIdleTimer();  // Don't sleep during sequencer playback
    if (keyframes.length === 0) {
        addConsoleLine("No keyframes to play", "warning");
        return;
    }

    kfPlaying = true;
    kfPlayStartOffsetMs = kfPlayheadTimeMs;  // remember where we're starting from
    kfPlayStartMs = performance.now();

    const btn = document.getElementById("kf-play-btn");
    btn.classList.add("playing");
    setSvgIcon(document.getElementById("kf-play-icon"), "pause");
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
    setSvgIcon(document.getElementById("kf-play-icon"), "play");
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

// --- Upload to Robot ---
function kfUploadToRobot() {
    if (keyframes.length === 0) {
        addConsoleLine("No keyframes to upload", "warning");
        return;
    }
    // Open naming modal
    document.getElementById("name-gesture-modal").classList.add("visible");
    const input = document.getElementById("gesture-name-input");
    input.value = "";
    input.focus();
    document.getElementById("gesture-name-error").style.display = "none";
}

function closeNameGestureModal() {
    document.getElementById("name-gesture-modal").classList.remove("visible");
}

function showGestureNameError(msg) {
    const err = document.getElementById("gesture-name-error");
    err.textContent = msg;
    err.style.display = "";
}

function submitGestureName() {
    const input = document.getElementById("gesture-name-input");
    const name = input.value.trim();

    // Validation
    if (!name) {
        showGestureNameError("Please enter a name");
        return;
    }
    if (name.length > 15) {
        showGestureNameError("Name must be 15 characters or less");
        return;
    }
    if (/\s/.test(name)) {
        showGestureNameError("Name cannot contain spaces (use underscores)");
        return;
    }

    closeNameGestureModal();

    // Show uploading state on button
    const btn = document.getElementById("kf-upload-btn");
    btn.disabled = true;
    btn.classList.add("uploading");
    setSvgIcon(btn.querySelector(".icon"), "loop");

    // 1. Clear staging
    sendCommand("seq_clear");

    // 2. Set loop flag from the Loop toggle
    sendCommand(`seq_loop ${kfLooping ? 1 : 0}`);

    // 3. Add keyframes to staging (max 50)
    const limit = Math.min(keyframes.length, 50);
    if (keyframes.length > 50) {
        addConsoleLine("Truncating to first 50 keyframes", "warning");
    }
    for (let i = 0; i < limit; i++) {
        const kf = keyframes[i];
        sendCommand(`seq_add ${kf.base.toFixed(1)} ${kf.shoulder.toFixed(1)} ${kf.elbow.toFixed(1)} ${kf.grip.toFixed(1)} ${kf.durationMs}`);
    }

    // 4. Save with name (triggers SEQ_SAVE_OK or SEQ_SAVE_ERR)
    setTimeout(() => {
        sendCommand(`seq_save ${name}`);
    }, 200);

    // 4. Safety timeout
    setTimeout(() => {
        if (btn.disabled) {
            handleUploadResult({ ok: false, reason: "Timeout \u2014 no response from robot" });
        }
    }, 5000);
}

function handleUploadResult(data) {
    const btn = document.getElementById("kf-upload-btn");
    btn.disabled = false;
    btn.classList.remove("uploading");

    const icon = btn.querySelector(".icon");

    if (data.ok) {
        btn.classList.add("upload-success");
        setSvgIcon(icon, "check");
        addConsoleLine(`Gesture "${data.name}" uploaded (${data.count} keyframes, ${data.loop ? "looping" : "one-shot"})!`, "system");
        // Refresh the custom gesture list from the robot
        sendCommand("seq_list");
    } else {
        btn.classList.add("upload-error");
        setSvgIcon(icon, "warning");
        addConsoleLine(`Upload failed: ${data.reason || 'Unknown error'}`, "error");
    }

    // Reset button after 3s
    setTimeout(() => {
        btn.classList.remove("upload-success", "upload-error");
        setSvgIcon(icon, "upload");
    }, 3000);
}

// --- Custom Gesture Grid ---
function renderCustomGestures() {
    let container = document.getElementById("custom-gesture-section");

    // Only show when a single robot is selected (or direct robot mode)
    const canShow = (deviceType === "robot" || selectedTarget !== null) && customGestures.length > 0;

    if (!canShow) {
        if (container) container.style.display = "none";
        return;
    }

    // Create section if it doesn't exist
    if (!container) {
        container = document.createElement("div");
        container.id = "custom-gesture-section";
        const grid = document.getElementById("gesture-grid");
        grid.parentNode.insertBefore(container, grid.nextSibling);
    }
    container.style.display = "";

    container.innerHTML = `
        <div class="custom-gestures-label">${iconSvg("spark", "ui-icon")} Custom Gestures</div>
        <div class="gesture-grid" id="custom-gesture-grid"></div>
    `;

    const grid = container.querySelector("#custom-gesture-grid");
    customGestures.forEach(name => {
        const wrapper = document.createElement("div");
        wrapper.className = "gesture-btn-wrapper";

        const btn = document.createElement("button");
        btn.className = "gesture-btn custom-gesture-btn";
        btn.id = `gesture-custom-${name}`;
        btn.innerHTML = `${iconSvg("play", "play-icon")} ${iconSvg("spark", "gesture-symbol")}<span>${name}</span>`;

        btn.addEventListener("click", () => {
            toggleCustomGesture(name);
        });

        // Delete button
        const del = document.createElement("button");
        del.className = "custom-gesture-delete";
        del.innerHTML = iconSvg("close", "ui-icon");
        del.title = `Delete "${name}"`;
        del.addEventListener("click", (e) => {
            e.stopPropagation();
            deleteCustomGesture(name);
        });

        wrapper.appendChild(btn);
        wrapper.appendChild(del);
        grid.appendChild(wrapper);
    });
}

function toggleCustomGesture(name) {
    if (kfPlaying) kfPause();
    clearSliderIdleTimer();

    if (activeGesture === name) {
        sendCommand(`gesture ${name} stop`);
        setActiveGesture(null);
    } else {
        sendCommand(`gesture ${name}`);
        setActiveGesture(name);
    }
}

function deleteCustomGesture(name) {
    sendCommand(`seq_delete ${name}`);
}

function handleDeleteResult(data) {
    if (data.ok) {
        addConsoleLine(`Gesture "${data.name}" deleted`, "system");
        sendCommand("seq_list");
    } else {
        addConsoleLine(`Delete failed: ${data.reason}`, "error");
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
            kfAutosave();

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
        btn.innerHTML = `${iconSvg("chevron-up", "ui-icon")} Show`;
        panel.style.height = ""; // reset inline height so CSS var takes over
    } else {
        btn.innerHTML = `${iconSvg("chevron-down", "ui-icon")} Hide`;
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
    initCalibrationSliders();
    updateSliderValues();
    kfRender();
    initKfZoom();
    kfAutoload();
    initConsoleResize();
    initSectionBackground();

    // Useful for documentation links and screenshots, e.g. ?help=animate.
    const requestedHelp = new URLSearchParams(window.location.search).get("help");
    if (requestedHelp && HELP_TOPICS.has(requestedHelp)) openHelp(requestedHelp);
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
    // Card order: 0 = Move the Arm, 1 = Calibration, 2 = Animation Maker, 3 = Dance Moves
    const mapping = ['bg-arm', null, 'bg-animation', 'bg-dance'];

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

document.getElementById("device-settings-modal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeDeviceSettings();
});

document.getElementById("erase-device-modal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeEraseDeviceModal();
});

document.getElementById("help-modal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeHelp();
});

// Keyboard shortcut: Escape to close modal/menus
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeAllMenus();
        closeSettings();
        closeFirmwareUpdateModal();
        closeDeviceSettings();
        closeEraseDeviceModal();
        closeHelp();
        closeNameGestureModal();
    }
});

// Click outside to close context menus
document.addEventListener("click", (e) => {
    if (!e.target.closest(".robot-menu-btn") && !e.target.closest(".robot-context-menu")) {
        closeAllMenus();
    }
});

// Close modals on overlay click
document.getElementById("name-gesture-modal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) {
        closeNameGestureModal();
    }
});

// Submit gesture name on Enter key
document.getElementById("gesture-name-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        submitGestureName();
    }
});

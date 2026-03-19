let parts: string[] = []
let verb = ""
let action = ""
let value = 0
let rawData = ""

// Helper function to handle signed wheel speeds (-100 to 100)
function setWheel(wheel: LR, speed: number) {
    let dir = MD.Forward
    if (speed < 0) {
        dir = MD.Back
    }
    mecanumRobotV2.Motor(wheel, dir, Math.abs(speed))
}

// Listen for commands from the Python robot controller
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    rawData = serial.readString().trim()
    parts = rawData.split(":")

    verb = parts[0]   // S, G, or A
    action = parts[1] // ULD, MFW, WFL, etc.
    value = parseInt(parts[2])

    // --- SETTERS (S) ---
    if (verb == "S") {

        // Motion Controls
        if (action == "STP") {
            mecanumRobotV2.state() // Stops the car
        } else if (action == "MFW") {
            mecanumRobotV2.Motor(LR.Upper_left, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Upper_right, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Lower_left, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Lower_right, MD.Forward, value)
        } else if (action == "MBW") {
            mecanumRobotV2.Motor(LR.Upper_left, MD.Back, value)
            mecanumRobotV2.Motor(LR.Upper_right, MD.Back, value)
            mecanumRobotV2.Motor(LR.Lower_left, MD.Back, value)
            mecanumRobotV2.Motor(LR.Lower_right, MD.Back, value)
        } else if (action == "MSR") {
            mecanumRobotV2.Motor(LR.Upper_left, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Upper_right, MD.Back, value)
            mecanumRobotV2.Motor(LR.Lower_left, MD.Back, value)
            mecanumRobotV2.Motor(LR.Lower_right, MD.Forward, value)
        } else if (action == "MSL") {
            mecanumRobotV2.Motor(LR.Upper_left, MD.Back, value)
            mecanumRobotV2.Motor(LR.Upper_right, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Lower_left, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Lower_right, MD.Back, value)
        } else if (action == "RTL") {
            mecanumRobotV2.Motor(LR.Upper_left, MD.Back, value)
            mecanumRobotV2.Motor(LR.Upper_right, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Lower_left, MD.Back, value)
            mecanumRobotV2.Motor(LR.Lower_right, MD.Forward, value)
        } else if (action == "RTR") {
            mecanumRobotV2.Motor(LR.Upper_left, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Upper_right, MD.Back, value)
            mecanumRobotV2.Motor(LR.Lower_left, MD.Forward, value)
            mecanumRobotV2.Motor(LR.Lower_right, MD.Back, value)
        }

        // Individual Wheel Actuators
        else if (action == "WFL") {
            setWheel(LR.Upper_left, value)
        } else if (action == "WFR") {
            setWheel(LR.Upper_right, value)
        } else if (action == "WBL") {
            setWheel(LR.Lower_left, value)
        } else if (action == "WBR") {
            setWheel(LR.Lower_right, value)
        }

        // Sensor Setters
        else if (action == "ULA") {
            mecanumRobotV2.setServo(value)
        }

        // Display Setters
        else if (action == "LDL") {
            mecanumRobotV2.setLed(LedCount.Left, value == 0 ? LedState.OFF : LedState.ON)
        } else if (action == "DIC") {
            basic.clearScreen() // Clears the micro:bit dot matrix
        }
    }

    // --- GETTERS (G) ---
    else if (verb == "G") {
        if (action == "ULD") {
            // Get Ultrasonic Distance
            serial.writeLine("" + mecanumRobotV2.ultra())
        } else if (action == "LTR") {
            // Get Line Tracker: 0=Left, 1=Center, 2=Right
            if (value == 0) {
                serial.writeLine("" + mecanumRobotV2.LineTracking(LT.Left))
            } else if (value == 1) {
                serial.writeLine("" + mecanumRobotV2.LineTracking(LT.Center))
            } else if (value == 2) {
                serial.writeLine("" + mecanumRobotV2.LineTracking(LT.Right))
            }
        }
    }

    // --- ARRAY/SPECIAL (A) ---
    else if (verb == "A") {
        if (action == "DIS") {
            // Standard Micro:bit matrix display doesn't easily parse 
            // a full array from string in one go, but we can show the string
            // or use a guessed library method if available.
            basic.showString(parts[2])
        }
    }
})
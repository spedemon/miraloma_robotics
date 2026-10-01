/* Android bridge presenting the small Socket.IO/HTTP surface used by app.js. */
(function () {
    "use strict";

    class MobileSocket {
        constructor() {
            this.handlers = new Map();
        }

        on(event, handler) {
            if (!this.handlers.has(event)) this.handlers.set(event, []);
            this.handlers.get(event).push(handler);
        }

        emit(event, data) {
            if (event === "send_command") {
                window.MiraAndroid.sendCommand(
                    String(data?.target || "all"),
                    String(data?.command || "")
                );
            } else if (event === "request_robot_list") {
                window.MiraAndroid.refreshState();
            }
        }

        dispatch(event, data) {
            (this.handlers.get(event) || []).forEach((handler) => handler(data));
        }
    }

    const socket = new MobileSocket();

    function structuredLine(target, text) {
        let match = text.match(/Calibration:\s+B=(-?\d+(?:\.\d+)?)\s+S=(-?\d+(?:\.\d+)?)\s+E=(-?\d+(?:\.\d+)?)\s+G=(-?\d+(?:\.\d+)?)/);
        if (match) {
            socket.dispatch("calibration_values", {
                base: Number(match[1]), shoulder: Number(match[2]),
                elbow: Number(match[3]), grip: Number(match[4]), target,
            });
        }

        match = text.match(/^SEQ_SAVE_OK\s+(\S+)\s+(\d+)(?:\s+(0|1))?/);
        if (match) socket.dispatch("upload_result", {
            ok: true, name: match[1], count: Number(match[2]), loop: match[3] !== "0",
        });
        match = text.match(/^SEQ_SAVE_ERR\s+(\d+)\s+(.*)/);
        if (match) socket.dispatch("upload_result", {
            ok: false, code: Number(match[1]), reason: match[2],
        });
        match = text.match(/^SEQ_LIST\s+(\d+)(.*)/);
        if (match) socket.dispatch("custom_gestures", {
            count: Number(match[1]), names: match[2].trim() ? match[2].trim().split(/\s+/) : [],
        });
        match = text.match(/^SEQ_DELETE_OK\s+(\S+)/);
        if (match) socket.dispatch("delete_result", { ok: true, name: match[1] });
        match = text.match(/^SEQ_DELETE_ERR\s+(\S+)\s+(.*)/);
        if (match) socket.dispatch("delete_result", { ok: false, name: match[1], reason: match[2] });
        match = text.match(/^SEQ_COUNT\s+(\d+)/);
        if (match) socket.dispatch("staging_count", { count: Number(match[1]) });

        socket.dispatch("console_line", {
            text, type: text.includes("ERR") ? "error" : "response",
            time: new Date().toLocaleTimeString([], { hour12: false }),
        });
    }

    window.MiraMobilePlatform = {
        socket,
        receive(json) {
            const message = JSON.parse(json);
            if (message.event === "line") {
                structuredLine(message.data.target, message.data.text);
            } else {
                socket.dispatch(message.event, message.data);
            }
        },
        connect(address) {
            window.MiraAndroid.connect(address);
        },
        disconnect(address) {
            window.MiraAndroid.disconnect(address);
        },
    };

    window.io = function () {
        setTimeout(() => {
            socket.dispatch("connect");
            socket.dispatch("device_type", { type: "robot" });
            window.MiraAndroid.start();
        }, 0);
        return socket;
    };

    const browserFetch = window.fetch.bind(window);
    window.fetch = async function (resource, options = {}) {
        const url = typeof resource === "string" ? resource : resource.url;
        if (!url.startsWith("/api/")) return browserFetch(resource, options);
        const payload = window.MiraAndroid.api(
            url,
            options.method || "GET",
            typeof options.body === "string" ? options.body : ""
        );
        const envelope = JSON.parse(payload);
        return {
            ok: envelope.status >= 200 && envelope.status < 300,
            status: envelope.status,
            async json() { return envelope.body; },
        };
    };
})();

package org.miraloma.mira;

import android.content.SharedPreferences;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;

public final class MiraWebBridge {
    private final MainActivity activity;
    private final WebView webView;
    private final MiraBleManager bleManager;
    private final SharedPreferences preferences;
    private volatile boolean pageReady;

    MiraWebBridge(MainActivity activity, WebView webView, MiraBleManager bleManager) {
        this.activity = activity;
        this.webView = webView;
        this.bleManager = bleManager;
        this.preferences = activity.getSharedPreferences("mira", 0);
        bleManager.setLineListener(this::sendLine);
        bleManager.setAliasLookup(this::aliasFor);
    }

    void setPageReady(boolean ready) {
        pageReady = ready;
    }

    @JavascriptInterface
    public void start() {
        activity.runOnUiThread(activity::ensureBluetoothPermissions);
    }

    @JavascriptInterface
    public void refreshState() {
        publishState();
    }

    @JavascriptInterface
    public void connect(String address) {
        bleManager.connect(address);
    }

    @JavascriptInterface
    public void disconnect(String address) {
        bleManager.disconnect(address);
    }

    @JavascriptInterface
    public void sendCommand(String target, String command) {
        bleManager.sendCommand(target, command);
    }

    @JavascriptInterface
    public String api(String rawPath, String method, String rawBody) {
        try {
            String path = rawPath.split("\\?", 2)[0];
            JSONObject body = rawBody == null || rawBody.isBlank() ? new JSONObject() : new JSONObject(rawBody);
            switch (path) {
                case "/api/ble/connect":
                    connect(body.optString("address"));
                    return envelope(200, new JSONObject().put("ok", true));
                case "/api/ble/disconnect":
                    disconnect(body.optString("address"));
                    return envelope(200, new JSONObject().put("ok", true));
                case "/api/robots/rename":
                    String id = body.optString("mac");
                    String name = body.optString("name").trim();
                    if (id.isEmpty() || name.isEmpty() || name.length() > 15) {
                        return envelope(400, new JSONObject().put("error", "Use a name from 1 to 15 characters."));
                    }
                    if (name.chars().anyMatch(value -> value < 0x20 || value > 0x7e)) {
                        return envelope(400, new JSONObject().put("error", "Use printable English characters."));
                    }
                    if (!bleManager.renameRobot(id, name)) {
                        return envelope(409, new JSONObject().put("error", "Robot is not connected."));
                    }
                    preferences.edit().putString("name." + id, name).apply();
                    publishState();
                    return envelope(200, new JSONObject().put("ok", true));
                case "/api/sequence/autosave":
                    preferences.edit().putString("sequence", rawBody).apply();
                    return envelope(200, new JSONObject().put("ok", true));
                case "/api/sequence/autoload":
                    return envelope(200, new JSONObject(preferences.getString("sequence", "{\"keyframes\":[]}")));
                case "/api/updates":
                    return envelope(200, new JSONObject()
                        .put("devices", new JSONArray())
                        .put("available", false)
                        .put("error", JSONObject.NULL)
                        .put("update", new JSONObject().put("state", "idle")));
                case "/api/updates/start":
                case "/api/devices/erase":
                    return envelope(409, new JSONObject().put(
                        "error", "Connect this board to Mira on macOS or Windows for firmware maintenance."
                    ));
                default:
                    return envelope(404, new JSONObject().put("error", "Unsupported mobile API"));
            }
        } catch (JSONException error) {
            return "{\"status\":400,\"body\":{\"error\":\"Invalid request\"}}";
        }
    }

    void publishState() {
        if (!pageReady) return;
        sendEvent("device_inventory", object("devices", bleManager.inventoryJson()));
        boolean connected = bleManager.connectedCount() > 0;
        sendEvent("serial_status", object("connected", connected));
        sendEvent("robot_list", bleManager.robotsJson());
    }

    void sendLine(String target, String text) {
        sendEvent("line", object("target", target, "text", text));
    }

    void sendConsole(String text, String type) {
        sendEvent("console_line", object(
            "text", text,
            "type", type,
            "time", LocalTime.now().format(DateTimeFormatter.ofPattern("HH:mm:ss"))
        ));
    }

    private String aliasFor(String id) {
        return preferences.getString("name." + id, id);
    }

    private String envelope(int status, JSONObject body) {
        return object("status", status, "body", body).toString();
    }

    private void sendEvent(String event, Object data) {
        if (!pageReady) return;
        JSONObject message = object("event", event, "data", data);
        String quoted = JSONObject.quote(message.toString());
        activity.runOnUiThread(() -> webView.evaluateJavascript(
            "window.MiraMobilePlatform&&window.MiraMobilePlatform.receive(" + quoted + ")", null
        ));
    }

    private static JSONObject object(Object... pairs) {
        JSONObject result = new JSONObject();
        for (int index = 0; index + 1 < pairs.length; index += 2) {
            try { result.put(String.valueOf(pairs[index]), pairs[index + 1]); }
            catch (JSONException ignored) {}
        }
        return result;
    }
}

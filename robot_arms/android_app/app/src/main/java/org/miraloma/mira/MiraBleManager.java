package org.miraloma.mira;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;

final class MiraBleManager {
    static final UUID SERVICE_UUID = UUID.fromString("7f510001-1b15-4f8e-9f5d-6f6d69726100");
    static final UUID COMMAND_UUID = UUID.fromString("7f510002-1b15-4f8e-9f5d-6f6d69726100");
    static final UUID RESPONSE_UUID = UUID.fromString("7f510003-1b15-4f8e-9f5d-6f6d69726100");
    static final UUID DEVICE_INFO_UUID = UUID.fromString("7f510004-1b15-4f8e-9f5d-6f6d69726100");
    private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    interface LineListener { void onLine(String target, String line); }

    private final MainActivity activity;
    private final Runnable stateChanged;
    private final BluetoothAdapter adapter;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Map<String, NearbyDevice> nearby = new LinkedHashMap<>();
    private final Map<String, GattSession> sessions = new LinkedHashMap<>();
    private BluetoothLeScanner scanner;
    private boolean scanning;
    private boolean statePublishPending;
    private LineListener lineListener;
    private Function<String, String> aliasLookup = id -> id;

    MiraBleManager(MainActivity activity, Runnable stateChanged) {
        this.activity = activity;
        this.stateChanged = stateChanged;
        BluetoothManager manager = (BluetoothManager) activity.getSystemService(Context.BLUETOOTH_SERVICE);
        this.adapter = manager == null ? null : manager.getAdapter();
    }

    void setLineListener(LineListener listener) { this.lineListener = listener; }
    void setAliasLookup(Function<String, String> lookup) { this.aliasLookup = lookup; }

    @SuppressLint("MissingPermission")
    void startScanning() {
        if (adapter == null || !adapter.isEnabled()) return;
        if (scanning) return;
        scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) return;
        ScanFilter filter = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SERVICE_UUID)).build();
        ScanSettings settings = new ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build();
        scanner.startScan(List.of(filter), settings, scanCallback);
        scanning = true;
    }

    @SuppressLint("MissingPermission")
    void connect(String address) {
        NearbyDevice device;
        synchronized (this) { device = nearby.get(address); }
        if (device == null || sessions.containsKey(address)) return;
        device.state = "connecting";
        scheduleStatePublish();
        BluetoothGatt gatt = device.result.getDevice().connectGatt(
            activity, false, new GattCallbacks(address), BluetoothDevice.TRANSPORT_LE
        );
        synchronized (this) { sessions.put(address, new GattSession(address, gatt)); }
    }

    @SuppressLint("MissingPermission")
    void disconnect(String address) {
        GattSession session;
        synchronized (this) { session = sessions.get(address); }
        if (session != null) session.gatt.disconnect();
    }

    void sendCommand(String target, String command) {
        if (command == null || command.isBlank()) return;
        List<GattSession> selected = new ArrayList<>();
        synchronized (this) {
            for (GattSession session : sessions.values()) {
                if (!session.ready) continue;
                String alias = displayName(session);
                if ("all".equals(target) || target.equalsIgnoreCase(session.robotId) || target.equals(alias)) {
                    selected.add(session);
                }
            }
        }
        for (GattSession session : selected) session.enqueue(command);
    }

    synchronized boolean renameRobot(String robotId, String name) {
        for (GattSession session : sessions.values()) {
            if (session.ready && robotId.equalsIgnoreCase(session.robotId)) {
                session.robotName = name;
                session.enqueue("name set " + name);
                scheduleStatePublish();
                return true;
            }
        }
        return false;
    }

    private String displayName(GattSession session) {
        if (session.robotName != null && !session.robotName.isBlank()) return session.robotName;
        return aliasLookup.apply(session.robotId);
    }

    synchronized int connectedCount() {
        int count = 0;
        for (GattSession session : sessions.values()) if (session.ready) count++;
        return count;
    }

    synchronized JSONArray inventoryJson() {
        JSONArray result = new JSONArray();
        for (NearbyDevice device : nearby.values()) {
            GattSession session = sessions.get(device.address);
            JSONObject item = new JSONObject();
            put(item, "port", "ble:" + device.address);
            put(item, "address", device.address);
            put(item, "name", session != null && session.ready ? displayName(session) : device.name);
            put(item, "state", session != null && session.ready ? "connected" : device.state);
            put(item, "role", "robot");
            put(item, "deviceId", session != null && session.ready ? session.robotId : JSONObject.NULL);
            put(item, "firmware", session != null && session.ready ? session.firmware : JSONObject.NULL);
            put(item, "protocol", session != null && session.ready ? session.protocol : JSONObject.NULL);
            put(item, "legacy", false);
            put(item, "transport", "ble");
            put(item, "rssi", device.rssi);
            result.put(item);
        }
        return result;
    }

    synchronized JSONArray robotsJson() {
        JSONArray result = new JSONArray();
        for (GattSession session : sessions.values()) {
            if (!session.ready) continue;
            JSONObject robot = new JSONObject();
            String alias = displayName(session);
            put(robot, "name", alias);
            put(robot, "masterName", session.robotId);
            put(robot, "mac", session.robotId);
            put(robot, "online", true);
            put(robot, "firmware", session.firmware);
            put(robot, "legacy", false);
            put(robot, "connection", "Bluetooth");
            result.put(robot);
        }
        return result;
    }

    @SuppressLint("MissingPermission")
    void shutdown() {
        if (scanner != null && scanning) scanner.stopScan(scanCallback);
        scanning = false;
        List<GattSession> copy;
        synchronized (this) { copy = new ArrayList<>(sessions.values()); }
        for (GattSession session : copy) {
            try { session.gatt.disconnect(); } catch (Exception ignored) {}
            session.gatt.close();
        }
        synchronized (this) { sessions.clear(); }
    }

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            recordResult(result);
        }

        @Override
        public void onBatchScanResults(List<ScanResult> results) {
            for (ScanResult result : results) recordResult(result);
        }
    };

    @SuppressLint("MissingPermission")
    private void recordResult(ScanResult result) {
        String address = result.getDevice().getAddress();
        String name = result.getDevice().getName();
        if (name == null && result.getScanRecord() != null) name = result.getScanRecord().getDeviceName();
        if (name == null) name = "Mira robot";
        synchronized (this) {
            NearbyDevice existing = nearby.get(address);
            if (existing == null) nearby.put(address, new NearbyDevice(address, name, result));
            else {
                existing.name = name;
                existing.result = result;
                existing.rssi = result.getRssi();
            }
        }
        scheduleStatePublish();
    }

    private void scheduleStatePublish() {
        synchronized (this) {
            if (statePublishPending) return;
            statePublishPending = true;
        }
        mainHandler.postDelayed(() -> {
            synchronized (MiraBleManager.this) { statePublishPending = false; }
            stateChanged.run();
        }, 250);
    }

    @SuppressLint("MissingPermission")
    private void discover(GattSession session) {
        if (session.discovering) return;
        session.discovering = true;
        session.gatt.discoverServices();
    }

    private void parseMetadata(GattSession session, byte[] value) {
        String metadata = new String(value, StandardCharsets.UTF_8);
        for (String token : metadata.split("\\s+")) {
            String[] pair = token.split("=", 2);
            if (pair.length != 2) continue;
            switch (pair[0]) {
                case "id": session.robotId = pair[1].toUpperCase(); break;
                case "firmware": session.firmware = pair[1]; break;
                case "name": session.robotName = Uri.decode(pair[1]); break;
                case "protocol":
                    try { session.protocol = Integer.parseInt(pair[1]); } catch (NumberFormatException ignored) {}
                    break;
            }
        }
        if (session.robotId == null || session.protocol < 2) {
            failSession(session.address, "This robot needs the BLE-capable Mira firmware.");
            return;
        }
        session.ready = true;
        String legacyName = aliasLookup.apply(session.robotId);
        if ((session.robotName == null || session.robotName.isBlank()) &&
                session.protocol >= 3 && !legacyName.equals(session.robotId)) {
            session.robotName = legacyName;
            session.enqueue("name set " + legacyName);
        }
        NearbyDevice device;
        synchronized (this) { device = nearby.get(session.address); }
        if (device != null) device.state = "connected";
        scheduleStatePublish();
    }

    private void receive(GattSession session, byte[] value) {
        session.responseBuffer.append(new String(value, StandardCharsets.UTF_8));
        int newline;
        while ((newline = session.responseBuffer.indexOf("\n")) >= 0) {
            String line = session.responseBuffer.substring(0, newline).replace("\r", "");
            session.responseBuffer.delete(0, newline + 1);
            if (!line.isEmpty() && lineListener != null) lineListener.onLine(session.robotId, line);
        }
    }

    @SuppressLint("MissingPermission")
    private void failSession(String address, String message) {
        GattSession session;
        synchronized (this) { session = sessions.remove(address); }
        if (session != null) {
            try { session.gatt.disconnect(); } catch (Exception ignored) {}
            session.gatt.close();
        }
        NearbyDevice device;
        synchronized (this) { device = nearby.get(address); }
        if (device != null) device.state = "available";
        if (lineListener != null) lineListener.onLine(address, message);
        scheduleStatePublish();
    }

    private final class GattCallbacks extends BluetoothGattCallback {
        private final String address;
        GattCallbacks(String address) { this.address = address; }

        @Override
        @SuppressLint("MissingPermission")
        public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH);
                if (!gatt.requestMtu(247)) discover(session);
                mainHandler.postDelayed(() -> discover(session), 600);
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                gatt.close();
                synchronized (MiraBleManager.this) { sessions.remove(address); }
                NearbyDevice device;
                synchronized (MiraBleManager.this) { device = nearby.get(address); }
                if (device != null) device.state = "available";
                scheduleStatePublish();
            }
        }

        @Override
        public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (session != null) discover(session);
        }

        @Override
        @SuppressLint("MissingPermission")
        public void onServicesDiscovered(BluetoothGatt gatt, int status) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (session == null || status != BluetoothGatt.GATT_SUCCESS) {
                failSession(address, "Mira Bluetooth service discovery failed.");
                return;
            }
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            if (service == null) {
                failSession(address, "This Bluetooth device is not a Mira robot.");
                return;
            }
            session.command = service.getCharacteristic(COMMAND_UUID);
            session.response = service.getCharacteristic(RESPONSE_UUID);
            session.info = service.getCharacteristic(DEVICE_INFO_UUID);
            if (session.command == null || session.response == null || session.info == null) {
                failSession(address, "The robot's Bluetooth service is incomplete.");
                return;
            }
            gatt.setCharacteristicNotification(session.response, true);
            BluetoothGattDescriptor cccd = session.response.getDescriptor(CCCD_UUID);
            if (cccd != null) {
                if (Build.VERSION.SDK_INT >= 33) {
                    gatt.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                } else {
                    cccd.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                    gatt.writeDescriptor(cccd);
                }
            } else {
                gatt.readCharacteristic(session.info);
            }
        }

        @Override
        @SuppressLint("MissingPermission")
        public void onDescriptorWrite(BluetoothGatt gatt, BluetoothGattDescriptor descriptor, int status) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (session == null) return;
            if (status == BluetoothGatt.GATT_SUCCESS) {
                gatt.readCharacteristic(session.info);
            } else {
                failSession(address, "Mira could not enable Bluetooth responses.");
            }
        }

        @Override
        public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value, int status) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (session != null && status == BluetoothGatt.GATT_SUCCESS && DEVICE_INFO_UUID.equals(characteristic.getUuid())) {
                parseMetadata(session, value);
            } else if (session != null && DEVICE_INFO_UUID.equals(characteristic.getUuid())) {
                failSession(address, "Mira could not read the robot identity.");
            }
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            onCharacteristicRead(gatt, characteristic, characteristic.getValue(), status);
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (session != null && RESPONSE_UUID.equals(characteristic.getUuid())) receive(session, value);
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic) {
            onCharacteristicChanged(gatt, characteristic, characteristic.getValue());
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            GattSession session;
            synchronized (MiraBleManager.this) { session = sessions.get(address); }
            if (session != null) session.writeFinished();
        }
    }

    private static final class NearbyDevice {
        final String address;
        String name;
        ScanResult result;
        int rssi;
        String state = "available";

        NearbyDevice(String address, String name, ScanResult result) {
            this.address = address;
            this.name = name;
            this.result = result;
            this.rssi = result.getRssi();
        }
    }

    private final class GattSession {
        final String address;
        final BluetoothGatt gatt;
        final ArrayDeque<byte[]> writes = new ArrayDeque<>();
        final StringBuilder responseBuffer = new StringBuilder();
        BluetoothGattCharacteristic command;
        BluetoothGattCharacteristic response;
        BluetoothGattCharacteristic info;
        String robotId;
        String firmware;
        String robotName;
        int protocol;
        boolean ready;
        boolean discovering;
        boolean writing;

        GattSession(String address, BluetoothGatt gatt) {
            this.address = address;
            this.gatt = gatt;
        }

        synchronized void enqueue(String text) {
            byte[] value = text.getBytes(StandardCharsets.UTF_8);
            if (value.length > 240) return;
            if ("stop".equals(text)) writes.clear();
            // Live tracking values supersede an older unsent live target.
            if (text.startsWith("track ") && !writes.isEmpty()) writes.removeLast();
            writes.add(value);
            writeNext();
        }

        @SuppressLint("MissingPermission")
        @SuppressWarnings("deprecation")
        private synchronized void writeNext() {
            if (writing || command == null || writes.isEmpty()) return;
            byte[] value = writes.removeFirst();
            writing = true;
            int result;
            if (Build.VERSION.SDK_INT >= 33) {
                result = gatt.writeCharacteristic(command, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            } else {
                command.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                command.setValue(value);
                result = gatt.writeCharacteristic(command) ? 0 : -1;
            }
            if (result != 0) {
                writing = false;
                mainHandler.postDelayed(this::writeNext, 25);
            }
        }

        synchronized void writeFinished() {
            writing = false;
            writeNext();
        }
    }

    private static void put(JSONObject object, String key, Object value) {
        try { object.put(key, value); } catch (Exception ignored) {}
    }
}

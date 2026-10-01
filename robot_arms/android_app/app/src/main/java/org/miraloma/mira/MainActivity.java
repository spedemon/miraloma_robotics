package org.miraloma.mira;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.graphics.Color;
import android.view.WindowInsets;
import android.webkit.MimeTypeMap;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

public final class MainActivity extends Activity {
    private static final int BLUETOOTH_PERMISSION_REQUEST = 41;
    private WebView webView;
    private MiraBleManager bleManager;
    private MiraWebBridge bridge;
    private int safeTopPx;
    private int safeRightPx;
    private int safeBottomPx;
    private int safeLeftPx;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        webView = new WebView(this);
        setContentView(webView);

        // Android 15 enforces edge-to-edge for targetSdk 35. Keep the background
        // immersive while publishing the untouchable system-bar/cutout area to
        // the web shell so controls never sit under the camera or navigation UI.
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.TRANSPARENT);
        webView.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                android.graphics.Insets safe = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                safeTopPx = safe.top;
                safeRightPx = safe.right;
                safeBottomPx = safe.bottom;
                safeLeftPx = safe.left;
            } else {
                safeTopPx = insets.getStableInsetTop();
                safeRightPx = insets.getStableInsetRight();
                safeBottomPx = insets.getStableInsetBottom();
                safeLeftPx = insets.getStableInsetLeft();
            }
            publishSafeArea();
            return insets;
        });
        webView.requestApplyInsets();

        bleManager = new MiraBleManager(this, this::publishState);
        bridge = new MiraWebBridge(this, webView, bleManager);
        configureWebView();
        webView.addJavascriptInterface(bridge, "MiraAndroid");
        webView.loadUrl("https://appassets.androidplatform.net/static/index.html");
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMediaPlaybackRequiresUserGesture(true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (!"appassets.androidplatform.net".equals(uri.getHost())) return null;
                String path = uri.getPath();
                if (path == null || !path.startsWith("/static/")) return null;
                String assetPath = path.substring(1);
                try {
                    InputStream input = getAssets().open(assetPath);
                    String extension = MimeTypeMap.getFileExtensionFromUrl(path);
                    String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
                    if (mime == null) mime = "application/octet-stream";
                    return new WebResourceResponse(mime, "UTF-8", input);
                } catch (IOException ignored) {
                    return null;
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("appassets.androidplatform.net".equals(uri.getHost())) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                bridge.setPageReady(true);
                publishSafeArea();
                publishState();
            }
        });
    }

    private void publishSafeArea() {
        if (webView == null) return;
        float density = getResources().getDisplayMetrics().density;
        float top = safeTopPx / density;
        float right = safeRightPx / density;
        float bottom = safeBottomPx / density;
        float left = safeLeftPx / density;
        String script = String.format(java.util.Locale.US,
                "document.documentElement.style.setProperty('--android-safe-top','%.2fpx');" +
                "document.documentElement.style.setProperty('--android-safe-right','%.2fpx');" +
                "document.documentElement.style.setProperty('--android-safe-bottom','%.2fpx');" +
                "document.documentElement.style.setProperty('--android-safe-left','%.2fpx');",
                top, right, bottom, left);
        webView.post(() -> webView.evaluateJavascript(script, null));
    }

    public void ensureBluetoothPermissions() {
        List<String> missing = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.BLUETOOTH_SCAN);
            }
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.BLUETOOTH_CONNECT);
            }
        } else if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            missing.add(Manifest.permission.ACCESS_FINE_LOCATION);
        }
        if (missing.isEmpty()) {
            bleManager.startScanning();
        } else {
            requestPermissions(missing.toArray(new String[0]), BLUETOOTH_PERMISSION_REQUEST);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != BLUETOOTH_PERMISSION_REQUEST) return;
        for (int result : grantResults) {
            if (result != PackageManager.PERMISSION_GRANTED) {
                bridge.sendConsole("Bluetooth permission is required to find Mira robots.", "error");
                return;
            }
        }
        bleManager.startScanning();
    }

    private void publishState() {
        if (bridge != null) bridge.publishState();
    }

    @Override
    protected void onDestroy() {
        bleManager.shutdown();
        webView.removeJavascriptInterface("MiraAndroid");
        webView.destroy();
        super.onDestroy();
    }
}

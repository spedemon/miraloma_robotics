# Mira's native bridge methods are invoked by Android WebView JavaScript.
-keepclassmembers class org.miraloma.mira.MiraWebBridge {
    @android.webkit.JavascriptInterface <methods>;
}

# Keep the JavaScript bridge interface used by the offscreen WebView engine.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class com.antigravity.noveldownloader.** {
    kotlinx.serialization.KSerializer serializer(...);
}

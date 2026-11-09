#!/bin/bash
# Re-download the exact AOSP 9 files the reports cite, and verify their SHA-256 against
# reports/AOSP9_SOURCE_PROVENANCE.md.
# NOTE: only this endpoint form works here; directory listings and +archive tarballs 404. A
# missing file is fetched as an empty body and deleted by the size test below, so a FAIL line means
# the path is wrong for this tag - check the path in the browser before editing it.
BASE=https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-9.0.0_r35
declare -A P=(
 [SystemImpl.java]=services/core/java/com/android/server/webkit/SystemImpl.java
 [SystemInterface.java]=services/core/java/com/android/server/webkit/SystemInterface.java
 [WebViewUpdater.java]=services/core/java/com/android/server/webkit/WebViewUpdater.java
 [WebViewUpdateService.java]=services/core/java/com/android/server/webkit/WebViewUpdateService.java
 [WebViewUpdateServiceImpl.java]=services/core/java/com/android/server/webkit/WebViewUpdateServiceImpl.java
 [WebViewProviderInfo.java]=services/core/java/com/android/server/webkit/WebViewProviderInfo.java
 [WebViewLibraryLoader.java]=services/core/java/com/android/server/webkit/WebViewLibraryLoader.java
 [WebViewFactory.java]=core/java/android/webkit/WebViewFactory.java
 [UserPackage.java]=core/java/android/webkit/UserPackage.java
 [NativeLibraryHelper.java]=services/core/java/com/android/server/pm/NativeLibraryHelper.java
 [PackageManagerService.java]=services/core/java/com/android/server/pm/PackageManagerService.java
 [PackageParser.java]=services/core/java/com/android/server/pm/PackageParser.java
 [ApplicationInfo.java]=core/java/android/content/pm/ApplicationInfo.java
 [config_webview_packages.xml]=core/res/res/xml/config_webview_packages.xml
 [core_res_AndroidManifest.xml]=core/res/AndroidManifest.xml
 [config.xml]=core/res/res/values/config.xml
)
for f in "${!P[@]}"; do
  curl -s "$BASE/${P[$f]}?format=TEXT" | base64 -d > "$f" 2>/dev/null
  s=$(wc -c < "$f")
  if [ "$s" -lt 40 ]; then echo "FAIL  $f  (${P[$f]})"; rm -f "$f"; else printf "ok    %-34s %8d B\n" "$f" "$s"; fi
done

#!/system/bin/sh
# GUEST_DIAGNOSTICS.sh — run INSIDE the Virtual Master Android 9 guest.
# Read-only. Nothing here modifies the guest.
# Purpose: settle the two open questions that cannot be answered from the
# encrypted ROM package: (1) does the guest support 32-bit ARM, and
# (2) how is the WebView provider list actually configured in this ROM.
#
# STATUS 2026-11-04: SUPERSEDED for deployment decisions by tools/guest_probe.sh, which answers the
# same ABI/provider questions plus the overlay-directory, mount-state, idmap and resource-cache
# questions, and prints machine-readable PROBE_* verdict lines. This script is still the deeper
# 32-bit-linker check, so it is kept rather than deleted; run one or the other, not both.

echo "##### 1. ABI SUPPORT (blocker B1) #####"
echo "-- ro.product.cpu.* --"
getprop | grep -E 'ro\.product\.cpu|ro\.dalvik|ro\.zimage|persist\.dalvik'
echo
echo "abilist      = $(getprop ro.product.cpu.abilist)"
echo "abilist32    = '$(getprop ro.product.cpu.abilist32)'   <-- EMPTY means NO 32-bit support"
echo "abilist64    = $(getprop ro.product.cpu.abilist64)"
echo "abi          = $(getprop ro.product.cpu.abi)"
echo
echo "-- is a 32-bit bionic linker present? --"
ls -l /system/bin/linker /system/bin/linker64 2>&1
echo "-- 32-bit vs 64-bit library directories --"
ls -d /system/lib /system/lib64 /vendor/lib /vendor/lib64 /system/product/lib* 2>&1
echo "count /system/lib  : $(ls /system/lib  2>/dev/null | wc -l)"
echo "count /system/lib64: $(ls /system/lib64 2>/dev/null | wc -l)"
echo
echo "-- ABI actually recorded for the preinstalled WebView --"
dumpsys package com.android.webview | grep -iE 'CpuAbi|abi|versionName|versionCode|codePath|flags|installerPackageName'
echo
echo "-- which ABIs can this device load, per zygote --"
ls -l /system/bin/app_process32 /system/bin/app_process64 2>&1
getprop ro.zygote

echo "##### 2. EXISTING WEBVIEW FILES (Phase 2 items 1-9) #####"
ls -lZ /system/app/webview/ 2>&1
ls -lZ /system/app/webview/oat/*/ 2>&1
echo "-- ABIs inside the shipped WebView 81 APK --"
unzip -l /system/app/webview/webview.apk 2>/dev/null | grep -E 'lib/|\.so$' | head
echo "-- primaryCpuAbi tells you which ABI the ROM shipped for webview --"

echo "##### 3. PROVIDER CONFIGURATION (Phase 2 items 10-13, Phase 3) #####"
echo "-- current provider state as the framework sees it --"
dumpsys webviewupdate
echo
echo "-- developer-options relevant props --"
getprop | grep -i webview
echo "-- is com.google.android.webview known to PMS at all? --"
pm list packages | grep -iE 'webview|trichrome|chromium'
echo
echo "-- framework-res location and size (we need this file to answer B3) --"
ls -l /system/framework/framework-res.apk 2>&1
ls -l /system/framework/*.apk 2>/dev/null | head -30

echo "##### 4. PARTITION SPACE (can a 87-222 MB APK even fit?) #####"
df -h /system /vendor /product 2>&1
mount | grep -E ' /system| /vendor| /product'
echo "-- filesystem type + size of the mounted system --"
blockdev --getsize64 $(mount | awk '/\/system /{print $1}') 2>/dev/null

echo "##### 5. SIGNING KEY IDENTITY OF THIS ROM (decides blocker B3 / L4) #####"
echo "If the ROM is signed with the public AOSP test keys, framework-res can be"
echo "legitimately re-signed locally. Extract these files and check their signer:"
echo "  /system/framework/framework-res.apk"
echo "  /system/app/webview/webview.apk"
echo "Pull them out of the guest and we can compare the certificate against the"
echo "well-known AOSP 'platform' / 'testkey' certificates."
echo "-- reference answer to compare against (AOSP public test 'platform' key) --"
echo "   SHA-1   27196E386B875E76ADF700E7EA84E4C6EEE33DFA"
echo "   SHA-256 C8A2E9BCCF597C2FB6DC66BEE293FC13F2FC47EC77BC6B2B0D52C11F51192AB8"
echo "-- do these two packages share the signature group of 'android'? --"
dumpsys package android | grep -iE 'sharedUser|signatures|codePath|flags' | head
echo "-- the real provider config, as the running framework sees it (READ-ONLY) --"
echo "   This prints the parsed WebViewProviderInfo list: package names, descriptions,"
echo "   availableByDefault, isFallback and any signatures. If com.google.android.webview"
echo "   is absent here, no APK placement can make it selectable."
dumpsys webviewupdate

echo "##### 6. OPTIONAL DECISIVE ABI TEST #####"
echo "adb install the supplied armeabi-v7a-only APK into the guest:"
echo "  adb install -r webview138.apk"
echo "  expect 'INSTALL_FAILED_NO_MATCHING_ABIS (failed to extract native libs / no"
echo "  matching ABI)' if the guest is arm64-only, which is a direct confirmation."
echo "Then try the arm64-containing build (webview138_arm64_universal_138.0.7204.179.apk);"
echo "if that installs, the correct artefact family for this guest is confirmed."

echo "##### 7. BUILD TYPE + VERITY (decides whether /system is writable at all) #####"
getprop ro.build.type        # user vs userdebug/eng  <-- 'eng'/'userdebug' also disables WebView signature+version gates
getprop ro.debuggable
getprop ro.secure
getprop ro.adb.secure
getprop persist.sys.usb.config
echo "-- verity / dm-verity state --"
getprop | grep -iE 'verity|avb|dm.'
mount | grep -i verity
echo "-- can /system be remounted rw? (dry run; do NOT if you want to keep it pristine) --"
grep -E ' /system ' /proc/mounts

echo "##### 8. PROVIDER-SELECTION STATE (from the AOSP 9 source read this session) #####"
echo "-- Settings.Global.WEBVIEW_PROVIDER: the key Developer Options writes. If empty, the"
echo "   framework picks the FIRST valid entry with availableByDefault in XML document order"
echo "   (WebViewUpdater.java:285-315), i.e. today com.android.webview."
settings get global webview_provider
echo "-- the service's own shell interface exists on Android 9"
echo "   (WebViewUpdateService.java:149-152 wires WebViewUpdateServiceShellCommand) --"
cmd webviewupdate get-webview-packages 2>&1 | head -40
echo "-- gate 2 (minimum version code) and gate 3 (signature) are SKIPPED when"
echo "   Build.IS_DEBUGGABLE is true; ro.build.type userdebug/eng means SystemImpl.java:263-266"
echo "   returns true, which changes the whole plan, not just confirms it --"
echo "ro.build.type = $(getprop ro.build.type)   ro.debuggable = $(getprop ro.debuggable)"
echo "-- gate 4: meta-data key the loader reads (WebViewFactory.java:159-161). Should print"
echo "   libwebviewchromium.so for any candidate provider APK. --"
echo "-- relro plumbing (non-fatal if absent, but shows whether the loader dir is usable) --"
ls -lZ /data/misc/shared_relro/ 2>&1
echo "-- is the isolated WebViewLoader present for each ABI on this build? --"
ls -l /system/bin/WebViewLoader-* /system/bin/app_process* 2>&1
echo "-- stale AOT for the old WebView 81 provider (L6 risk: regeneration / stale oat) --"
ls -lR /system/app/webview/oat 2>&1
ls -l /data/dalvik-cache/*/ 2>/dev/null | grep -i webview
echo "-- does the guest have a zip reader we could use to inspect framework-res in place? --"
for b in unzip aapt aapt2 apksigner openssl python3 toybox busybox; do
  printf '%-10s %s\n' "$b" "$(command -v $b || echo MISSING)"
done
echo
echo "##### 9. PULL THE TWO DECISIVE FILES OUT OF THE GUEST (run on the adb host) #####"
cat <<'PULL'
  adb pull /system/framework/framework-res.apk .
  adb pull /system/app/webview/webview.apk .
  # then, on this machine, we compare each signer against the AOSP public test key
  # (work/aosp_platform_test_cert.pem) and, for framework-res, dump
  # res/xml/config_webview_packages.xml to see the real provider grammar of THIS ROM.
PULL
echo "END OF READ-ONLY DIAGNOSTICS — nothing in this script modifies the guest."

#!/system/bin/sh
# service.sh - runs as root once per boot, AFTER boot_completed.
#
# Why a boot script exists at all (the user asked for scripts only when actually required): the RRO
# does the registering by itself, but ONE piece of Android 9 state can silently overrule it -
# Settings.Global.WEBVIEW_PROVIDER. Source, android-9.0.0_r35:
#   Settings.java:9425            WEBVIEW_PROVIDER = "webview_provider"
#   Settings.java:9421-9422       "Name of the package used as WebView provider (if unset the
#                                 provider is instead determined by the system)."
#   WebViewUpdater.java:287-301   findPreferredWebViewPackage() returns the user-chosen package if it
#                                 is valid, BEFORE it ever looks at document order (:306-316).
# So if somebody once picked com.android.webview in Developer options, the RRO alone would NOT change
# the provider. That is the only case this script touches, and it is reversible: uninstall.sh puts
# the old value back.
#
# Everything else here is READ-ONLY diagnostics written to one log file inside the module directory.
# This script never kills, disables, uninstalls, mounts, reboots, or writes outside $MODPATH.

MODDIR=$(dirname "$0")
: "${MODPATH:=$MODDIR}"
LOG="$MODPATH/boot-verify.log"
GPKG=com.google.android.webview
: "${VDIR:=/vendor/overlay}"
: "${PDIR:=/product/overlay}"
OVERLAY=$(sed -n 's/^overlay_file=//p' "$MODPATH/webview138.manifest" 2>/dev/null | head -1)
PATH=/system/bin:/system/xbin:/vendor/bin:/sbin:$PATH
# Android's own pm/settings/dumpsys first - that is what runs on a device. QODER_SHIM exists ONLY so
# tools/selftest_magisk.py can exercise these branches without touching a real framework; unset means
# inert, and it is never set on a guest.
if [ -n "${QODER_SHIM:-}" ]; then PATH="$QODER_SHIM:$PATH"; fi
export PATH

# keep the log from growing without bound across reboots
if [ -f "$LOG" ]; then
    sz=$(wc -c < "$LOG" 2>/dev/null | tr -d ' ')
    [ "${sz:-0}" -gt 65536 ] && mv -f "$LOG" "$LOG.old"
fi

{
echo "===== service.sh $(date -u '+%Y-%m-%dT%H:%M:%SZ') sdk=$(getprop ro.build.version.sdk) ====="

# 1. did Magisk's magic mount actually present the overlay before PackageManagerService scanned?
found=""
for d in "$VDIR" "$PDIR"; do
    if [ -f "$d/$OVERLAY" ]; then found="$d/$OVERLAY"; fi
done
if [ -n "$found" ]; then
    echo "OVERLAY MOUNTED: $found"
    ls -Z "$found" 2>/dev/null || ls -l "$found" 2>/dev/null
else
    echo "OVERLAY NOT MOUNTED: $OVERLAY is in neither $VDIR nor $PDIR."
    echo "  -> the provider list was NOT overlaid; WebView stays on the ROM default."
    echo "  -> check that Magisk is enabled and that this module is not disabled:"
    echo "     ls -l /data/adb/modules/webview138-replacement/disabled"
fi

# 2. is the replacement package there, and which version?
if pm list packages "$GPKG" 2>/dev/null | grep -q .; then
    ver=$(dumpsys package "$GPKG" 2>/dev/null | sed -n 's/.*versionName=//p' | head -1)
    echo "PACKAGE INSTALLED: $GPKG versionName=$ver"
else
    echo "PACKAGE NOT INSTALLED: $GPKG - the RRO lists a provider that is not present, so Android"
    echo "  keeps the factory one. Install it once with either:"
    echo "    su -c 'pm install -r /data/local/tmp/webview138.apk'      (recommended, you watch it happen)"
    echo "    touch $MODPATH/auto-install                                (this script does it next boot)"
    # Opt-in only: with no auto-install file this script NEVER installs anything. When the user creates
    # it, the bytes are checked against the measured identity of the package this module was built for
    # before pm is asked to touch the system, and a mismatch is refused rather than installed.
    if [ -f "$MODPATH/auto-install" ]; then
        AP=$(head -1 "$MODPATH/auto-install" 2>/dev/null)
        [ -n "$AP" ] || AP=input/webview138_arm64_universal_138.0.7204.179.apk
        PROP="$MODPATH/webview138-apk.prop"
        want=$(sed -n 's/^webview_apk_sha256=//p' "$PROP" 2>/dev/null | head -1)
        echo "  auto-install requested, source: $AP"
        if [ ! -f "$AP" ]; then
            echo "  REFUSED: $AP does not exist. Push the APK to the device first; nothing was installed."
        elif [ -z "$want" ] || ! command -v sha256sum >/dev/null 2>&1; then
            echo "  REFUSED: cannot verify the bytes here, so this script will not install blind."
        else
            got=$(sha256sum "$AP" | cut -d' ' -f1)
            if [ "$got" != "$want" ]; then
                echo "  REFUSED: sha256 $got is not the 138 package this module was built for ($want)."
                echo "  A provider whose <signature> the overlay names must be the package that carries it."
            else
                echo "  bytes verified ($got); running pm install -r"
                pm install -r "$AP" 2>&1 | sed 's/^/    pm: /'
                rc=$?
                if [ $rc -eq 0 ] && pm list packages "$GPKG" 2>/dev/null | grep -q .; then
                    echo "  installed. The provider list already names it; it becomes the provider at the"
                    echo "  next boot without waiting for anything else in this module."
                else
                    echo "  pm install returned rc=$rc and the package still does not list as installed."
                    echo "  Nothing was forced; WebView 81 remains the provider and works."
                fi
            fi
        fi
    fi
fi

# 3. what does the framework think the provider is right now? (root-only; needs DUMP permission)
dumpsys webviewupdate 2>/dev/null | grep -E 'Current WebView package|Minimum WebView version|Fallback logic|Preferred WebView package' | sed 's/^/  /'
echo "  provider dirs as the framework scans them:"
for d in "$VDIR" "$PDIR"; do
    [ -d "$d" ] && echo "    $d: $(ls "$d" 2>/dev/null | grep -c '\.apk$') apk(s)"
done

# 4. the one corrective write, and only in the overruled-by-user-choice case.
cur=$(settings get global webview_provider 2>/dev/null)
case "$cur" in
    null|"")
        echo "PREFERENCE: webview_provider unset -> document order decides -> $GPKG is first." ;;
    "$GPKG")
        echo "PREFERENCE: webview_provider already $GPKG." ;;
    *)
        if [ -f "$MODPATH/no-pin" ]; then
            echo "PREFERENCE: webview_provider=$cur (NOT Google). Pinning skipped because $MODPATH/no-pin exists."
        elif pm list packages "$GPKG" 2>/dev/null | grep -q .; then
            [ -f "$MODPATH/pref-backup" ] || printf '%s' "$cur" > "$MODPATH/pref-backup"
            settings put global webview_provider "$GPKG" 2>/dev/null
            now=$(settings get global webview_provider 2>/dev/null)
            if [ "$now" = "$GPKG" ]; then
                echo "PREFERENCE: was '$cur', backed up to $MODPATH/pref-backup, now pinned to $GPKG."
            else
                echo "PREFERENCE: FAILED to set webview_provider (still '$now'). The old value '$cur' is"
                echo "  saved in $MODPATH/pref-backup and was NOT modified."
            fi
        else
            echo "PREFERENCE: webview_provider=$cur but $GPKG is not installed; left alone."
        fi ;;
esac
echo "===== end ====="
} >> "$LOG" 2>&1
exit 0

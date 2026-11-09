#!/system/bin/sh
# uninstall.sh - runs as root from inside the module directory, just before Magisk deletes it.
#
# Rollback of everything this module is capable of changing:
#   * the RRO: Magisk deletes the module directory, so the bind mount vanishes and /vendor/overlay
#     reverts to the real, read-only partition contents at the next boot. The framework's own
#     config_webview_packages.xml (inside the signed framework-res.apk) becomes authoritative again
#     -> the factory provider com.android.webview 81 is selected. There is nothing for us to delete
#     to achieve that, which is exactly why this script deletes nothing outside $MODPATH.
#   * the preference this module may have pinned: restored from pref-backup.
#   * WebView 138 itself: INTENTIONALLY LEFT INSTALLED. It is an ordinary /data package, it is not a
#     provider without the RRO, and removing a package the user may want for other reasons is not
#     this module's call. README.md gives the one command if you do want it gone.

MODDIR=$(dirname "$0")
: "${MODPATH:=$MODDIR}"
PATH=/system/bin:/system/xbin:/vendor/bin:/sbin:$PATH
# sandbox hook only (see service.sh); inert unless QODER_SHIM is set
if [ -n "${QODER_SHIM:-}" ]; then PATH="$QODER_SHIM:$PATH"; fi
export PATH

if [ -f "$MODPATH/pref-backup" ]; then
    old=$(cat "$MODPATH/pref-backup")
    if [ -z "$old" ]; then
        settings delete global webview_provider >/dev/null 2>&1
    else
        settings put global webview_provider "$old" >/dev/null 2>&1
    fi
    now=$(settings get global webview_provider 2>/dev/null)
    echo "webview_provider: was pinned, restoring to '$old' (now reads '$now')"
else
    echo "webview_provider: this module never pinned it, nothing to restore"
fi

# Only touch files we know we created. module.prop / the overlay / the manifest all disappear with
# the directory; listing them here is just so the log says what went away.
for f in boot-verify.log boot-verify.log.old installed-overlay.sha256 pref-backup no-pin; do
    [ -e "$MODPATH/$f" ] && rm -f "$MODPATH/$f"
done
echo "Module files in $MODPATH removed; reboot to finish the rollback."
echo "WebView 81 (com.android.webview) was never touched by this module and remains the fallback."
exit 0

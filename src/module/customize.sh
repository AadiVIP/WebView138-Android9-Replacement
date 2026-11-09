#!/system/bin/sh
# Runs inside Magisk's installer (or inside our own update-binary). Installs NOTHING of its own:
# the module directory is already the finished product, Magisk just copies it. This script's whole
# job is to REFUSE a bad install, because a silent failure here means "the overlay was never scanned"
# and the user would only discover that much later.
#
# Magisk exposes ui_print/abort/set_perm_recursive as shell FUNCTIONS. They are not present when the
# script is run by a plain sh, so every use is guarded - the logic must be identical either way.

have_fn() { type "$1" >/dev/null 2>&1; }
say()   { if have_fn ui_print; then ui_print "$1"; else echo "   $1"; fi; }
bail()  { say "!! $1"; if have_fn abort; then abort "$1"; else echo "ABORT: $1" >&2; exit 1; fi; }

: "${MODPATH:?MODPATH is not set - run this from the Magisk installer, not by hand}"
[ -z "$ZIPFILE" ] && ZIPFILE=unknown

ID=$(sed -n 's/^id=//p' "$MODPATH/module.prop" 2>/dev/null | head -1)
[ "$ID" = "webview138-replacement" ] || bail "module.prop id is '$ID', expected 'webview138-replacement'"

# --- 1. API level. The RRO targets Android 9 semantics: from API 29 a framework overlay must name an
#     <overlayable> entry, which android:config_webview_packages is not, so idmap would reject it.
if [ -n "${API:-}" ]; then
    [ "$API" -eq 28 ] 2>/dev/null || bail "this module is built for API 28 (Android 9); this device reports API $API"
    say "API $API confirmed"
else
    say "WARNING: API unknown (flashed from recovery?). The module is built for Android 9 / API 28."
fi

# --- 2. the overlay bytes must still be the bytes the auditor signed off on.
MANIFEST="$MODPATH/webview138.manifest"
[ -f "$MANIFEST" ] || bail "$MANIFEST missing - the module is incomplete"
mget() { sed -n "s/^$1=//p" "$MANIFEST" | head -1; }
OVERLAY=$(mget overlay_file)
APK="$MODPATH/system/vendor/overlay/$OVERLAY"
[ -f "$APK" ] || bail "expected the overlay at $APK and it is not there"
command -v sha256sum >/dev/null 2>&1 || bail "no sha256sum on this shell - cannot verify the payload, refusing to install half-blind"
got=$(sha256sum "$APK" | cut -d' ' -f1)
want=$(mget overlay_sha256)
[ "$got" = "$want" ] || bail "overlay sha256 mismatch: got $got want $want - the payload is not what was audited"
say "overlay verified: $OVERLAY ($got)"

# --- 3. is the provider logic actually the one that makes Google the default?
[ "$(mget provider_1_packageName)" = "com.google.android.webview" ]      || bail "provider #1 is not com.google.android.webview"
[ "$(mget provider_1_availableByDefault)" = "true" ]   || bail "provider #1 is not availableByDefault"
[ "$(mget provider_1_isFallback)" = "false" ]          || bail "provider #1 is isFallback=true: the platform would DISABLE it once another valid provider exists"
n=$(mget provider_count)
[ "${n:-0}" -ge 2 ] 2>/dev/null || bail "only $n provider(s) declared - Android 9 throws AndroidRuntimeException if no availableByDefault provider survives, so never ship a list that holds just one"
say "provider list: $n entries, com.google.android.webview first, availableByDefault, not fallback"

# --- 4. Android 9 only scans these two directories for static RROs (PackageManagerService.java:578,580
#     scanned at :2609,:2616). If neither exists at scan time the module can do nothing, so pick the
#     one that does before we finish installing. VDIR/PDIR are overridable ONLY so this branch can be
#     exercised in a sandbox; on a device they are /vendor/overlay and /product/overlay.
: "${VDIR:=/vendor/overlay}"
: "${PDIR:=/product/overlay}"
moved=0
if [ ! -d "$VDIR" ] && [ -d "$PDIR" ]; then
    mkdir -p "$MODPATH/system/product/overlay" || bail "cannot create system/product/overlay"
    mv "$APK" "$MODPATH/system/product/overlay/$OVERLAY" || bail "cannot relocate the overlay to /product/overlay"
    rmdir "$MODPATH/system/vendor/overlay" "$MODPATH/system/vendor" 2>/dev/null
    moved=1
    say "WARNING: $VDIR does not exist on this device - the overlay was relocated to $PDIR"
elif [ ! -d "$VDIR" ] && [ ! -d "$PDIR" ]; then
    bail "neither $VDIR nor $PDIR exists on this device. Android 9 scans ONLY those two for static RROs, and this module will not invent a directory on a read-only partition."
fi
[ $moved -eq 0 ] && say "target: $VDIR"

# --- 5. record what this install was, so uninstall and the deployer can prove what they remove.
printf '%s\n' "$got" > "$MODPATH/installed-overlay.sha256"
say "customize.sh OK"
exit 0

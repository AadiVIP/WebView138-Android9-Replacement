#!/system/bin/sh
# Install / verify / remove the WebView-138 replacement Magisk module WITHOUT flashing anything.
#
#     su -c 'sh magisk_deploy.sh --check'                      # reads everything, writes nothing
#     su -c 'sh magisk_deploy.sh --install --src /sdcard/Download/webview138-replacement --i-reviewed'
#     su -c 'sh magisk_deploy.sh --remove --i-reviewed'
#
# WHY THIS SCRIPT EXISTS NEXT TO THE FLASHABLE ZIP. A module ZIP is installed by
# META-INF/com/google/android/update-binary, whose contract belongs to Magisk. Magisk's own template
# and util_functions.sh are not on the machine that built this project and the offline rule forbids
# fetching them, so the ZIP's update-binary is a re-implementation that cannot be claimed compatible
# with an unknown Magisk build. The module DIRECTORY layout - /data/adb/modules/<id>/module.prop +
# the files - is the interface Magisk itself consumes at boot, and it is what this script writes. So
# the path that was actually tested end to end is this one; the ZIP is for convenience in a Magisk
# app that accepts it.
#
# WHAT IT NEVER DOES: it never writes to /system, /vendor or /product (the overlay arrives via
# Magisk's magic mount, which is why no partition has to be writable); it never flashes, never
# reboots the device by itself, never disables or uninstalls any package, never touches
# framework-res.apk, and never deletes a path that is not exactly the one module directory.
#
# Sandbox-only test hooks (never set on a device): QODER_ALLOW_TARGET=1 permits a MODULES_DIR
# outside /data/adb/modules; QODER_SHIM prepends a directory of stub pm/settings/dumpsys/getprop.

PATH="/system/bin:/system/xbin:/vendor/bin:/sbin:$PATH"

: "${MODULES_DIR:=/data/adb/modules}"
: "${MOD_ID:=webview138-replacement}"
: "${GOOGLE_PKG:=com.google.android.webview}"
: "${SETTINGS_KEY:=webview_provider}"

SRC=""
MODE=check
REVIEWED=0
REINSTALL=0
NEXT=""
for a in "$@"; do
    case "$a" in
        --check)     MODE=check ;;
        --install)   MODE=install ;;
        --remove)    MODE=remove ;;
        --reinstall) REINSTALL=1 ;;
        --i-reviewed) REVIEWED=1 ;;
        --src)       NEXT=src ;;
        -h|--help)   sed -n '2,/^$/p' "$0"; exit 0 ;;
        *) if [ "$NEXT" = src ]; then SRC=$a; NEXT="";
           else echo "unknown option: $a (options: --check --install --remove --reinstall --src PATH --i-reviewed)" >&2; exit 2; fi ;;
    esac
done
[ -z "$NEXT" ] || { echo "--src needs a path" >&2; exit 2; }
SRC=$(echo "$SRC" | sed 's:/*$::')
DEST="$MODULES_DIR/$MOD_ID"

say() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1; }
have() { command -v "$1" >/dev/null 2>&1; }
die() { printf '\nREFUSED: %s\n' "$1"; printf 'Nothing was changed.\n'; exit 1; }

[ -n "$QODER_SHIM" ] && PATH="$QODER_SHIM:$PATH" && export PATH

# Sandbox-only test hooks (never set on a device): QODER_ALLOW_TARGET=1 permits a MODULES_DIR
# outside /data/adb/modules; QODER_SHIM prepends a directory of stub pm/settings/dumpsys/getprop;
# QODER_UID impersonates uid 0 so the install/remove branches can be exercised off-device. All three
# are inert unless somebody sets them, and selftest_magisk.py is the only thing that does.
: "${QODER_UID:=$(id -u 2>/dev/null)}"
UID_N="$QODER_UID"
echo "magisk_deploy.sh  mode=$MODE  uid=${UID_N:-?}  $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  MODULES_DIR=$MODULES_DIR   DEST=$DEST"
[ -n "$SRC" ] && echo "  SRC=$SRC"

# ---------------------------------------------------------------- shared reads
sdk=$(getprop ro.build.version.sdk 2>/dev/null)
rel=$(getprop ro.build.version.release 2>/dev/null)
btype=$(getprop ro.build.type 2>/dev/null)
abi64=$(getprop ro.product.cpu.abilist64 2>/dev/null)

say "1. TARGET SYSTEM (this must be the guest, not the physical phone)"
echo "  Android $rel / API $sdk / build $btype"
echo "  abilist64 = ${abi64:-unknown}"
[ "$MODE" = install ] && { [ "$sdk" = 28 ] || die "API is '$sdk', this module is built for API 28. Android 10+ requires a framework overlay to name an <overlayable> entry, which config_webview_packages is not, so it cannot work there."; }
case "$abi64" in
    *arm64*) echo "  arm64-v8a present: the 138 ARM64 package can run here." ;;
    "")      echo "  abilist64 unreadable - verify manually before installing." ;;
    *)       echo "  WARNING: abilist64 lists no arm64-v8a ($abi64). The 138 ARM64 APK cannot load." ;;
esac

say "2. IS MAGISK ACTUALLY HERE?"
if [ -d "$MODULES_DIR" ]; then
    echo "  $MODULES_DIR exists. Modules:"
    ls -1 "$MODULES_DIR" 2>/dev/null | sed 's/^/    /'
    for m in "$MODULES_DIR"/*; do
        [ -e "$m/disabled" ] && echo "    $(basename "$m") is DISABLED"
        [ -e "$m/remove" ]   && echo "    $(basename "$m") is queued for removal"
    done
    [ "$UID_N" = 0 ] || echo "  (not uid 0: writes into it will fail)"
    have magisk && echo "  magisk binary: $(command -v magisk)" || echo "  no 'magisk' on PATH (normal - the app is not a CLI)"
else
    echo "  $MODULES_DIR is not visible to this shell."
    if [ "$UID_N" != 0 ]; then
        # /data is 0771+SELinux here: an EXISTING directory and one that was never created both answer
        # EACCES to a non-root uid, so absence cannot be concluded from this - only from a root shell.
        echo "  -> uid is ${UID_N:-?}, NOT root. This is NOT proof Magisk is absent; it is proof this"
        echo "     shell cannot look. Re-run as:  su -c 'sh '$0' --check'"
        [ "$MODE" = install ] && die "cannot see $MODULES_DIR from uid ${UID_N:-?}; install needs root: su -c 'sh $0 --install ...'"
    else
        echo "  -> Magisk is not installed or not enabled in this system, so Option A cannot work here."
        echo "  -> Nothing in this script creates it; that would pretend a mechanism exists."
        [ "$MODE" = install ] && die "$MODULES_DIR absent: no Magisk, no modules."
    fi
fi

say "3. THE TWO DIRECTORIES ANDROID 9 SCANS FOR STATIC RROs"
echo "  PackageManagerService.java:578 /vendor/overlay and :580 /product/overlay, scanned at :2609,:2616"
TARGET=""
: "${VDIR:=/vendor/overlay}"
: "${PDIR:=/product/overlay}"
for d in "$VDIR" "$PDIR"; do
    if [ -d "$d" ]; then
        echo "  $d EXISTS  ($(ls "$d" 2>/dev/null | grep -c '\.apk$') apk(s))"
        [ -z "$TARGET" ] && TARGET=$d
    else
        echo "  $d does not exist"
    fi
done
[ -n "$TARGET" ] || echo "  neither exists -> the overlay can never be scanned; customize.sh aborts on this too."

say "4. THE PAYLOAD, VERIFIED BEFORE ANYTHING IS COPIED OR ACCEPTED"
mget() { sed -n "s/^$1=//p" "$2" 2>/dev/null | head -1; }
[ "$UID_N" = 0 ] || [ "$MODE" = check ] || die "install/remove need root (uid 0); this shell is uid ${UID_N:-?}"
have sha256sum || die "no sha256sum available - this script refuses to install what it cannot verify"

check_tree() {   # $1 = directory holding the module
    d=$1
    [ -f "$d/module.prop" ]      || { echo "  $d/module.prop missing"; return 1; }
    [ "$(mget id "$d/module.prop")" = "$MOD_ID" ] || { echo "  module.prop id is '$(mget id "$d/module.prop")', expected $MOD_ID"; return 1; }
    [ -f "$d/webview138.manifest" ] || { echo "  $d/webview138.manifest missing - no audit trail"; return 1; }
    ov=$(mget overlay_file "$d/webview138.manifest")
    apk=$(find "$d/system" -name "$ov" 2>/dev/null | head -1)
    [ -n "$apk" ] || { echo "  $ov not found under $d/system"; return 1; }
    got=$(sha256sum "$apk" | cut -d' ' -f1)
    want=$(mget overlay_sha256 "$d/webview138.manifest")
    if [ "$got" != "$want" ]; then echo "  sha256 MISMATCH: got $got want $want"; return 1; fi
    echo "  $d"
    echo "    overlay      $apk"
    echo "    sha256       $got  (matches the audit manifest)"
    echo "    bytes        $(wc -c < "$apk" | tr -d ' ')  (manifest says $(mget overlay_bytes "$d/webview138.manifest"))"
    echo "    provider #1  $(mget provider_1_packageName "$d/webview138.manifest")"
    echo "    avail/fall   $(mget provider_1_availableByDefault "$d/webview138.manifest") / $(mget provider_1_isFallback "$d/webview138.manifest")"
    echo "    cert sha256  $(mget cert_sha256 "$d/webview138.manifest")"
    [ "$(mget provider_1_packageName "$d/webview138.manifest")" = "$GOOGLE_PKG" ] || { echo "    provider #1 is not $GOOGLE_PKG"; return 1; }
    [ "$(mget provider_1_isFallback "$d/webview138.manifest")" = "false" ] || { echo "    provider #1 would be disabled by the fallback logic"; return 1; }
    return 0
}

case "$MODE" in
check)
    if [ -n "$SRC" ]; then
        check_tree "$SRC" || die "the source tree is not usable - fix it before installing"
    else
        echo "  no --src given; nothing to verify before install. Add --src <staged module dir>."
    fi
    ;;
install)
    [ "$REVIEWED" = 1 ] || die "install changes the device's boot behaviour. Re-run with --i-reviewed to confirm you have read the module's README, customize.sh, service.sh and uninstall.sh."
    [ -n "$SRC" ] || die "--install needs --src <directory>"
    [ -d "$SRC" ] || die "$SRC is not a directory (unzip WebView138-Replacement-Magisk.zip first and point --src at the webview138-replacement folder inside it)"
    check_tree "$SRC" || die "refusing to install a tree that does not verify"
    [ -n "$TARGET" ] || die "neither /vendor/overlay nor /product/overlay exists on this system."
    case "$MODULES_DIR" in
        /data/adb/modules) : ;;
        *) [ "${QODER_ALLOW_TARGET:-0}" = 1 ] || die "MODULES_DIR=$MODULES_DIR is not /data/adb/modules. Set QODER_ALLOW_TARGET=1 only for sandbox testing." ;;
    esac
    if [ -e "$DEST" ]; then
        if [ -f "$DEST/installed-overlay.sha256" ] || [ -f "$DEST/module.prop" ]; then
            ours=$(mget id "$DEST/module.prop")
            [ "$ours" = "$MOD_ID" ] || die "$DEST exists with id '$ours' - that is somebody else's module and this script will not overwrite it."
            [ "$REINSTALL" = 1 ] || die "$DEST is already installed. Use --reinstall to replace it, or --remove first."
        else
            die "$DEST exists but is not a module we recognise. Not touching it."
        fi
    fi
    say "WRITING $DEST"
    mkdir -p "$DEST" || die "cannot create $DEST"
    cp -a "$SRC/." "$DEST/" || die "copy failed; partial tree left at $DEST, run --remove to clean it"
    check_tree "$DEST" || die "the copy at $DEST does not verify - run --remove"
    printf '%s\n' "$(mget overlay_sha256 "$DEST/webview138.manifest")" > "$DEST/installed-overlay.sha256"
    rm -f "$DEST/remove" "$DEST/disabled" 2>/dev/null
    # run the same validation a flashed install would run, as a child so its 'exit' cannot kill us
    ( MODPATH="$DEST" sh "$DEST/customize.sh" ) ; rc=$?
    [ $rc -eq 0 ] || { echo "  customize.sh refused with rc=$rc."; die "customize.sh rejected the installation"; }
    # labels: report, do not guess. Magisk's own installer creates these files; a cp from /sdcard
    # carries the source context, which may or may not be what magic mount needs.
    echo "  SELinux context of what we wrote:"
    ls -Zd "$DEST" 2>/dev/null | sed 's/^/    /'
    ls -Z "$DEST"/system/*/*/ 2>/dev/null | head -4 | sed 's/^/    /'
    for m in "$MODULES_DIR"/*; do
        [ -d "$m" ] && [ "$m" != "$DEST" ] && { echo "    (for comparison) $m:"; ls -Zd "$m" 2>/dev/null | sed 's/^/      /'; break; }
    done
    sync
    say "INSTALLED. NOTHING HAS REBOOTED - the overlay only takes effect at the next boot."
    cat <<EOF
  Read this before you reboot:
    1. The Google WebView 138 package must be installed too; this module does not carry it:
         su -c 'pm install -r /data/local/tmp/webview138.apk'
    2. Reboot when you choose to:   su -c reboot
    3. After boot, prove it instead of assuming it:
         su -c 'cat $DEST/boot-verify.log'
         su -c 'dumpsys webviewupdate | head -20'
         su -c 'ls -l $TARGET/'
       Expect 'Current WebView package (name, version): ($GOOGLE_PKG, 138.0.7204.179)'.
    4. Roll back:  su -c 'sh magisk_deploy.sh --remove --i-reviewed'   then reboot.
EOF
    ;;
remove)
    [ "$REVIEWED" = 1 ] || die "--remove also changes state. Re-run with --i-reviewed."
    [ -d "$DEST" ] || die "$DEST does not exist - there is nothing this script may remove."
    [ "$(mget id "$DEST/module.prop")" = "$MOD_ID" ] || die "refusing to delete $DEST: its module.prop id is not $MOD_ID"
    [ -f "$DEST/installed-overlay.sha256" ] || echo "  note: no installed-overlay.sha256 marker (installed by flashing, or an older build)"
    case "$DEST" in
        /data/adb/modules/"$MOD_ID") : ;;
        *) [ "${QODER_ALLOW_TARGET:-0}" = 1 ] || die "refusing to delete $DEST: not the expected module path" ;;
    esac
    say "ROLLING BACK"
    if [ -f "$DEST/uninstall.sh" ]; then
        ( MODPATH="$DEST" sh "$DEST/uninstall.sh" )
    else
        echo "  uninstall.sh absent; restoring the preference here instead."
        if [ -f "$DEST/pref-backup" ]; then
            old=$(cat "$DEST/pref-backup")
            if [ -z "$old" ]; then settings delete global "$SETTINGS_KEY"; else settings put global "$SETTINGS_KEY" "$old"; fi
            echo "  webview_provider restored to '$old'"
        else
            echo "  this module never pinned $SETTINGS_KEY (it reads '$(settings get global "$SETTINGS_KEY" 2>/dev/null)')"
        fi
    fi
    rm -rf "$DEST"
    [ -e "$DEST" ] && die "rm reported success but $DEST still exists - investigate before continuing"
    sync
    cat <<EOF
  Module directory gone. At the next boot Magisk has no files to mount, /vendor/overlay reverts to
  the real read-only partition contents, the framework's own signed config_webview_packages.xml is
  authoritative again, and the factory provider com.android.webview is selected. WebView 138 is
  still installed but is not a provider (it is not in the factory list) - to drop it as well run
  the package manager yourself:  su -c 'pm uninstall $GOOGLE_PKG'
  Reboot to finish:  su -c reboot
EOF
    ;;
esac

say "5. CURRENT WEBVIEW STATE ON THIS DEVICE"
if have dumpsys; then
    dumpsys webviewupdate 2>&1 | grep -E 'Current WebView package|Minimum WebView version|Fallback logic|Preferred WebView|Valid package|Invalid package|NOT installed' | sed 's/^/  /'
else
    echo "  dumpsys not on PATH"
fi
echo "  settings get global $SETTINGS_KEY = '$(settings get global "$SETTINGS_KEY" 2>/dev/null)'"
if have pm; then
    pm list packages "$GOOGLE_PKG" 2>/dev/null | sed 's/^/  provider package: /'
    pm list packages com.android.webview 2>/dev/null | sed 's/^/  factory package : /'
    path=$(pm path "$GOOGLE_PKG" 2>/dev/null | head -1 | sed 's/^package://')
    [ -n "$path" ] && { echo "  installed at: $path"; }
    if [ -n "$path" ] && [ -r "$path" ]; then
        echo "  installed sha256: $(sha256sum "$path" | cut -d' ' -f1)"
    else
        echo "  (installed APK bytes not readable from this uid - normal for a non-root shell)"
    fi
fi
[ -d "$DEST" ] && echo "  module present at $DEST; marker sha256 $(cat "$DEST/installed-overlay.sha256" 2>/dev/null)"

echo
echo "VERDICT_DEPLOY mode=$MODE sdk=$sdk magisk_dir=$([ -d "$MODULES_DIR" ] && echo yes || echo no) target_dir=${TARGET:-none} module_present=$([ -d "$DEST" ] && echo yes || echo no) pref=$(settings get global "$SETTINGS_KEY" 2>/dev/null)"
exit 0

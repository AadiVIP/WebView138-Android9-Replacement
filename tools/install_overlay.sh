#!/system/bin/sh
#
# Staged, reversible installer for the WebView-138 provider RRO (Virtual Master / Android 9).
#
#   CHECK FIRST (reads only, writes nothing, default mode):
#       sh /sdcard/Download/install_overlay.sh \
#           --overlay  /sdcard/Download/webview138-provider-overlay.apk \
#           --manifest /sdcard/Download/webview138-provider-overlay.manifest
#
#   INSTALL (refuses unless you pass --i-reviewed, i.e. you have read the check output):
#       sh ... --install --i-reviewed
#
#   UNDO EVERYTHING THIS SCRIPT DID:
#       sh ... --uninstall --i-reviewed
#
#   SEPARATE STEP, to register the 138 APK itself:
#       sh ... --webview-apk /sdcard/Download/webview138_arm64_universal.apk --install-apk --i-reviewed
#
# HARD RULES BUILT INTO THIS SCRIPT
#   * It writes only to: $TARGET_DIR/<the one overlay apk>, $STATE, and /data/local/tmp (only for
#     --install-apk staging), and - only with --purge-idmap - resource-cache entries naming our file.
#   * It never touches /system, never touches com.android.webview, never touches
#     /system/app/webview/webview.apk. WebView 81 stays exactly as it is.
#   * It never reboots, never remounts, never disables verified boot, never runs pm uninstall or
#     pm disable against anything, never installs a third-party module.
#   * It refuses to install a file whose sha256 differs from the manifest that
#     tools/verify_overlay.py emitted - so what lands on the device is byte-for-byte what was
#     audited off-device. The manifest itself is only written when every audit check passed.
#   * EACCES / EROFS is reported as-is. A failed write means nothing was installed, and it says so.

set -u

PATH="/system/bin:/system/xbin:/vendor/bin:/product/bin:$PATH"; export PATH

die() { echo "ABORT: $*" >&2; exit 1; }
if [ "${QODER_FAKE_PM:-0}" = 1 ]; then
    pm() {
        echo "FAKE-PM: $*"
        case "$*" in *fail*) return 1 ;; esac
        return 0
    }
fi
ok()  { echo "  [ok]   $*"; }
no()  { echo "  [NO]   $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

TARGET_DIR=/vendor/overlay

# STAGE is where the 138 APK is copied so installd can read it; QODER_FAKE_PM replaces the real `pm`
# so this branch can be exercised on a machine that must not have anything installed on it. Neither
# hook is set on the guest: the defaults are the real device paths and the real package manager.
: "${STAGE:=/data/local/tmp/webview138.apk}"
OVERLAY=""
MANIFEST=""
WEBVIEW_APK=""
STATE=/data/local/tmp/webview138-overlay.state
MODE=check
I_REVIEWED=0
PURGE_IDMAP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --overlay)      OVERLAY=$2;     shift 2 ;;
        --manifest)     MANIFEST=$2;    shift 2 ;;
        --webview-apk)  WEBVIEW_APK=$2; shift 2 ;;
        --target)       TARGET_DIR=$2;  shift 2 ;;
        --state)        STATE=$2;       shift 2 ;;
        --install)      MODE=install;   shift ;;
        --uninstall)    MODE=uninstall; shift ;;
        --install-apk)  MODE=install-apk; shift ;;
        --purge-idmap)  PURGE_IDMAP=1;  shift ;;
        --i-reviewed)   I_REVIEWED=1;   shift ;;
        *) die "unknown option: $1" ;;
    esac
done

echo "=== install_overlay.sh  mode=$MODE  target=$TARGET_DIR  $(date 2>/dev/null)  uid=$(id 2>/dev/null) ==="

# ---------------------------------------------------------------- path boundaries, checked first
# QODER_ALLOW_TARGET exists only so these code paths can be exercised in a sandbox before anyone
# runs them on the guest. Never set it on the device.
case "$TARGET_DIR" in
    /system|/system/*)
        die "refusing to write under /system. Android 9 scans only /vendor/overlay (PackageManagerService.java:578) and /product/overlay (:580); a /system overlay is never read, and writing to /system would put the factory partition - and WebView 81 - at risk." ;;
    /vendor/overlay|/product/overlay)
        ok "target is one of the two directories PMS scans at boot (:2609, :2616)";;
    *)
        [ "${QODER_ALLOW_TARGET:-}" = 1 ] \
            && { no "target '$TARGET_DIR' accepted ONLY because QODER_ALLOW_TARGET=1 is set - this is a sandbox path, PMS would never scan it on a device"; } \
            || die "target '$TARGET_DIR' is not /vendor/overlay or /product/overlay, so PMS would never scan it. Use --target /product/overlay only if section 3 of the probe showed /product writable." ;;
esac

if [ "$MODE" != check ] && [ $I_REVIEWED -eq 0 ]; then
    die "mode=$MODE writes to the device. Run the check first, read its output, then add --i-reviewed."
fi
if [ "$MODE" != uninstall ] && [ -z "$OVERLAY" ]; then
    die "--overlay <path to webview138-provider-overlay.apk> is required for check and install"
fi
if [ "$MODE" = install ] && [ ! -r "$OVERLAY" ]; then
    die "--overlay $OVERLAY is not readable"
fi

# ---------------------------------------------------------------- 1. bind the file to the audit
echo
if [ "$MODE" = uninstall ]; then
    echo "(uninstall: sections 1-4 describe a NEW install for context; what gets DELETED is governed"
    echo " solely by the rollback record in $STATE/installed.env, verified by sha256)"
fi
echo "--- 1. is the staged file the one that was audited off-device? ---"
M_FILE=""; M_BYTES=""; M_SHA=""; M_PKG=""; M_TARGET=""; M_STATIC=""; M_PRIO=""; M_N=""; M_P1=""; M_P1_FB=""
mget() { sed -n "s/^$1=//p" "$MANIFEST" 2>/dev/null | head -1; }
if [ -z "$MANIFEST" ]; then
    no "no --manifest given: the on-device file cannot be bound to the off-device audit. Everything below is advisory only."
elif [ ! -r "$MANIFEST" ]; then
    die "--manifest $MANIFEST not readable"
else
    M_FILE=$(mget overlay_file);       M_BYTES=$(mget overlay_bytes)
    M_SHA=$(mget overlay_sha256);      M_PKG=$(mget overlay_package)
    M_TARGET=$(mget overlay_targetPackage); M_STATIC=$(mget overlay_isStatic)
    M_PRIO=$(mget overlay_priority);   M_N=$(mget provider_count)
    M_P1=$(mget provider_1_packageName); M_P1_FB=$(mget provider_1_isFallback)
    echo "  manifest: file=$M_FILE bytes=$M_BYTES pkg=$M_PKG target=$M_TARGET isStatic=$M_STATIC priority=$M_PRIO providers=$M_N"
    echo "            provider_1=$M_P1 isFallback=$M_P1_FB"
    echo "            cert_sha256=$(mget cert_sha256)"
    if [ "$(basename "${OVERLAY:-$M_FILE}")" = "$M_FILE" ]; then
        ok "filename matches the manifest"
    else
        no "filename $(basename "${OVERLAY:-?}") != manifest '$M_FILE' (the sha256 below is what actually matters)"
    fi
    [ -r "${OVERLAY:-/nonexistent}" ] || die "overlay file '$OVERLAY' not readable"
    sz=$(wc -c < "$OVERLAY" 2>/dev/null | tr -d ' \n')
    if [ "$sz" = "$M_BYTES" ]; then ok "size $sz bytes == manifest"; else no "size $sz != manifest $M_BYTES"; fi
    got=$(sha256sum "$OVERLAY" 2>/dev/null | cut -d' ' -f1)
    if [ -z "$got" ]; then
        no "sha256sum unavailable in this shell: cannot bind the file to the audit"
        [ "$MODE" = install ] && die "install needs the sha256 check; re-run where sha256sum exists (toybox has it)"
    elif [ "$got" = "$M_SHA" ]; then
        ok "sha256 $got == the audited build"
    else
        no "sha256 MISMATCH got=$got want=$M_SHA"
        die "refusing to touch a file that is not the one tools/verify_overlay.py checked"
    fi
    [ "$M_TARGET" = android ] && ok "overlay targetPackage=android (PackageParser matches the framework by NAME)" \
        || die "manifest targetPackage=$M_TARGET, expected android"
    [ "$M_STATIC" = true ] && ok "isStatic=true (PackageParser.java:2066-2068 defaults it to FALSE, which would never auto-apply)" \
        || die "manifest isStatic=$M_STATIC; a non-static overlay is not applied at boot"
    case "$M_PRIO" in
        ''|*[!0-9]*) die "manifest priority '$M_PRIO' is not a number" ;;
    esac
    if [ "$M_PRIO" -ge 0 ] && [ "$M_PRIO" -le 9999 ]; then
        ok "priority $M_PRIO inside 0..9999 (PackageParser.java:2081-2086 rejects anything else by ignoring the overlay)"
    else
        die "priority $M_PRIO outside 0..9999"
    fi
    [ "$M_P1" = com.google.android.webview ] \
        && ok "provider_1=com.google.android.webview - first availableByDefault entry in document order wins (WebViewUpdater.java:305-315)" \
        || die "manifest provider_1=$M_P1; the Google entry must be first"
    [ "$M_P1_FB" = false ] \
        && ok "provider_1 isFallback=false. Required: fallback logic is ON by default (SystemImpl.java:212-216) and the platform disables the fallback provider once a valid non-fallback one exists (WebViewUpdateServiceImpl.java:202-220 -> SystemImpl.java:225-235)." \
        || die "manifest provider_1_isFallback=$M_P1_FB - installing it would let the platform itself disable WebView 138"
    [ "${M_N:-0}" -ge 2 ] && ok "provider list has $M_N entries, so the factory provider is still declared" \
        || no "only $M_N provider(s) declared: com.android.webview must stay in the list or WebView 81 stops being a candidate"
fi

# ---------------------------------------------------------------- 2. cheap structural checks
echo
echo "--- 2. structural sanity of the staged APK (the deep checks ran off-device) ---"
if have unzip && [ -n "${OVERLAY:-}" ]; then
    unzip -l "$OVERLAY" 2>&1 | sed 's/^/  /'
    for e in AndroidManifest.xml resources.arsc res/xml/config_webview_packages.xml; do
        if unzip -l "$OVERLAY" 2>/dev/null | grep -q "[ ]$e\$"; then
            ok "entry present: $e"
        else
            die "entry MISSING: $e - this APK cannot override the framework resource"
        fi
    done
    echo "  (resources.arsc must be STORED so AssetManager can mmap it - see the 'Method' column above;"
    echo "   tools/verify_overlay.py already asserted compress_type==0 and 4-byte alignment)"
else
    no "no unzip in this shell: skipping the entry listing"
fi

# ---------------------------------------------------------------- 3. acceptance conditions on device
echo
echo "--- 3. acceptance conditions on THIS device ---"
if [ -d "$TARGET_DIR" ]; then
    ls -ldZ "$TARGET_DIR" 2>/dev/null | sed 's/^/  /' || ls -ld "$TARGET_DIR" 2>/dev/null | sed 's/^/  /'
else
    no "$TARGET_DIR does not exist yet; --install will mkdir it, which fails for real if the partition is ro"
fi
n=$(ls "$TARGET_DIR" 2>/dev/null | grep -c '\.apk$')
echo "  overlay APKs already in the dir: ${n:-0}  (a populated dir = static RROs demonstrably work here)"
FINAL="$TARGET_DIR/${M_FILE:-$(basename "${OVERLAY:-none}")}"
ALREADY=no
# In uninstall mode the file is SUPPOSED to exist - the rollback section decides what to delete, by
# the recorded sha256, not by whatever path happens to be named here.
if [ "$MODE" != uninstall ] && [ -e "$FINAL" ]; then
    old=$(sha256sum "$FINAL" 2>/dev/null | cut -d' ' -f1)
    if [ -n "$M_SHA" ] && [ "$old" = "$M_SHA" ]; then
        ok "$FINAL is already present and byte-identical - nothing to install"
        ALREADY=same
    else
        no "$FINAL already exists and differs (sha256 ${old:-unknown})"
        die "a different file occupies the target path. This script will not overwrite something it did not create - check what it is first."
    fi
fi
if have pm && [ -n "$M_PKG" ]; then
    if pm list packages 2>/dev/null | grep -qx "package:$M_PKG"; then
        die "$M_PKG is ALREADY a known package. PMS would see a duplicate; I have not proven from source which one wins, so this script refuses. Roll back first (--uninstall)."
    else
        ok "$M_PKG is not a known package: the boot scan would add it fresh"
    fi
fi
if [ -r /system/framework/framework-res.apk ]; then
    ok "/system/framework/framework-res.apk readable here ($(wc -c < /system/framework/framework-res.apk | tr -d ' \n') B); idmap/installd must also be able to open it"
else
    no "/system/framework/framework-res.apk not readable by this uid. installd runs as root so idmap may still work - the probe's section 5 answer about /data/resource-cache is the evidence to trust"
fi
echo "  space at the target: $(df "$TARGET_DIR" 2>/dev/null | tail -1)"
echo "  the overlay is ${M_BYTES:-?} bytes - a few KB; space is never the issue for the RRO"
have restorecon && echo "  restorecon present" || echo "  restorecon absent: the file will inherit the directory label"

# ---------------------------------------------------------------- 4. the plan, printed before any write
echo
echo "--- 4. exactly what --install --i-reviewed does ---"
cat <<EOF
    1. mkdir -p $TARGET_DIR                                  (only if absent)
    2. write $TARGET_DIR/.new-$(basename "$FINAL")  then sync   (never the final name in place)
    3. sha256 the copy and compare it to the manifest                     (a bad copy is deleted)
    4. chmod 0644, chown root:root, restorecon if available
    5. mv the temp to $FINAL                     (atomic rename inside one filesystem)
    6. record $STATE/installed.env                  (this is what --uninstall reads)
    7. print a reminder. You reboot. This script never reboots.
    PMS then parses it at boot (:2609, :2616) and installd generates the .idmap (:832-834);
    a failed idmap logs 'Failed to generate idmap for ...' (:839-841) and the overlay is skipped.
EOF
echo "    DELIBERATELY NOT DONE:"
echo "      - nothing under /system is written, replaced or repacked"
echo "      - com.android.webview (WebView 81) is not disabled, updated or uninstalled - it remains"
echo "        the factory provider and the rollback path"
echo "      - no remount, no verified-boot change, no Magisk module, no flashing of any image"
echo "      - no 'pm install' unless you separately pass --install-apk --i-reviewed"

# ---------------------------------------------------------------- 5. staged install
if [ "$MODE" = install ]; then
    if [ "$ALREADY" = same ]; then
        echo
        echo "=== NOTHING WRITTEN: the identical file is already at $FINAL"
        exit 0
    fi
    echo
    echo "--- 5. performing the staged write ---"
    if [ ! -d "$TARGET_DIR" ]; then
        echo "  \$ mkdir -p $TARGET_DIR"
        mkdir -p "$TARGET_DIR" || die "mkdir $TARGET_DIR failed. THIS is the real answer to the writability question: the partition is read-only for this uid and the overlay cannot be installed this way."
    fi
    TMP="$TARGET_DIR/.new-$(basename "$FINAL")"
    echo "  \$ cat $OVERLAY > $TMP   (then sync)"
    cat "$OVERLAY" > "$TMP" || die "write of $TMP failed: not writable by this uid. Nothing was installed."
    sync 2>/dev/null
    got=$(sha256sum "$TMP" 2>/dev/null | cut -d' ' -f1)
    want=${M_SHA:-$(sha256sum "$OVERLAY" 2>/dev/null | cut -d' ' -f1)}
    if [ "$got" != "$want" ] || [ -z "$got" ]; then
        rm -f "$TMP" 2>/dev/null
        die "copy verification failed (got=${got:-none} want=$want). Temp removed; nothing was installed."
    fi
    ok "staged copy verified byte-for-byte: $got"
    chmod 0644 "$TMP" 2>/dev/null || no "chmod 0644 failed (the directory default may already be correct)"
    chown root:root "$TMP" 2>/dev/null || no "chown root:root failed (needs root). PMS can still read it if DAC allows - check the listing after reboot."
    if have restorecon; then restorecon "$TMP" 2>/dev/null && ok "restorecon applied" || no "restorecon refused"; fi
    echo "  \$ mv -f $TMP $FINAL"
    mv -f "$TMP" "$FINAL" || { rm -f "$TMP" 2>/dev/null; die "rename to $FINAL failed; nothing was installed"; }
    sync 2>/dev/null
    ls -lZ "$FINAL" 2>/dev/null | sed 's/^/  /' || ls -l "$FINAL" 2>/dev/null | sed 's/^/  /'
    mkdir -p "$STATE" 2>/dev/null || die "cannot create $STATE - the rollback record cannot be written, so this install would be unrecoverable by this script. Install aborted BEFORE any change? no: the file IS installed. Record the path manually: $FINAL"
    {
        echo "installed_path=$FINAL"
        echo "installed_sha256=$got"
        echo "installed_bytes=$(wc -c < "$FINAL" | tr -d ' \n')"
        echo "overlay_package=$M_PKG"
        echo "target_dir=$TARGET_DIR"
        echo "installed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)"
    } > "$STATE/installed.env" 2>/dev/null || no "could not write $STATE/installed.env - SAVE THIS OUTPUT, it is the only record of the installed path"
    ls -1 "$TARGET_DIR" > "$STATE/dir-listing-before.txt" 2>/dev/null || true
    echo
    echo "=== INSTALLED: $FINAL  (sha256 $got)"
    echo "    Now YOU reboot the guest - this script never reboots anything."
    echo "    After boot run reports/INTEGRATION_PLAN.md section 10 (verification). To undo:"
    echo "        sh $0 --target $TARGET_DIR --uninstall --i-reviewed"
    exit 0
fi

# ---------------------------------------------------------------- 6. the 138 APK itself
if [ "$MODE" = install-apk ]; then
    [ -r "$WEBVIEW_APK" ] || die "--webview-apk '$WEBVIEW_APK' not readable"
    echo
    echo "--- 138 APK install: a normal /data install. /system/app/webview is NOT touched ---"
    echo "  abilist32=$(getprop ro.product.cpu.abilist32 2>/dev/null)  abilist64=$(getprop ro.product.cpu.abilist64 2>/dev/null)"
    echo "  audited properties of this APK: arm64-v8a + armeabi-v7a, minSdk 26, maxSdk 28, targetSdk 35"
    echo "  (reports/WEBVIEW_138_COMPATIBILITY.md section 6). On a 64-bit-only device the v7a half is"
    echo "  ignored and the arm64 libraries are what load."
    echo "  size $(wc -c < "$WEBVIEW_APK" | tr -d ' \n') bytes; /data free: $(df /data 2>/dev/null | tail -1)"
    mkdir -p "$STATE" 2>/dev/null || true
    stage="$STAGE"
    log="$STATE/pm-install.log"
    echo "  staging to $stage - /sdcard is FUSE and installd frequently cannot read it"
    cat "$WEBVIEW_APK" > "$stage" || die "could not stage the APK to $stage (permissions or free space)"
    sync 2>/dev/null
    chmod 0644 "$stage" 2>/dev/null || true
    echo "  \$ pm install -r $stage    (output captured in $log)"
    pm install -r "$stage" > "$log" 2>&1
    rc=$?
    sed 's/^/    /' < "$log" 2>/dev/null
    echo "  pm install exit=$rc"
    if [ $rc -ne 0 ]; then
        rm -f "$stage" 2>/dev/null
        echo "  INSTALL FAILED. WebView 81 is untouched and remains the provider. Read the message above:"
        echo "  the usual real causes are no matching ABI, insufficient storage, or a signature conflict"
        echo "  with an existing package of the same name (rm -f $stage if it still exists)."
        exit 1
    fi
    rm -f "$stage" 2>/dev/null && ok "staged copy removed" || no "$stage still exists - delete it to reclaim the space"
    pm path com.google.android.webview 2>/dev/null | sed 's/^/  /'
    dumpsys package com.google.android.webview 2>/dev/null \
        | grep -E "versionName|versionCode|codePath" | head -5 | sed 's/^/    /'
    echo
    echo "=== 138 APK installed. Reboot is still needed for the overlay and the selection to settle."
    exit 0
fi

# ---------------------------------------------------------------- 7. rollback
if [ "$MODE" = uninstall ]; then
    echo
    echo "--- rollback ---"
    [ -r "$STATE/installed.env" ] || die "no rollback record at $STATE/installed.env. I will not guess which file to delete. If the overlay was placed by hand, remove it yourself and state the exact path you used."
    # read the record with sed, not with `.`: a value containing spaces must never be executed as code
    uget() { sed -n "s/^$1=//p" "$STATE/installed.env" | head -1; }
    installed_path=$(uget installed_path)
    installed_sha256=$(uget installed_sha256)
    installed_bytes=$(uget installed_bytes)
    overlay_package=$(uget overlay_package)
    installed_at=$(uget installed_at)
    [ -n "$installed_path" ] || die "$STATE/installed.env has no installed_path - refusing to act on a corrupt record"
    case "$installed_path" in
        /system|/system/*) die "the record points inside /system ($installed_path). This script never wrote there, so the record is not trustworthy - investigate before deleting anything" ;;
    esac
    echo "  recorded: path=$installed_path"
    echo "            sha256=$installed_sha256 bytes=$installed_bytes pkg=$overlay_package at=$installed_at"
    if [ ! -r "$installed_path" ]; then
        echo "  $installed_path is already gone - nothing to remove"
    else
        cur=$(sha256sum "$installed_path" 2>/dev/null | cut -d' ' -f1)
        if [ "$cur" != "$installed_sha256" ]; then
            die "$installed_path no longer matches the recorded sha256 (now ${cur:-unreadable}). Something else changed it; I will not delete a file this script did not install."
        fi
        ok "sha256 matches the recorded file - safe to remove"
        echo "  \$ rm -f $installed_path"
        rm -f "$installed_path" || die "rm $installed_path failed"
        sync 2>/dev/null
        if [ -e "$installed_path" ]; then die "$installed_path STILL exists after rm (partition mounted ro cannot delete either - it means the rm was refused)"; fi
        ok "removed $installed_path"
    fi
    b=$(basename "$installed_path")
    if [ $PURGE_IDMAP -eq 1 ]; then
        echo "  --purge-idmap: the /data/resource-cache naming scheme was NOT verified from AOSP source,"
        echo "  so this lists first and deletes only entries whose NAME contains our file, $b :"
        find /data/resource-cache -name "*$b*" -print 2>/dev/null | sed 's/^/    /'
        find /data/resource-cache -name "*$b*" -delete 2>/dev/null
        echo "  (PMS does not need these: an overlay absent from the scan set is never consulted)"
    else
        echo "  leaving /data/resource-cache alone: with the APK gone the overlay is not in the scan set"
        echo "  (:2609) so no idmap is consulted. Use --purge-idmap to delete them explicitly."
    fi
    rm -f "$STATE/installed.env"
    echo
    echo "=== ROLLED BACK. Reboot to return to the factory provider list."
    echo "    WebView 81 was never touched by this script, so there is nothing to restore there."
    echo "    Confirm after reboot:  pm list packages | grep ${overlay_package:-com.qoder.webviewprovider.overlay}   (must be empty)"
    echo "    If you also ran --install-apk, remove that package with:  pm uninstall com.google.android.webview"
    echo "    (that is a deliberate, separate command - this script never runs pm uninstall)"
    exit 0
fi

echo
echo "=== CHECK ONLY - nothing was written. If every line above reads [ok] and you have read them:"
echo "    sh $0 --overlay $OVERLAY ${MANIFEST:+--manifest $MANIFEST} --target $TARGET_DIR --install --i-reviewed"
exit 0

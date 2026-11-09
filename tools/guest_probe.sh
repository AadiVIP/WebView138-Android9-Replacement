#!/system/bin/sh
# Read-only probe for the Virtual Master Android 9 guest.
#
#   Run it INSIDE the guest (terminal app, or MiXplorer > device shell) and send back the whole output:
#
#       sh /sdcard/Download/guest_probe.sh              > /sdcard/Download/probe.txt 2>&1
#       sh /sdcard/Download/guest_probe.sh --test-write # adds ONE create+delete per overlay dir
#       sh /sdcard/Download/guest_probe.sh --extract    # writes a few files to /sdcard/Download only
#
#   Default run touches NOTHING. It reads only.
#
# WHY "--test-write" IS A SEPARATE FLAG: a truly read-only run cannot answer "is this directory
# writable". It can report the mount flags (ro is decisive), the owner/mode and the SELinux label, but
# DAC + ro/rw do not fully determine it - a file created here also needs the right label and a
# permissive-enough context for installd/idmap to read it. So the default run only OBSERVES, and the
# opt-in run creates and immediately deletes one dot-file per candidate directory. Nothing else in
# this script writes anything, and nothing in it installs, enables, disables, mounts or reboots.
#
# What each question is answered from (Android 9 = frameworks/base @ android-9.0.0_r35):
#   which overlay dirs are scanned .... PackageManagerService.java:578 "/vendor/overlay",
#                                       :580 "/product/overlay", scanned at :2609 and :2616 with
#                                       PARSE_IS_SYSTEM_DIR | SCAN_AS_SYSTEM. Only those two.
#   is a signature required ........... PackageManagerService.java:11232-11249 (platform-cert throw)
#                                       is in the ELSE branch of the SCAN_AS_SYSTEM test, so no.
#   is a static RRO honoured .......... cmds/idmap/scan.cpp:179-182 (only is_static_overlay gets a
#                                       tag) and PackageParser.java:2055-2094.
#   idmap assignment .................. PackageManagerService.java:832-834 mInstaller.idmap();
#                                       failure is caught and logged at :839-841 ("Failed to generate
#                                       idmap for ...") and the overlay is then silently skipped.
#   current provider + candidate list .. dumpsys webviewupdate (WebViewUpdater.java:524-550, 557-590)
#   fallback logic ..................... WebViewUpdateServiceImpl.java:202-220 + SystemImpl.java:
#                                       212-216 - ENABLED BY DEFAULT; it disables the provider flagged
#                                       isFallback once a valid non-fallback one exists.

TEST_WRITE=0
EXTRACT=0
for a in "$@"; do
    case "$a" in
        --test-write) TEST_WRITE=1 ;;
        --extract)    EXTRACT=1 ;;
        -h|--help)    sed -n '2,37p' "$0"; exit 0 ;;
        *) echo "unknown option: $a (options: --test-write --extract -h)" >&2; exit 2 ;;
    esac
done

# Android's own bins first: pm/dumpsys/settings/idmap live there, and a sandbox shell (Termux) does not
# have them on PATH, which would otherwise look like "tool missing" instead of "wrong PATH".
PATH="/system/bin:/system/xbin:/vendor/bin:/product/bin:$PATH"
export PATH

# These three are the ONLY paths this script can ever write to. The defaults are the real guest
# targets; they are overridable solely so the --test-write and --extract code paths can be exercised
# in a sandbox before anybody runs this on the guest.
: "${VDIR:=/vendor/overlay}"
: "${PDIR:=/product/overlay}"
: "${ODIR:=/sdcard/Download}"

say() { printf '\n===== %s =====\n' "$1"; }
try() { printf '$ %s\n' "$*"; "$@" 2>&1 || printf '  (command failed or absent)\n'; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "guest_probe.sh  $(date 2>/dev/null)  uid=$(id 2>/dev/null || echo unknown)"
W1=no; [ $TEST_WRITE -eq 1 ] && W1=YES
W2=none; [ $EXTRACT -eq 1 ] && W2="files under $ODIR"
echo "writes by this run: overlay-dir dot-files=$W1 , exports=$W2"
echo "targets: VDIR=$VDIR PDIR=$PDIR ODIR=$ODIR"

say "1. GUEST IDENTITY (build type decides the signature gate; abilist32 decides the ABI)"
for p in ro.build.fingerprint ro.build.version.sdk ro.build.version.release ro.build.type ro.debuggable \
         ro.product.cpu.abilist ro.product.cpu.abilist32 ro.product.cpu.abilist64 \
         ro.board.platform ro.vendor.build.fingerprint ro.product.model; do
    printf '  %-32s = %s\n' "$p" "$(getprop $p 2>/dev/null)"
done
echo "  read: ro.build.type=userdebug|eng -> systemIsDebuggable() skips the provider signature gate"
echo "        (WebViewUpdater.java:507-509). user -> the <signature> text in the overlay is what"
echo "        carries it. ro.product.cpu.abilist32 empty -> the armeabi-v7a APK cannot run here."

say "2. THE TWO DIRECTORIES ANDROID 9 ACTUALLY SCANS"
echo "  source: PackageManagerService.java:578 VENDOR_OVERLAY_DIR=\"/vendor/overlay\""
echo "          PackageManagerService.java:580 PRODUCT_OVERLAY_DIR=\"/product/overlay\""
echo "          scanned at :2609 and :2616 with PARSE_IS_SYSTEM_DIR | SCAN_AS_SYSTEM"
echo "  /system/overlay and /oem/overlay are NOT scanned for overlays on this version."
for d in "$VDIR" "$PDIR"; do
    printf '\n  --- %s ---\n' "$d"
    if [ -d "$d" ]; then
        ls -ldZ "$d" 2>/dev/null || ls -ld "$d" 2>/dev/null
        n=$(ls "$d" 2>/dev/null | grep -c '\.apk$')
        echo "  APKs present: ${n:-0}"
        if [ "${n:-0}" -gt 0 ]; then
            ls "$d" 2>/dev/null | grep '\.apk$' | head -10 | sed 's/^/    /'
        fi
    else
        echo "  DOES NOT EXIST"
    fi
    DW=no; [ -w "$d" ] && DW=yes
    echo "  DAC writable (test -w): $DW"
    echo "  NOTE: test -w ignores SELinux and can lie on an ro mount; see section 3 and --test-write."
done
for d in /system/overlay /oem/overlay /system/etc/overlay; do
    [ -d "$d" ] && echo "  (exists but NOT scanned by Android 9: $d)"
done

say "3. MOUNT STATE: which partition holds each dir, and is it ro or rw? (decisive read-only answer)"
if [ -r /proc/mounts ]; then
    echo "  mounts that matter:"
    while read -r dev mp fs op rest; do
        case "$mp" in
            /|/vendor|/product|/system|/data|/system/vendor|/system/product)
                printf '    %s on %s type %s (%s)\n' "$dev" "$mp" "$fs" "$op";;
        esac
    done < /proc/mounts
else
    try mount
fi
# pure-shell longest-prefix mount resolution: toybox awk rejects the one-liner form, and the guest
# runs toybox, so this must not depend on GNU awk.
containing_mount() {
    d=$1; bl=-1; res=""
    while read -r dev mp fs op rest; do
        plen=0
        if [ "$mp" = "/" ]; then
            plen=1
        else
            case "$d" in
                "$mp"|"$mp"/*) plen=${#mp} ;;
            esac
        fi
        if [ "$plen" -gt "$bl" ]; then
            bl=$plen
            res="$mp|$dev|$fs|$op"
        fi
    done < /proc/mounts
    echo "$res"
}
if [ -r /proc/mounts ]; then
    for d in "$VDIR" "$PDIR" /system/framework /data/resource-cache; do
        m=$(containing_mount "$d")
        if [ -z "$m" ]; then
            printf '  %-22s no mount entry resolves to it\n' "$d"
            continue
        fi
        mp=$(echo "$m" | cut -d'|' -f1); dev=$(echo "$m" | cut -d'|' -f2)
        fs=$(echo "$m" | cut -d'|' -f3);  op=$(echo "$m" | cut -d'|' -f4)
        ST="flags unclear ($op)"
        case ",$op," in
            *,ro,*) ST="READ-ONLY";;
            *,rw,*) ST="read-write";;
        esac
        ex=""
        [ -e "$d" ] || ex="   (path does not exist yet; the mount shown is where it WOULD live)"
        printf '  %-22s -> on %-14s %-6s %-20s %s%s\n' "$d" "$mp" "$fs" "$dev" "$ST" "$ex"
    done
    printf '  overlayfs supported by the kernel? '
    if grep -qw overlay /proc/filesystems 2>/dev/null; then
        echo "yes (a bind/overlayfs approach is technically possible with root)"
    else
        echo "NO - no 'overlay' line in /proc/filesystems, so overlayfs writes to /vendor are out"
    fi
else
    echo "  /proc/mounts not readable - use --test-write in section 4 to measure writability instead"
fi

say "4. WRITABILITY, MEASURED (only with --test-write)"
if [ $TEST_WRITE -eq 0 ]; then
    echo "  SKIPPED - creating a file is a write. Re-run with --test-write to measure it."
else
    for d in "$VDIR" "$PDIR"; do
        if [ ! -d "$d" ]; then
            echo "  $d absent, nothing to test"
            continue
        fi
        f="$d/.qoder-write-probe.tmp"
        err=$( (echo probe > "$f") 2>&1 )
        if [ -z "$err" ] && [ -f "$f" ]; then
            sync 2>/dev/null
            echo "  $d WRITABLE (created the probe file)"
            if rm -f "$f" 2>/dev/null; then echo "    removed again: yes"; else echo "    REMOVE FAILED: $f still exists"; fi
        else
            echo "  $d NOT WRITABLE: ${err:-refused, no message}"
            rm -f "$f" 2>/dev/null
        fi
    done
fi

say "5. DOES THIS GUEST ALREADY RUN STATIC RROs? (existence of the mechanism, not theory)"
if have pm; then
    echo '$ pm list packages -s -f | grep -i overlay'
    pm list packages -s -f 2>/dev/null | grep -i overlay | head -20 | sed 's/^/  /'
    c=$(pm list packages -s 2>/dev/null | grep -ci overlay)
    echo "  system packages whose name contains 'overlay': ${c:-0}"
    echo "  > 0 means PMS accepts overlay packages from a system partition on THIS image."
else
    echo "  pm not available in this shell"
fi
echo ""
echo "  idmap binary (PMS calls it through installd, PackageManagerService.java:832-834):"
found_idmap=0
for b in /system/bin/idmap /system/bin/idmap2 /vendor/bin/idmap; do
    out=$(ls -ld "$b" 2>&1)
    case "$out" in
        *"No such file"*)
            printf '    %-24s absent\n' "$b";;
        *"Permission denied"*|*"not permitted"*|*"denied"*)
            printf '    %-24s present but this uid cannot stat it - re-run as root to confirm\n' "$b"
            found_idmap=2;;
        *)
            printf '    %s\n' "$out"
            found_idmap=1;;
    esac
done
if [ $found_idmap -eq 0 ]; then
    echo "    NO idmap anywhere on this image. Without it a static RRO can NEVER take effect:"
    echo "    PMS logs 'Failed to generate idmap for ...' (:839-841) and skips the overlay silently."
elif [ $found_idmap -eq 2 ]; then
    echo "    (existence unconfirmed for this uid, but the 15 loaded overlays above prove idmap works)"
fi
echo "  /data/resource-cache holds ONE .idmap per ACCEPTED overlay - listing it is the direct proof"
echo "  that idmap assignment works on this image (needs root):"
if ls /data/resource-cache >/dev/null 2>&1; then
    ls -l /data/resource-cache/ 2>/dev/null | head -12 | sed 's/^/    /'
    echo "    idmap files:"
    find /data/resource-cache -name '*idmap*' 2>/dev/null | head -10 | sed 's/^/      /'
else
    echo "    not readable from this uid (normal without root) - re-run as root to see it"
fi
echo "  boot-log evidence, if the buffer still has it:"
( (dmesg 2>/dev/null; logcat -d 2>/dev/null) | grep -iE "idmap|overlay" | head -12 | sed 's/^/    /' )
echo "  the line to look for is 'Failed to generate idmap for <apk>' (:839-841). Its ABSENCE together"
echo "  with a populated /data/resource-cache = the mechanism is healthy on this image."

say "6. WEBVIEW STATE RIGHT NOW (the pre-install baseline to diff afterwards)"
if have dumpsys; then
    try dumpsys webviewupdate
else
    echo "  dumpsys unavailable"
fi
echo "  what the lines mean (from source, so you can read the output yourself):"
echo "    'Current WebView package (name, version)'  - the provider in use (WebViewUpdater:529)"
echo "    'Minimum WebView version code'             - gate 4, computed from the factory package (:533)"
echo "    'WebView packages:' + 'Valid/Invalid/NOT installed' - the EFFECTIVE provider list, i.e. the"
echo "      overlaid resource as the framework sees it (:557-590). The overlay working at all is"
echo "      PROVEN when com.google.android.webview appears in this list and did not before."
echo "    'Fallback logic enabled: true' (default, SystemImpl:212-216) - with an isFallback entry in"
echo "      the list, the platform will DISABLE that provider once another valid one exists."
echo "  MEASURED CAVEAT: as a non-root uid this prints"
echo "      'Permission Denial: can't dump WebViewUpdateService ... missing android.permission.DUMP'"
echo "  (observed on the Android 9 host). If you see that, this section needs root, e.g. 'su -c'."
echo "  A no-root alternative: any app that shows its own WebView user agent reports the Chrome/WebView"
echo "  version in use (navigator.userAgent), which proves the selected provider independently."
if [ $EXTRACT -eq 1 ]; then
    mkdir -p "$ODIR" 2>/dev/null
    b="$ODIR/webviewupdate-before.txt"
    if dumpsys webviewupdate > "$b" 2>&1; then
        echo "  saved baseline: $b ($(wc -c < "$b" 2>/dev/null | tr -d ' \n') bytes)"
    else
        echo "  could not write $ODIR"
    fi
else
    echo "  saved baseline SKIPPED (it is a write) - re-run with --extract, or redirect the output yourself"
fi

say "7. FACTORY WEBVIEW PACKAGE (must stay untouched; we only READ it)"
if have pm; then
    for pkg in com.android.webview com.google.android.webview; do
        printf '\n  --- %s ---\n' "$pkg"
        pm path "$pkg" 2>/dev/null | sed 's/^/    codePath: /'
        pm list packages -i 2>/dev/null | grep -F "$pkg" | sed 's/^/    /'
        dumpsys package "$pkg" 2>/dev/null | grep -E "versionCode|versionName|enabled|installed|flags|Signature" | head -8 | sed 's/^/    /'
    done
fi
echo "  expected: com.android.webview 81.0.4044.117 at /system/app/webview/webview.apk, enabled,"
echo "  a system app. Do NOT disable, uninstall-update or touch that file."

say "8. THE FILES TO EXTRACT (sizes + checksums measured here, to compare against what I receive)"
for f in /system/framework/framework-res.apk /system/build.prop; do
    printf '  %-42s ' "$f"
    if [ -r "$f" ]; then
        printf '%s bytes' "$(wc -c < "$f" 2>/dev/null | tr -d ' \n')"
        if have sha256sum; then
            printf '  sha256=%s' "$(sha256sum "$f" 2>/dev/null | cut -c1-64)"
        else
            printf '  (no sha256sum in this shell)'
        fi
        printf '\n'
    else
        echo "not readable from this uid"
    fi
done
if [ $EXTRACT -eq 1 ]; then
    o="$ODIR/config_webview_packages.xml"
    err=$( (unzip -p /system/framework/framework-res.apk res/xml/config_webview_packages.xml > "$o") 2>&1 )
    sz=0
    [ -f "$o" ] && sz=$(wc -c < "$o" 2>/dev/null | tr -d ' \n')
    if [ "${sz:-0}" -gt 0 ]; then
        echo "  wrote $o ($sz bytes) - send that file back, it is only a few KB"
        if have sha256sum; then sha256sum "$o" | sed 's/^/    /'; fi
    else
        rm -f "$o" 2>/dev/null
        echo "  automatic extract failed${err:+ ($err)} - use MiXplorer instead"
        echo "  (the entry lives INSIDE the APK: framework-res.apk > res/xml/config_webview_packages.xml)"
    fi
else
    echo "  automatic extraction SKIPPED (it writes a file) - re-run with --extract, or use MiXplorer"
fi

say "9. IS MAGISK HERE? (the Magisk-module plan depends entirely on this answer)"
# WHY THIS IS NOT JUST "[ -d /data/adb ]": /data is 0771 + SELinux, so a non-root shell gets EACCES for
# a directory that exists AND for one that was never created. Reporting "no Magisk" from that would be
# a guess. classify() separates PROVEN-ABSENT from NOT-LOOKABLE using the errno the kernel returned.
classify() {   # $1 = path  -> PRESENT / ABSENT / NOINFO
    _m=$(stat -c '%F' "$1" 2>&1)
    case "$_m" in
        *directory*)   echo PRESENT ;;
        *"No such file"*) echo ABSENT ;;
        *)             echo NOINFO ;;
    esac
}
adb_state=$(classify /data/adb)
echo "  as uid $(id -u 2>/dev/null): /data/adb is $adb_state (PRESENT/ABSENT/NOINFO)"
echo "  the ROM package declares a Magisk plugin of its own:"
echo "    manifest.json -> magisk_uri = asset:///plugins/magisk.zip?h=true"
echo "  so Virtual Master ships Magisk, but WHICH build, and whether it is enabled in this guest, is"
echo "  only answerable from inside the guest. Everything below is a read."
if [ "$adb_state" = PRESENT ]; then
    echo "  /data/adb exists:"
    ls -ld /data/adb 2>/dev/null | sed 's/^/    /'
    ls -1 /data/adb 2>/dev/null | head -20 | sed 's/^/    /'
elif [ "$adb_state" = ABSENT ]; then
    echo "  PROVEN: /data/adb does not exist -> no Magisk-derived tooling is installed/enabled here"
else
    echo "  NOT LOOKABLE from this uid. Re-run as root:  su -c 'sh guest_probe.sh' > probe-root.txt"
    echo "  Until then the Magisk question is OPEN, not answered 'no'."
fi
[ -d /data/adb/modules ] && { echo "  module directory present; modules:"; ls -1 /data/adb/modules 2>/dev/null | sed 's/^/    /'; }
for b in /data/adb/magisk/magisk /sbin/.magisk /dev/.magisk /system/bin/magisk /sbin/magisk; do
    [ -e "$b" ] && printf '    %-28s exists\n' "$b"
done
if command -v magisk >/dev/null 2>&1; then
    printf '    magisk -v : '; magisk -v 2>&1 | head -1
    printf '    magisk -V : '; magisk -V 2>&1 | head -1
    echo "    magisk --status:"; magisk --status 2>&1 | head -10 | sed 's/^/      /'
else
    echo "    'magisk' is not on PATH (normal: it lives in /data/adb/magisk or is app-only)"
fi
echo "  su: $(command -v su || echo none)"
echo "  magisk-related packages:"
pm list packages 2>/dev/null | grep -iE 'magisk|topjohnwu|kernelsu' | sed 's/^/    /'
echo "  props mentioning magisk:"
getprop 2>/dev/null | grep -i magisk | head -5 | sed 's/^/    /'
echo "  SELinux mode (a permissive guest makes an RRO/idmap problem less likely, not less dangerous):"
getenforce 2>/dev/null | sed 's/^/    /'
echo "  does an ALREADY-MOUNTED module file exist anywhere under /vendor or /product?"
ls -l /data/adb/modules/*/system 2>/dev/null | head -20 | sed 's/^/    /'
echo "  the decisive question for Option A is answered by these two lines:"
printf '    /data/adb/modules : %s\n' "$([ -d /data/adb/modules ] && echo PRESENT || echo ABSENT)"
printf '    magisk version     : %s\n' "$(command -v magisk >/dev/null 2>&1 && magisk -v 2>&1 | head -1 || echo 'unknown - install Magisk first')"

say "10. VERDICT LINES (copy these back with the full output)"
V=0; [ -d "$VDIR" ] && V=1
P=0; [ -d "$PDIR" ] && P=1
RWV=no; [ -w "$VDIR" ] && RWV=yes
RWP=no; [ -w "$PDIR" ] && RWP=yes
OP=$(pm list packages -s 2>/dev/null | grep -ci overlay)
IDB=absent
[ "${found_idmap:-0}" -eq 1 ] && IDB=present
[ "${found_idmap:-0}" -eq 2 ] && IDB=unknown-need-root
RC=unreadable; ls /data/resource-cache >/dev/null 2>&1 && RC=readable
OFS=no; grep -qw overlay /proc/filesystems 2>/dev/null && OFS=yes
CUR=$( (dumpsys webviewupdate 2>/dev/null | grep -m1 'Current WebView package') | tr -d '\n')
echo "PROBE_SCANNED_DIRS_EXIST vendor_overlay=$V product_overlay=$P"
echo "PROBE_DAC_WRITABLE vendor_overlay=$RWV product_overlay=$RWP"
echo "PROBE_MEASURED_WRITE=$([ $TEST_WRITE -eq 0 ] && echo 'not tested (read-only run)' || echo 'see section 4')"
echo "PROBE_BUILD_TYPE=$(getprop ro.build.type 2>/dev/null)"
echo "PROBE_DEBUGGABLE=$(getprop ro.debuggable 2>/dev/null)"
echo "PROBE_ABILIST32=$(getprop ro.product.cpu.abilist32 2>/dev/null)"
echo "PROBE_OVERLAY_PKGS=${OP:-0}"
echo "PROBE_IDMAP_BINARY=$IDB"
echo "PROBE_RESOURCE_CACHE=$RC"
echo "PROBE_OVERLAYFS_IN_KERNEL=$OFS"
echo "PROBE_FALLBACK_ENABLED=$(settings get global webview_fallback_logic_enabled 2>/dev/null)"
echo "PROBE_CURRENT_PROVIDER=$CUR"
echo "PROBE_MAGISK_DATA_ADB=$adb_state"
echo "PROBE_MAGISK_MODULES_DIR=$(classify /data/adb/modules)"
echo "PROBE_MAGISK_MODULES=$(ls -1 /data/adb/modules 2>/dev/null | tr '\n' ' ')"
echo "PROBE_MAGISK_VERSION=$(command -v magisk >/dev/null 2>&1 && magisk -v 2>/dev/null | head -1)"
# A su BINARY IS NOT ROOT: it is present here (Termux's shim) while the shell is uid 10180. Root is
# proven only by id -u going to 0, so report both and let the reader tell them apart.
echo "PROBE_SU=$(command -v su >/dev/null 2>&1 && echo present || echo absent) (binary only - not proof)"
echo "PROBE_UID=$(id -u 2>/dev/null)"
echo "PROBE_ENFORCE=$(getenforce 2>/dev/null)"
echo
echo "Nothing was installed, enabled, mounted, deleted or rebooted by this script."
[ $TEST_WRITE -eq 1 ] && echo "Except: section 4 created and deleted one dot-file per scanned overlay directory."
[ $EXTRACT -eq 1 ]    && echo "Except: sections 6 and 8 wrote files under $ODIR only."
exit 0

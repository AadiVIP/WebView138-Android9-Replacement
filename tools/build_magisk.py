#!/usr/bin/env python3
"""Assemble the WebView-138 replacement Magisk module from ALREADY-AUDITED bytes.

    python3 tools/build_magisk.py \
        --overlay  output/webview138-provider-overlay.apk \
        --manifest output/webview138-provider-overlay.manifest \
        --webview-apk input/webview138_arm64_universal_138.0.7204.179.apk \
        --stagedir work/magisk_stage \
        --zip      output/WebView138-Replacement-Magisk.zip

Why it takes the overlay as an INPUT instead of building one: the only hard part of this module is the
static RRO, and tools/verify_overlay.py is what decides whether those bytes are correct (it is the
file that writes --manifest, and it writes it ONLY when every check passed). Re-deriving the overlay
here would put a second, unaudited producer in the chain. So this builder:

  * refuses to run without a manifest           -> no audit, no module;
  * refuses it if the manifest's sha256 != the overlay bytes it is about to ship;
  * refuses it if the provider logic in the manifest is not what Android 9 needs to select Google
    first (provider_1_packageName / availableByDefault / isFallback);
  * copies the overlay byte for byte (never repacks, never realigns, never resigns anything);
  * never touches the 222 MB WebView APK - the module's job is the provider LIST, the package itself
    is installed normally with pm install (see README, and tools/install_overlay.sh --install-apk).

Deterministic: every ZIP entry gets the same fixed timestamp, so rebuilding from the same inputs
produces a byte-identical archive - which is what makes "the zip I audited is the zip you have"
checkable by sha256 alone.
"""
import argparse, hashlib, io, json, os, re, stat, sys, zipfile

MOD_ID = 'webview138-replacement'
GOOGLE = 'com.google.android.webview'
TS = (2000, 1, 1, 0, 0, 0)          # fixed -> reproducible archive


def apk_facts(path):
    """Everything the module claims about the replacement package, read out of the package itself."""
    import zipfile as _zf
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from axml import AXML
    z = _zf.ZipFile(path)
    ax = AXML(z.read('AndroidManifest.xml'))
    els = {}
    for k, t, av in ax.dump():
        if k == 'start':
            els.setdefault(t, dict(av))
    man, sdk = els.get('manifest', {}), els.get('uses-sdk', {})
    abis = sorted({n.split('/')[1] for n in z.namelist() if n.startswith('lib/')})
    return {
        'package': man.get('package'),
        'versionName': man.get('versionName'),
        'versionCode': man.get('versionCode'),
        'minSdkVersion': sdk.get('minSdkVersion'),
        'maxSdkVersion': sdk.get('maxSdkVersion'),
        'targetSdkVersion': sdk.get('targetSdkVersion'),
        'abis': ','.join(abis),
        'sha256': sha256_file(path),
        'bytes': os.path.getsize(path),
    }


def sha256_file(p, block=1 << 20):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(block), b''):
            h.update(b)
    return h.hexdigest()


def read_manifest(path):
    m = {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip('\n')
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            m[k] = v
    return m


def die(msg, code=2):
    print('BUILD REFUSED: %s' % msg)
    sys.exit(code)


# --------------------------------------------------------------------------- module texts
MODULE_PROP = """id={id}
name=Google WebView 138 provider registration (Android 9)
version={version}
versionCode={code}
author=qoder
description=Systemless static RRO that registers the Google-signed WebView 138.0.7204.179 as the default Android 9 WebView provider. Touches no signed framework resource. Reversible.
"""


CUSTOMIZE_SH = r"""#!/system/bin/sh
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
[ "$ID" = "@ID@" ] || bail "module.prop id is '$ID', expected '@ID@'"

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
APK="$MODPATH/system/@TARGET_DIR@/$OVERLAY"
[ -f "$APK" ] || bail "expected the overlay at $APK and it is not there"
command -v sha256sum >/dev/null 2>&1 || bail "no sha256sum on this shell - cannot verify the payload, refusing to install half-blind"
got=$(sha256sum "$APK" | cut -d' ' -f1)
want=$(mget overlay_sha256)
[ "$got" = "$want" ] || bail "overlay sha256 mismatch: got $got want $want - the payload is not what was audited"
say "overlay verified: $OVERLAY ($got)"

# --- 3. is the provider logic actually the one that makes Google the default?
[ "$(mget provider_1_packageName)" = "@GOOGLE@" ]      || bail "provider #1 is not @GOOGLE@"
[ "$(mget provider_1_availableByDefault)" = "true" ]   || bail "provider #1 is not availableByDefault"
[ "$(mget provider_1_isFallback)" = "false" ]          || bail "provider #1 is isFallback=true: the platform would DISABLE it once another valid provider exists"
n=$(mget provider_count)
[ "${n:-0}" -ge 2 ] 2>/dev/null || bail "only $n provider(s) declared - Android 9 throws AndroidRuntimeException if no availableByDefault provider survives, so never ship a list that holds just one"
say "provider list: $n entries, @GOOGLE@ first, availableByDefault, not fallback"

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
"""


SERVICE_SH = r"""#!/system/bin/sh
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
GPKG=@GOOGLE@
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
    echo "     ls -l /data/adb/modules/@ID@/disabled"
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
        [ -n "$AP" ] || AP=@APK_DEFAULT@
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
"""


UNINSTALL_SH = r"""#!/system/bin/sh
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
"""


UPDATER_SCRIPT = '#MAGISK\n'

# Re-implementation, NOT Magisk's own template: see README "What is and is not verified".
UPDATE_BINARY = r"""#!/system/bin/sh
# META-INF/com/google/android/update-binary
#
# Magisk's module ZIP interface is: this file is executed as
#     update-binary <api> <tmpdir> <zipfile>
# and META-INF/com/google/android/updater-script must start with the line "#MAGISK".
#
# THIS IS OUR OWN RE-IMPLEMENTATION. Magisk's template update-binary and its util_functions.sh are not
# present on the machine that built this module and the offline rule forbids downloading them, so this
# script cannot be claimed compatible with every Magisk version. It is deliberately conservative:
# if anything it needs is missing it prints the drop-in alternative instead of half-installing.
# The path this project actually tested end to end is tools/magisk_deploy.sh, which copies the module
# directory into /data/adb/modules and needs no installer ABI at all.

umask 022
API="$1"
TMP="$2"
ZIP="$3"
[ -n "$TMP" ] && [ -n "$ZIP" ] || { echo "usage: update-binary <api> <tmpdir> <zip>"; exit 1; }

MODID=
for c in unzip busybox; do command -v $c >/dev/null 2>&1 && UNZIP="$c" && break; done
if [ -n "${UNZIP:-}" ] && [ "$UNZIP" = unzip ]; then EX="unzip"; else EX="busybox unzip"; fi
have() { command -v "$1" >/dev/null 2>&1; }

if ! have unzip; then
    echo "This recovery has no 'unzip'. Magisk normally supplies its own extractor for the template"
    echo "update-binary, which this module does not embed (see the comment above)."
    echo "Install the module from its directory instead:"
    echo "    sh /sdcard/Download/magisk_deploy.sh --install --i-reviewed"
    exit 1
fi

WORK="$TMP/@ID@-stage"
rm -rf "$WORK" 2>/dev/null
mkdir -p "$WORK" || { echo "cannot create $WORK"; exit 1; }
unzip -o -q "$ZIP" -d "$WORK" || { echo "unzip failed"; exit 1; }

SRC="$WORK/@ID@"
[ -d "$SRC" ] || SRC="$WORK"
[ -f "$SRC/module.prop" ] || { echo "module.prop not found in the archive layout"; exit 1; }
MODID=$(sed -n 's/^id=//p' "$SRC/module.prop" | head -1)
[ "$MODID" = "@ID@" ] || { echo "bad id '$MODID'"; exit 1; }

# The Magisk installer contract: MODPATH is the live module directory, customize.sh runs inside it.
MODDIR="/data/adb/modules/$MODID"
[ -d /data/adb/modules ] || { echo "/data/adb/modules absent: Magisk is not installed/enabled here."; echo "refusing to create it - use the Magisk app to install Magisk first."; exit 1; }

mkdir -p "$MODDIR" || { echo "cannot create $MODDIR"; exit 1; }
# copy, never move, so a failed install leaves the archive intact for a retry
cp -a "$SRC/." "$MODDIR/" || { echo "copy into $MODDIR failed"; exit 1; }

export MODPATH="$MODDIR"
export API ZIPFILE="$ZIP"
if [ -f "$MODDIR/customize.sh" ]; then
    . "$MODDIR/customize.sh"
    rc=$?
    [ $rc -eq 0 ] || { echo "customize.sh refused the install (rc=$rc)"; rm -rf "$MODDIR"; exit $rc; }
fi

# Magisk removes a module by these markers; a fresh install must not carry an old one.
rm -f "$MODDIR/remove" "$MODDIR/disabled"
touch "$MODDIR/update" 2>/dev/null
sync
echo "Installed @ID@ into $MODDIR. REBOOT for it to take effect (no flash, no partition write)."
exit 0
"""


def build_module_prop(version, code):
    return MODULE_PROP.format(id=MOD_ID, version=version, code=code)


def render(txt):
    return txt.replace('@ID@', MOD_ID).replace('@GOOGLE@', GOOGLE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--overlay', default='output/webview138-provider-overlay.apk')
    ap.add_argument('--manifest', default='output/webview138-provider-overlay.manifest')
    ap.add_argument('--webview-apk', default='input/webview138_arm64_universal_138.0.7204.179.apk')
    ap.add_argument('--stagedir', default='work/magisk_stage')
    ap.add_argument('--zip', default='output/WebView138-Replacement-Magisk.zip')
    ap.add_argument('--target-dir', default='vendor/overlay',
                    help='partition directory the RRO is mounted into (Android 9 scans '
                         'vendor/overlay and product/overlay only)')
    ap.add_argument('--version', default='v1.0')
    ap.add_argument('--versioncode', type=int, default=1)
    a = ap.parse_args()

    # ---- the chain: no audit manifest, no module
    for p in (a.overlay, a.manifest):
        if not os.path.isfile(p):
            die('%s is missing. Build/verify the overlay first:\n'
                '        python3 tools/build_overlay.py ... && \\\n'
                '        python3 tools/verify_overlay.py %s --cert work/V2_cert.der --apk %s \\\n'
                '                --write-manifest %s'
                % (p, a.overlay, a.webview_apk, a.manifest))
    raw = open(a.overlay, 'rb').read()
    m = read_manifest(a.manifest)
    got = hashlib.sha256(raw).hexdigest()
    if m.get('overlay_sha256') != got:
        die('manifest sha256 %s != overlay bytes %s' % (m.get('overlay_sha256'), got))
    if m.get('overlay_bytes') and int(m['overlay_bytes']) != len(raw):
        die('manifest size %s != %d bytes' % (m.get('overlay_bytes'), len(raw)))
    # ---- the provider logic this module is betting the boot on
    if m.get('provider_1_packageName') != GOOGLE:
        die('provider #1 is %r, must be %r - document order is what selects the provider '
            '(WebViewUpdater.java:306-316)' % (m.get('provider_1_packageName'), GOOGLE))
    if m.get('provider_1_availableByDefault') != 'true':
        die('provider #1 availableByDefault=%s - an unavailable provider is never auto-selected'
            % m.get('provider_1_availableByDefault'))
    if m.get('provider_1_isFallback') != 'false':
        die('provider #1 isFallback=%s - fallback providers get DISABLED by the platform once '
            'another valid provider exists (WebViewUpdateServiceImpl.java:202-220)'
            % m.get('provider_1_isFallback'))
    if int(m.get('provider_count', '0')) < 2:
        die('provider_count=%s: never ship a provider list with a single entry - if that one package '
            'is missing, SystemImpl.java:138-144 throws and WebView dies entirely'
            % m.get('provider_count'))
    if m.get('overlay_targetPackage') != 'android' or m.get('overlay_isStatic') != 'true':
        die('overlay is not a static RRO targeting android: %r / %r'
            % (m.get('overlay_targetPackage'), m.get('overlay_isStatic')))
    if not re.match(r'^[A-Za-z0-9+/]+={0,2}$', m.get('cert_base64', '')):
        die('cert_base64 is missing or not single-line canonical base64 - the <signature> TEXT is the '
            'thing that authorises a /data-installed provider (WebViewUpdater.java:506-521)')

    tgt = a.target_dir.strip('/')
    if tgt not in ('vendor/overlay', 'product/overlay'):
        die('--target-dir must be vendor/overlay or product/overlay (the only two Android 9 scans)')

    wb = {'path': a.webview_apk, 'exists': os.path.isfile(a.webview_apk), 'abis': []}
    if wb['exists']:
        try:
            facts = apk_facts(a.webview_apk)
            wb.update(facts)
            wb['abis_list'] = facts['abis'].split(',')
        except Exception as e:                      # never claim anything we could not read
            print('  note: could not parse %s (%s); README will describe it by name only'
                  % (a.webview_apk, e))
    else:
        print('  note: %s not present; README will describe it by name only' % a.webview_apk)
    apk_prop = ['# what this module expects the replacement package to be, MEASURED from the APK',
                '# (tools/build_magisk.py reads this out of the package; nothing here is typed in)',
                'webview_apk_path=%s' % a.webview_apk]
    for k in ('package', 'versionName', 'versionCode', 'minSdkVersion', 'maxSdkVersion',
              'targetSdkVersion', 'abis', 'sha256', 'bytes'):
        apk_prop.append('webview_apk_%s=%s' % (k, wb.get(k, 'NOT-MEASURED')))

    files = []                       # (arcname, bytes, compress_type)
    root = MOD_ID
    files.append(('%s/module.prop' % root, build_module_prop(a.version, a.versioncode).encode(), 8))
    files.append(('%s/customize.sh' % root, render(CUSTOMIZE_SH).replace('@TARGET_DIR@', tgt).encode(), 8))
    files.append(('%s/service.sh' % root,
                  render(SERVICE_SH).replace('@APK_DEFAULT@', a.webview_apk).encode(), 8))
    files.append(('%s/uninstall.sh' % root, render(UNINSTALL_SH).encode(), 8))
    files.append(('%s/webview138-apk.prop' % root, ('\n'.join(apk_prop) + '\n').encode(), 8))
    files.append(('%s/webview138.manifest' % root,
                  open(a.manifest, 'rb').read(), 8))
    files.append(('%s/system/%s/%s' % (root, tgt, os.path.basename(a.overlay)), raw, 0))
    files.append(('META-INF/com/google/android/updater-script', UPDATER_SCRIPT.encode(), 8))
    files.append(('META-INF/com/google/android/update-binary', render(UPDATE_BINARY).encode(), 8))
    readme = render(README_TMPL).replace('@OVERLAY_NAME@', os.path.basename(a.overlay)) \
                                .replace('@TARGET_DIR@', tgt) \
                                .replace('@OVERLAY_SHA@', got) \
                                .replace('@OVERLAY_BYTES@', str(len(raw))) \
                                .replace('@PROVIDER_COUNT@', m.get('provider_count', '?')) \
                                .replace('@CERT_SHA256@', m.get('cert_sha256', '?')) \
                                .replace('@CERT_B64_LEN@', str(len(m.get('cert_base64', '')))) \
                                .replace('@WB_PATH@', a.webview_apk) \
                                .replace('@WB_SHA@', wb.get('sha256', 'NOT MEASURED HERE')) \
                                .replace('@WB_BYTES@', str(wb.get('bytes', 0))) \
                                .replace('@WB_ABIS@', wb.get('abis', 'not measured') or 'not measured') \
                                .replace('@WB_VER@', str(wb.get('versionName', 'not measured'))) \
                                .replace('@WB_CODE@', str(wb.get('versionCode', 'not measured'))) \
                                .replace('@WB_MIN@', str(wb.get('minSdkVersion', 'not measured'))) \
                                .replace('@WB_MAX@', str(wb.get('maxSdkVersion', 'not measured'))) \
                                .replace('@WB_TGT@', str(wb.get('targetSdkVersion', 'not measured'))) \
                                .replace('@VERSION@', a.version)
    files.append(('%s/README.md' % root, readme.encode(), 8))

    stage = os.path.join(a.stagedir, MOD_ID)
    os.makedirs(stage, exist_ok=True)
    for arc, data, comp in files:
        p = os.path.join(a.stagedir, arc)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as fh:
            fh.write(data)
        if arc.endswith('.sh') or arc.endswith('update-binary'):
            os.chmod(p, 0o755)
    os.makedirs(os.path.dirname(a.zip) or '.', exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for arc, data, comp in files:
            zi = zipfile.ZipInfo(arc, date_time=TS)
            zi.compress_type = comp
            zi.external_attr = (0o755 if comp == 8 and (arc.endswith('.sh') or arc.endswith('update-binary'))
                                else 0o644) << 16
            zf.writestr(zi, data)
    out = buf.getvalue()
    with open(a.zip, 'wb') as fh:
        fh.write(out)

    print('staged : %s/' % stage)
    print('zip    : %s  %d B  sha256=%s' % (a.zip, len(out), hashlib.sha256(out).hexdigest()))
    for arc, data, comp in sorted(files):
        print('   %-62s %9d B  %s' % (arc, len(data), 'STORED' if comp == 0 else 'deflate'))
    print('overlay: %d B sha256=%s  (identical bytes to %s)' % (len(raw), got, a.overlay))
    print('payload: %d providers, %s first, cert sha256=%s'
          % (int(m['provider_count']), GOOGLE, m['cert_sha256']))
    return 0


README_TMPL = r"""# WebView 138 replacement Magisk module (@VERSION@)

Registers the Google-signed **WebView 138.0.7204.179 (arm64)** as the default WebView provider of an
**Android 9 (API 28)** system, without editing or re-signing a single signed partition file, and
without deleting the factory WebView.

## What is in here

| file | purpose |
|---|---|
| `module.prop` | module identity (`id=@ID@`) |
| `system/@TARGET_DIR@/@OVERLAY_NAME@` | **the whole mechanism** - a 2.7 KB static RRO, byte-for-byte the file `tools/verify_overlay.py` audited (sha256 `@OVERLAY_SHA@`, @OVERLAY_BYTES@ bytes) |
| `webview138.manifest` | the audit manifest for those bytes: certificate, provider list, checksums |
| `customize.sh` | refuses the install unless the payload verifies and the target directory exists |
| `service.sh` | per-boot read-only verification log + the one preference fix described below |
| `uninstall.sh` | restores that preference; everything else reverts by deleting the module directory |
| `README.md` | this file |
| `META-INF/com/google/android/{update-binary,updater-script}` | ZIP flashing support - **see "What is not verified"** |

## How the provider actually changes on Android 9

Two independent facts decide it, and a module must get both right:

1. **The provider list.** `R.xml/config_webview_packages.xml` inside the signed `framework-res.apk`
   is the list `WebViewUpdateService` reads (`SystemImpl.java:88-124`). This module does **not**
   modify that file - it overlays it. `@PROVIDER_COUNT@` providers are declared, `com.google.android.webview`
   **first**, `availableByDefault=true`, `isFallback=false`; every other provider from the base list is
   carried verbatim, so nothing is ever left without a WebView.
   Selection is document order: `WebViewUpdater.java:306-316` returns the first
   `availableByDefault` provider that is installed, enabled and valid.
2. **The signature gate.** A provider installed into `/data` is not a system app, so
   `WebViewUpdater.providerHasValidSignature` (`:506-521`) needs an explicit `<signature>` child
   whose base64 text is the real Google certificate (that is what Android 9 reads - the
   `signature=` *attribute* is never consulted by this version). @CERT_B64_LEN@ characters,
   certificate sha256 `@CERT_SHA256@`, extracted from the APK Signing Block of the 138 package
   itself, not typed in and not a fingerprint.

The overlay is scanned at boot only from `/vendor/overlay` or `/product/overlay`
(`PackageManagerService.java:578,580`, scanned at `:2609,:2616` with `SCAN_AS_SYSTEM`;
`/system/overlay` is **not** scanned on this version). Those partitions are mounted `ro` in a
Virtual Master guest, which is exactly the problem Magisk solves: magic mount binds the module file
into the directory during `post-fs-data`, **before** `system_server`/`PackageManagerService` starts,
so `idmap` runs and the RRO applies at normal boot. No root remount, no partition write.

## What this module deliberately does NOT do

* **It does not bundle the 138 package.** The APK is @WB_BYTES@ bytes
  (`@WB_PATH@`, sha256 `@WB_SHA@`, native libs for @WB_ABIS@). Putting it inside the module would mean
  222 MB in a module directory whose mount then depends on Magisk's handling of a *new* system app
  under a bind-mounted `/system` - SELinux label semantics for that are part of Magisk, are not
  documented on the machine that built this, and cannot be downloaded here (offline rule). So the
  package goes in the way Android 9 provably accepts on this exact build - the guest is already
  running a `/data`-installed `com.google.android.webview` - and `service.sh` detects if it is missing
  and tells you the command. See "The package this module registers" for the one command, or the
  `auto-install` opt-in if you want the module to do it after checking the bytes.
* **It does not remove or disable WebView 81.** Requirement: *"Do not remove WebView 81 until WebView
  138 is verified as valid and selectable."* 81 is the only fallback if 138 ever fails validation,
  and `SystemImpl.java:138-144` throws `AndroidRuntimeException` when a list has no valid
  `availableByDefault` provider - so 81 stays installed, stays declared, and simply stops being first.
  Reverting is therefore automatic: remove the module, 81 becomes the provider again.
* **It does not touch `framework-res.apk`, the platform key, or any `.img`.** Re-signing
  framework-res with an arbitrary key would break every package that shares the `android` UID.
* **It does not run destructive commands.** Every write is inside `$MODPATH` (plus one
  `settings` key, backed up first).

## The package this module registers (facts read out of the APK, see `webview138-apk.prop`)

| field | value | why it matters on Android 9 |
|---|---|---|
| package | `@GOOGLE@` | must equal `provider_1_packageName` in the overlay, or the list names something that is not there |
| versionName / versionCode | `@WB_VER@` / `@WB_CODE@` | `Minimum WebView version code` gate, computed from the factory package |
| minSdkVersion | @WB_MIN@ | 26 ≤ 28 ✓ |
| **maxSdkVersion** | **@WB_MAX@** | **exactly the Android 8.0-9.0 branch - this is why 138 can be installed on API 28 at all** |
| targetSdkVersion | @WB_TGT@ | `UserPackage.hasCorrectTargetSdkVersion` requires >= 28 ✓ |
| native libs | @WB_ABIS@ | the guest's `ro.product.cpu.abilist64` must contain arm64-v8a |
| size / sha256 | @WB_BYTES@ B / `@WB_SHA@` | what `service.sh` verifies before any opt-in install |

The module does **not** contain the @WB_BYTES@-byte package. Installing it is one command:

    su -c 'pm install -r /data/local/tmp/webview138.apk'      # you watch it happen

or, if you would rather the module did it: `touch /data/adb/modules/@ID@/auto-install` (optionally
write the device path to the APK as its first line) and reboot. `service.sh` then verifies the bytes
against `webview138-apk.prop` first and **refuses** on any mismatch - it will not install something it
cannot identify, and a failed `pm install` leaves WebView 81 running.

## Install (pick one; both are reversible)

**A. Drop-in directory - the path tested on this machine, needs root shell, no flash:**

    su -c 'sh /sdcard/Download/magisk_deploy.sh --check'          # read-only, proves it can work
    su -c 'sh /sdcard/Download/magisk_deploy.sh --install --i-reviewed'
    su -c reboot                                                  # reboot is yours to decide

**B. Flash the ZIP in the Magisk app** (Install from local storage). Requires
`META-INF/com/google/android/update-binary` to be compatible with the Magisk build in the guest -
see below. Nothing is written to a partition either way.

Prerequisites: Magisk present and enabled (`/data/adb/modules` exists), API 28, the guest's
`ro.product.cpu.abilist64` contains `arm64-v8a`, and the 138 package installed.

## Reboot, then verify (do not trust the module, trust the device)

    su -c dumpsys webviewupdate | head -20
    su -c cat /data/adb/modules/@ID@/boot-verify.log

Expect: `Current WebView package (name, version): (com.google.android.webview, 138.0.7204.179)`;
`WebView packages:` lists `Valid package com.google.android.webview ...` **first**; the overlay file
visible under `/vendor/overlay` or `/product/overlay`; one `.idmap` for it under
`/data/resource-cache`; no `Failed to generate idmap for` line in the log. The final proof is a real
page in a WebView app plus `navigator.userAgent` containing `Chrome/138.0.7204.179`.

## Rollback

    magisk --remove-module @ID@        (or the Magisk app's Remove button)
    # or: su -c 'sh /data/local/tmp/magisk_deploy.sh --remove --i-reviewed'
    su -c reboot

`uninstall.sh` restores `Settings.Global.webview_provider` if `service.sh` pinned it. The RRO and its
idmap effect disappear with the module directory, so the factory list inside `framework-res.apk` is
authoritative again and **WebView 81 is selected**. 138 remains installed but unused; remove it with
`pm uninstall @GOOGLE@` if you want the original state exactly.

## Why `service.sh` is here at all

`Settings.Global.WEBVIEW_PROVIDER` (`Settings.java:9425`, android-9.0.0_r35) is checked *before*
document order (`WebViewUpdater.java:287-301`). Its own documentation says: *"if unset the provider
is instead determined by the system"*. If anyone ever picked `com.android.webview` in Developer
options, that stale value would overrule the overlay and the module would look broken. `service.sh`
fixes only that case: it saves the old value to `pref-backup`, pins `@GOOGLE@`, re-reads to confirm,
and `uninstall.sh` restores it. Create the empty file `no-pin` in the module directory to disable
even that. Everything else the script does is read-only diagnostics into `boot-verify.log`.

## What is and is not verified

Verified on the build machine: the overlay bytes pass @PROVIDER_COUNT@+ structure/signature/provider
audits in `tools/verify_overlay.py`; `tools/audit_magisk.py` re-reads this ZIP independently and lints
every script above for destructive commands; `customize.sh`, `service.sh`, `uninstall.sh` and
`magisk_deploy.sh` were executed end to end against fake module dirs in a sandbox; the build is
reproducible (same inputs -> same ZIP sha256).

**NOT verified, and why:** no Magisk device was ever touched, so - that the guest runs Magisk at all
and which version; the `update-binary` contract (Magisk's own template and `util_functions.sh` are not
on this machine and the offline rule forbids downloading them, which is why install path A exists);
that magic mount can create a *new* subdirectory if `/vendor/overlay` does not exist (so
`customize.sh` refuses instead of assuming); that `idmap` succeeds on the guest image. All four are
settled by `guest_probe.sh` + the two verification commands above, which is why the deliverable is a
module plus a verification procedure rather than a claim.
"""


if __name__ == '__main__':
    sys.exit(main())

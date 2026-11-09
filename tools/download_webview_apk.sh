#!/system/bin/sh
# download_webview_apk.sh - obtain + VERIFY the exact Google WebView 138 package this project
# was built against, before anything is installed.
#
# WHY A HELPER INSTEAD OF THE FILE ITSELF:
#   "Android System WebView" (com.google.android.webview) is proprietary Google software.
#   It is not open source, it carries no redistribution license, and it is not shipped in this
#   repository or as a release asset. This script is the sanctioned path:
#
#     1. It tells you the ONLY acceptable source class for the exact build: Google Play
#        (canonical, on-device), or a copy you already trust. Third-party mirrors are NOT
#        endorsed by this project; a mirror file is acceptable ONLY if it passes the
#        verification below (SHA-256 exact match + manifest identity + arm64-v8a presence).
#     2. It then verifies what you have, and refuses to proceed on any mismatch.
#
#   It NEVER substitutes another build. In particular it refuses the ARMv7-only
#   138.0.7204.181 file (measured: lib/armeabi-v7a only) - the target guest is ARM64-only
#   (ROM manifest.json "support_a32": false), so that file cannot work.
#
# IDENTITY OF THE TESTED PACKAGE (measured, see docs/reports/VALIDATION_REPORT.md):
#   package         com.google.android.webview
#   versionName     138.0.7204.179        versionCode 720417901
#   minSdk 26 / maxSdk 28 / targetSdk 35  (maxSdk=28 is the Android 8-9 branch build)
#   ABIs            arm64-v8a + armeabi-v7a (universal; the arm64 lib is ELF64/EM_AARCH64)
#   size            222218902 bytes
#   SHA-256         39f8eee7b6a4588c55e9299f95bfdff0c0943414bf468241becd0ed588e444a0
#   signer          Google "CN=webview" RSA-2048, cert SHA-256
#                   6faf3c4140407473400934d117815a21af1cfefc5c0bee61c858bc3d72ba6fe5
#
# USAGE:
#   sh download_webview_apk.sh /path/to/webview138_arm64_universal_138.0.7204.179.apk
#   sh download_webview_apk.sh --list                 # print expected identity, then exit
#   sh download_webview_apk.sh /path/to/any.apk       # any candidate is accepted as INPUT and
#                                                     # rejected unless it verifies fully
# Exit codes: 0 verified, 1 refused/mismatch, 2 usage/missing tooling.

set -u

EXPECT_SHA256=39f8eee7b6a4588c55e9299f95bfdff0c0943414bf468241becd0ed588e444a0
EXPECT_BYTES=222218902
EXPECT_PKG=com.google.android.webview
EXPECT_VER=138.0.7204.179
EXPECT_CODE=720417901

say() { printf '%s\n' "$*"; }
die() { say "REFUSED: $*"; exit 1; }

print_identity() {
    say "expected package identity (the ONLY build this project was tested against):"
    say "  package    : $EXPECT_PKG"
    say "  version    : $EXPECT_VER ($EXPECT_CODE)"
    say "  ABIs       : arm64-v8a + armeabi-v7a (universal); arm64-v8a is REQUIRED"
    say "  bytes      : $EXPECT_BYTES"
    say "  sha256     : $EXPECT_SHA256"
    say ""
    say "where to obtain it (authorized channels only):"
    say "  1. Google Play Store on the target device/guest - the canonical source."
    say "     If the guest's Play can install it, no file transfer is needed at all:"
    say "     the module's service.sh detects an already-installed package and does nothing."
    say "  2. A copy you already possess and trust (e.g. exported from a device where Play"
    say "     installed the same build). Mirror sites are not endorsed by this project;"
    say "     whatever source a file comes from, it MUST pass every check below."
    say ""
    say "this script never downloads anything itself and refuses the ARMv7-only 138.0.7204.181."
}

[ $# -ge 1 ] || { print_identity; exit 2; }
case "$1" in
    --list) print_identity; exit 0 ;;
esac
APK=$1
[ -f "$APK" ] || die "$APK does not exist - obtain the file first (see --list)"

command -v sha256sum >/dev/null 2>&1 || die "no sha256sum on this shell - cannot verify, refusing"
command -v unzip >/dev/null 2>&1 || die "no unzip on this shell - cannot verify, refusing"

say "== verifying $APK =="

# 1. exact byte identity - the strongest check: SHA-256 of the tested file
got_sha=$(sha256sum "$APK" | cut -d' ' -f1)
say "  sha256   : $got_sha"
if [ "$got_sha" = "a7de80d7b69d4b38436c6e6cc09479a2e71008083e96b9b620a9abbd9bc13d33" ]; then
    die "this file is the ARMv7-only 138.0.7204.181 build (sha256 a7de80d7...). The guest is ARM64-only; that file cannot work. Do NOT install it."
fi
[ "$got_sha" = "$EXPECT_SHA256" ] || die "sha256 $got_sha is not the tested 138.0.7204.179 arm64 universal build ($EXPECT_SHA256). Nothing was installed."

# 2. size (redundant with sha256, but a cheap early signal with a readable message)
got_bytes=$(wc -c < "$APK" | tr -d ' ')
[ "$got_bytes" = "$EXPECT_BYTES" ] || die "size $got_bytes != $EXPECT_BYTES"

# 3. ZIP integrity
unzip -t -q "$APK" >/dev/null 2>&1 || die "ZIP integrity check failed (CRC error)"

# 4. manifest identity: package, version, and the arm64-v8a library must all be present
list=$(unzip -l "$APK" 2>/dev/null)
echo "$list" | grep -q "lib/arm64-v8a/libwebviewchromium.so" || die "no lib/arm64-v8a/libwebviewchromium.so in the archive - wrong build"
# package/version straight from the binary manifest via the project's own pure-Python AXML parser
here=$(dirname "$0")
if command -v python3 >/dev/null 2>&1 && [ -f "$here/axml.py" ]; then
    ident=$(python3 - "$APK" "$here" <<'EOF'
import sys, zipfile
sys.path.insert(0, sys.argv[2])
from axml import AXML
z = zipfile.ZipFile(sys.argv[1])
els = {}
for k, t, av in AXML(z.read('AndroidManifest.xml')).dump():
    if k == 'start':
        els.setdefault(t, dict(av))
m, s = els.get('manifest', {}), els.get('uses-sdk', {})
print('%s %s %s %s %s' % (m.get('package'), m.get('versionName'), m.get('versionCode'),
                          s.get('minSdkVersion'), s.get('maxSdkVersion')))
EOF
)
    got_pkg=$(echo "$ident" | cut -d' ' -f1)
    got_ver=$(echo "$ident" | cut -d' ' -f2)
    got_code=$(echo "$ident" | cut -d' ' -f3)
    got_min=$(echo "$ident" | cut -d' ' -f4)
    got_max=$(echo "$ident" | cut -d' ' -f5)
    say "  package  : $got_pkg"
    say "  version  : $got_ver ($got_code)   minSdk=$got_min maxSdk=$got_max"
    [ "$got_pkg" = "$EXPECT_PKG" ] || die "package is $got_pkg, expected $EXPECT_PKG"
    [ "$got_ver" = "$EXPECT_VER" ] || die "version is $got_ver, expected $EXPECT_VER - the tested build is $EXPECT_VER, and this helper never substitutes another one"
    [ "$got_code" = "$EXPECT_CODE" ] || die "versionCode is $got_code, expected $EXPECT_CODE"
    [ "$got_max" = "28" ] || die "maxSdkVersion is $got_max, expected 28 (the Android 8-9 branch build)"
else
    say "  note     : python3/axml.py not available here - sha256 exact match already identifies"
    say "             the tested file; the manifest identity was not re-read, say so in your notes"
fi

say ""
say "VERIFIED: $APK is byte-for-byte the tested Google WebView $EXPECT_VER (arm64 universal)."
say "It is safe to stage and install per docs/INSTALLATION_GUIDE.md section 3:"
say "    su -c 'pm install -r $APK'"

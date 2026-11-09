#!/usr/bin/env bash
# Build com.qoder.webviewprovider.overlay  (static RRO for Android 9 / vendor overlay dir)
#
# WHY THIS SCRIPT EXISTS
#   Adding a WebView provider name on Android 9 normally means editing
#   res/xml/config_webview_packages.xml inside framework-res.apk, which must then be re-signed
#   with the ROM's own platform key (framework-res declares
#   android:sharedUserId="android.uid.system", core/res/AndroidManifest.xml:21, and
#   PackageManagerService.java:10285-10313 makes a mismatched cert fatal for the whole UID).
#   We do not have that key and will not invent one. A static RRO avoids the problem entirely:
#   PackageManagerService.java:11238-11249 applies the platform-cert requirement only to
#   DATA-partition overlays, and cmds/idmap contains no signature code at all.
#
# STATUS: SUPERSEDED. tools/build_overlay.py now builds this APK in pure Python (verified AXML +
# resources.arsc, no aapt, no key) and tools/verify_overlay.py audits the result; this script is kept
# as the aapt2/apksigner path for a machine that has them. The source tree here (AndroidManifest.xml +
# res/xml/config_webview_packages.xml) is the input for BOTH paths, and tools/build_overlay.py reads
# neither - it generates equivalent bytes from the template overlay on an Android 9 device.
# See reports/INTEGRATION_PLAN.md for what to deploy and where.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-"$HERE/WebViewProviderOverlay.apk"}

echo "== tool inventory =="
for t in aapt2 apksigner zipalign openssl keytool javac python3; do
  printf '  %-10s %s\n' "$t" "$(command -v "$t" || echo MISSING)"
done

if command -v aapt2 >/dev/null 2>&1 && command -v apksigner >/dev/null 2>&1; then
  echo "== backend A: aapt2 + apksigner =="
  STAGE=$(mktemp -d)
  aapt2 compile --dir "$HERE/res" -o "$STAGE/res.zip"
  aapt2 link -o "$STAGE/base.apk" -I "${ANDROID_JAR:?set ANDROID_JAR to android.jar for API 28}" \
      --manifest "$HERE/AndroidManifest.xml" "$STAGE/res.zip"
  cp "$STAGE/base.apk" "$OUT"
  # A self-signed key of OUR OWN is correct here: nothing in the Android 9 RRO path requires
  # the platform key. Generate it if absent; never reuse a key from an untrusted source.
  [ -f "$HERE/overlay-keystore.jks" ] || keytool -genkeypair -v -keystore "$HERE/overlay-keystore.jks" \
      -alias overlay -keyalg RSA -keysize 2048 -validity 10000 \
      -dname "CN=WebView Provider Overlay, O=local, C=US"
  apksigner sign --ks "$HERE/overlay-keystore.jks" --ks-key-alias overlay --out "$OUT" "$OUT"
  apksigner verify --verbose "$OUT"
  echo "built: $OUT"
  exit 0
fi

cat <<'MSG'
== backend B: pure-Python build (NOT IMPLEMENTED YET) ==

Two things are still missing in this environment, and this script refuses to fake them:

 1. A compiled resources.arsc for the overlay package.
    tools/axml.py already writes Android binary XML byte-exactly (verified against 12 real
    aapt2-produced files: selftest_axml.py, 157 checks, 0 failures) but the ResTable
    (resources.arsc) writer is not written. The idmap matches the overlaid resource by
    (package, type=xml, entry=config_webview_packages) NAME, so the overlay's own table must
    declare that pair; it is a ~300-line addition, not a config change.

    Cheap alternative, preferred: edit a REAL overlay APK instead of compiling one. Any
    /vendor/overlay/*.apk from the guest is a valid, aapt2-produced template, and the same
    string-pool machinery that makes axml.py byte-exact can retarget its manifest and rename
    its package/type/entry strings. That turns "write an arsc compiler" into "surgically edit
    a known-good file", which is the approach already proven here for AXML.

 2. An APK signature. A system APK with no signatures is skipped by PackageManager, so the
    RRO must be signed - with any key, since no platform cert is required. No openssl,
    keytool or Java exists here, so signing needs either backend A or a pure-Python v1
    (META-INF/MANIFEST.MF + .SF + PKCS#7 .RSA) signer. RSA primitives and DER reading are
    already implemented and test-passing in work/verify_sig.py; keygen and PKCS#7 writing
    are the unbuilt parts.

Until both exist, treat rro/ as reviewed source, not a deliverable.
MSG
exit 2

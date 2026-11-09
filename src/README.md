# src/

Source of the deployed artefacts, plus the small set of build inputs.

| Path | What it is |
|---|---|
| `overlay/AndroidManifest.xml` | aapt2-path source for the static RRO manifest (package `com.qoder.webviewprovider.overlay`, `targetPackage="android"`, `isStatic="true"`) |
| `overlay/res/xml/config_webview_packages.xml` | aapt2-path source for the provider list (Google first with the certificate as `<signature>` text, `com.android.webview` preserved) |
| `overlay/build.sh` | the aapt2/apksigner build path (documented as superseded by the pure-Python `tools/build_overlay.py`, kept for a machine that has the Android SDK) |
| `module/` | the Magisk module tree **exactly as staged and audited** — reference source. It is *generated* by `tools/build_magisk.py` (the templates live in that file); rebuilding with the same inputs reproduces it byte-for-byte. `module/README.md` is the on-device documentation copy, `module/webview138.manifest` is the audit manifest, `module/system/vendor/overlay/` holds the payload |
| `inputs/V2_cert.der` | the 959-byte Google X.509 that signs the 138 package and is embedded in the overlay (extracted from the APK Signing Block; SHA-256 `6faf3c41…`) |
| `inputs/guest_config_webview_packages.xml` | the guest's real provider config as plain text (extracted from its `framework-res.apk`), single provider `com.android.webview` |
| `inputs/guest_config_webview_packages.axml` | the same file compiled to binary AXML by `tools/xml_to_axml.py` — this is the `--base-xml` build input |
| `inputs/FrameworksResCommon.apk` | aapt2-produced static-RRO template (24926 B) from an Android 9 `/vendor/overlay`; the pure-Python builder retargets its manifest and reuses its per-entry compression choices |

Rebuild chain: see `README.md` "Rebuild from source".

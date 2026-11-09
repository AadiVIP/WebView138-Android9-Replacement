# Architecture

This document is the condensed engineering record. The full, verbatim engineering reports
(every measured value, every test, every correction) are in `docs/reports/`. Labels:
`MEASURED` = read from a file on the build machine; `SOURCE` = quoted from AOSP
`android-9.0.0_r35` (copies in `docs/references/`); `UNTESTED` = needs the guest.

## 1. Target environment

| Fact | Value | Basis |
|---|---|---|
| OS / API | Android 9, **API 28** (build `PQ3A.190801.002`, "Pixel 4" profile) | MEASURED (ROM `manifest.json` `minimum_sdk_int: 28`) |
| ABI | **ARM64-only** — `support_a32: false`, `support_a64: true` | MEASURED (ROM `manifest.json`) |
| Root | Magisk, user-reported v30 (the ROM package ships a Magisk plugin: `magisk_uri` in `manifest.json`) | UNTESTED in-guest; probe it (`tools/guest_probe.sh` §9) |
| Factory WebView | `com.android.webview` 81 (`versionCode` `404411700`), the only provider in the guest's `config_webview_packages.xml` | MEASURED (guest file supplied and compiled: `src/inputs/guest_config_webview_packages.axml`) |

**Android 9 / API 28 compatibility.** The replacement package is `minSdkVersion 26`,
`maxSdkVersion 28`, `targetSdkVersion 35`. The `maxSdkVersion=28` marks it as the Android 8–9
branch build (it is the only 138 build installable on API 28 at all), and `targetSdk >= 28`
clears provider-validity gate 1 (`UserPackage.hasCorrectTargetSdkVersion`,
`MINIMUM_SUPPORTED_SDK = P` — SOURCE `UserPackage.java:37,87-88`).

**ARM64 requirement.** The guest's `support_a32: false` means there is no 32-bit zygote, so the
arm64-v8a `libwebviewchromium.so` (`ELF64/EM_AARCH64`, 130550128 B — MEASURED) is the library
that loads. The ARMv7-only `138.0.7204.181` file is unusable here by construction (a 32-bit ELF
cannot be mapped into a 64-bit-only address space). The universal APK also carries
`use32bitAbi="true"`, which is inert on this guest (nothing 32-bit exists to honour it).

## 2. The provider overlay mechanism

- On API 28 the WebView provider list **is** the framework resource
  `android:xml/config_webview_packages` (inside the signed `framework-res.apk`).
  `SystemImpl` reads exactly that resource (SOURCE `SystemImpl.java:84-85`).
- The overlay is a **static RRO**: `targetPackage="android"`, `isStatic="true"`, `priority`
  in 0..9999, package `com.qoder.webviewprovider.overlay`. It is **unsigned by design**:
  `/vendor/overlay` and `/product/overlay` are scanned with `PARSE_IS_SYSTEM_DIR |
  SCAN_AS_SYSTEM` (SOURCE `PackageManagerService.java:578,580`, scan at `:2609,:2616`), and the
  "must be signed with the platform certificate" throw sits in the **else** branch — it applies
  only to non-system overlays. Production proof: shipping `/vendor/overlay` contents on an
  Android 9 device override non-public `android` entries the same way (MEASURED;
  `tools/arsc.py` reproduces one of their `resources.arsc` byte-for-byte). The native `idmap`
  matcher (`docs/references/idmap/scan.cpp`) returns the priority only for static overlays and
  contains **zero** signature code — an independent second confirmation.
- `<overlayable>`/`<public>` enforcement is Android 10+; that is also why this module is
  **API 28-only** and `customize.sh` refuses anything else.

### 2.1 The four provider-validity gates (SOURCE `WebViewUpdater.validityResult`)

| # | Gate | The 138 package (MEASURED) |
|---|---|---|
| 1 | `targetSdkVersion >= 28` | 35 → PASS |
| 2 | `versionCode >=` minimum factory provider | `720417901` vs `404411700` (WebView 81) → PASS |
| 3 | signature — with a declared `<signature>` the code compares it to the package's single signer; **`isSystemApp()` is NOT required** | overlay declares Google's 959-byte cert; the APK carries exactly that one cert (v2+v3 blocks, MEASURED) → PASS (source-level) |
| 4 | `com.android.webview.WebViewLibrary` meta-data present | `libwebviewchromium.so` → PASS |

Declaring the certificate as **`<signature>` element TEXT** (single-line canonical base64, 1280
chars) is load-bearing: `SystemImpl.java:166-181` reads only child-element text, and
`WebViewProviderInfo.java:42` decodes it with `Base64.DEFAULT`. The `signature="…"` *attribute*
form is never read by Android 9. Without it, gate 3 falls back to `applicationInfo.isSystemApp()`,
which a `/data` install fails — the audit suite pins this in both directions.

### 2.2 Selection order and why 81 survives

`findPreferredWebViewPackage()` (SOURCE `WebViewUpdater.java:284-321`): user pin
(`Settings.Global.webview_provider`) first if valid, else the **first** `availableByDefault`
provider in **document order** that is installed/enabled/valid. The overlay puts Google first;
if the 138 package is absent, selection falls through to `com.android.webview` 81 (second entry,
carried verbatim). Both entries have `isFallback="false"`, so the platform's fallback-disabling
logic (`WebViewUpdateServiceImpl.java:202-220`) has nothing to act on — installing 138 does not
let the platform switch 81 off, and 81 is never masked. A malformed list (no
`availableByDefault` non-fallback provider) would throw in `system_server`
(`SystemImpl.java:138-144`); every such rule is asserted at build time and by
`tools/verify_overlay.py`.

## 3. Magisk deployment method

`/vendor` is mounted `ro` (MEASURED on the host), so the 2.7 KB overlay reaches it only through
**magic mount**: Magisk binds the module's `system/vendor/overlay/` into the real
`/vendor/overlay` during `post-fs-data`, which init runs **before** `system_server` starts and
`PackageManagerService` scans (SOURCE). That ordering is the whole reason the module works — a
`service.sh`-time mount would be one boot too late. The module is `webview138-replacement`
(module id must equal the directory name, a Magisk requirement):

| File | Role |
|---|---|
| `module.prop` | identity: `id=webview138-replacement`, name, version, description |
| `system/vendor/overlay/webview138-provider-overlay.apk` | **the whole mechanism** — the audited overlay, stored uncompressed so it lands byte-for-byte |
| `webview138.manifest` | the audit manifest, copied verbatim so the device verifies against the same record |
| `webview138-apk.prop` | measured identity of the 138 package, what the opt-in install compares against |
| `customize.sh` | install-time gates: API==28, payload sha256 == manifest, provider logic re-read, id match, scan-dir presence (relocates to `/product/overlay` if that is the one that exists). Refuses rather than guesses. |
| `service.sh` | after boot: writes `boot-verify.log` (overlay mounted? package version? `dumpsys webviewupdate`?), and fixes **one** stale `webview_provider` pin — backed up to `pref-backup` before writing, opt-out via `no-pin`. The opt-in `auto-install` branch sha-verifies before any `pm install -r`. |
| `uninstall.sh` | restores `webview_provider` from backup; deletes only files it created |
| `README.md` | on-device copy of method, verification, and the honest "not verified" list |

Deliberate absences: **no `post-fs-data.sh`** (Magisk does the magic mount itself), and the
module **does not bundle the 222 MB package** — bundling it would depend on magic mount creating
a brand-new system app directory with undocumented SELinux-label behaviour; the tested route is
a normal `/data` `pm install`, which is exactly what the signature-declaring overlay permits.

## 4. Why the flashable ZIP path can report API "dummy" — and the standalone script is used

The flashable interface is `META-INF/com/google/android/update-binary <api> <tmpdir> <zipfile>`:
the **`<api>` argument is supplied by whoever invokes the installer** (the flasher), it is not
read from the device. Depending on the flashing context it arrives as a real number, empty, or a
placeholder string such as **`dummy`**. Inside the module, `customize.sh` therefore treats a
non-numeric/absent API as *unknown* — it prints
`WARNING: API unknown (flashed from recovery?)` and cannot enforce its API-28 gate, because it
has no measured device value to check. (The same is true of any installer argument: it is
flasher-provided, not device-provided.)

`tools/magisk_deploy.sh` — the drop-in installer that the test suite exercises end to end —
does not take the API on trust at all: it **measures** it from the device with
`getprop ro.build.version.sdk` and hard-refuses unless it is exactly 28. It installs the module
directory directly into `/data/adb/modules/webview138-replacement/` (the exact interface Magisk
consumes at boot), re-verifies the payload against the audit manifest, and re-runs the module's
own `customize.sh` as a child, so the drop-in and flash paths validate identically once the API
is known.

Additionally, the shipped `update-binary` is a **labelled re-implementation**: Magisk's own
template and `util_functions.sh` were not present on the offline build machine, so the flash
ABI is `UNTESTED` against the guest's Magisk build (user-reported v30). If the flash path and
the drop-in path ever disagree, the drop-in path is authoritative. The `update-binary` refuses
to create `/data/adb/modules` if it is absent and prints the drop-in commands on failure instead
of half-installing.

## 5. SELinux and boot-time overlay verification

- The scanned directory on the measured host is labelled `u:object_r:vendor_overlay_file:s0`
  (MEASURED). The scripts **report** the `ls -Z` context of what they write, next to a
  neighbouring real module, instead of guessing a label or running `restorecon` — a guessed
  label policy is not a fix.
- If `idmap` (installd) cannot read the overlaid file, Android 9 logs
  `Failed to generate idmap for …` (`PackageManagerService.java:839-841`) and **silently skips
  the overlay** — no boot loop, no dialog. That log line is the failure signature to look for.
- Boot-time verification is the module's own `service.sh`, which writes
  `boot-verify.log` (rotated to `.old`): whether the overlay is present in the scanned directory
  (`OVERLAY MOUNTED` / `OVERLAY NOT MOUNTED` from its own `ls`), the installed package version
  from `dumpsys package`, the `dumpsys webviewupdate` provider lines, and exactly what it did —
  or deliberately did not do — about `webview_provider`. Absence of evidence is not success:
  verification is `dumpsys webviewupdate` showing
  `Current WebView package (name, version): (com.google.android.webview, 138.0.7204.179)`, plus
  a rendered page whose `navigator.userAgent` contains `Chrome/138.0.7204.179`
  (INSTALLATION_GUIDE §7).

## 6. Rollback (exact procedure)

Because WebView 81 is never modified, disabled or removed:

```sh
su -c 'sh /sdcard/Download/magisk_deploy.sh --remove --i-reviewed'   # verifies module id, runs uninstall.sh, deletes only our dir
su -c reboot                                                          # nothing for Magisk to mount; framework re-reads its own config
```

Manual equivalent: restore `webview_provider` from `/data/adb/modules/webview138-replacement/pref-backup`
(if present), `rm -rf /data/adb/modules/webview138-replacement` (that path only), reboot. The
138 package remains installed but is no longer a declared provider; `pm uninstall
com.google.android.webview` removes it if you want the original state exactly. Full recovery
paths, including a non-booting guest, are in `docs/ROLLBACK_GUIDE.md`.

## 7. Build and audit chain (what makes "audited" checkable)

`tools/build_overlay.py` (pure-Python AXML + `resources.arsc` writer; byte-exact against real
aapt2 output — `selftest_axml.py`) → `tools/verify_overlay.py` (**independent** re-reader; writes
the delivery manifest only if every check passes) → `tools/build_magisk.py` (refuses without the
manifest; copies the audited bytes; deterministic timestamps) → `tools/audit_magisk.py`
(independent re-read of the finished ZIP + destructive-command lint of every script) →
`tools/selftest_magisk.py` (sandboxed lifecycle of the real scripts with shimmed
`pm`/`settings`/`dumpsys`, plus host-integrity assertions). Two producers on purpose: the
split caught a real defect during development (certificate emitted as bare CDATA outside
`<signature>`, which the builder's own check could not see but Android 9 would have read as
zero signatures).

## 8. Known limitations and unverified configurations

**Unverified (read before installing):**
1. Whether the guest has Magisk at all, and which version — user-reported v30, unmeasured in-guest;
   `guest_probe.sh` §9 classifies PRESENT/ABSENT/NOINFO from `stat` errno (run as root).
2. `update-binary` ↔ Magisk v30 ABI — re-implementation; drop-in route is the tested path (§4).
3. Magic-mount of a *brand-new* `system/vendor/overlay/` directory — Magisk-internal, unverified;
   `customize.sh` refuses when neither scanned directory exists instead of inventing one.
4. `idmap` success for this RRO on the guest — failure is silent; `boot-verify.log` + `logcat`
   are the evidence.
5. Native 64-bit load and relro handshake of the 138 renderer — runtime-only.
6. The guest's `ro.build.type`: if `userdebug`/`eng`, gates 2–3 are skipped entirely
   (`systemIsDebuggable()`); the host is `user`. Read it in the probe.

**Limitations:**
- **API 28-only, by construction** (framework RROs on Android 10+ must name an `<overlayable>`
  entry, which `config_webview_packages` is not); ARM64-only guest assumed (measured); the
  overlay must carry the guest's complete provider list because an RRO *replaces* the resource —
  this build is matched to the guest's actual single-provider list, byte-identically.
- The target ROM's images are an encrypted private container (`?e=x&c=v2`); a modified ROM ZIP
  was never produceable and is not a goal — the module is the delivery vehicle.
- Nothing here is a boot claim: until INSTALLATION_GUIDE §7 passes on the guest, the honest
  status is *prepared, audited off-device, unverified at runtime*.

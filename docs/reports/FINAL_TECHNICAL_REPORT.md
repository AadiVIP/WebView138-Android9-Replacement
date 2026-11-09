# Final Technical Report — Google WebView 138 as default provider in the Virtual Master Android 9 guest

Status line: **Option A (Magisk module) is built, audited and sandbox-tested. It has not been flashed
and has not been runtime-verified on the guest.** Every line below that is a `MEASURED` fact or a
`SOURCE` citation is backed by a file on this machine; every line that is not one is labelled
`UNTESTED`. Nothing here is a boot claim.

Recommended implementation: **deliver `output/WebView138-Replacement-Magisk.zip` and install it with the
drop-in route in `INSTALLATION_GUIDE.md`.** Option B (direct RRO deploy) is the same overlay via
`tools/install_overlay.sh` if the guest turns out to have no Magisk; Option C (framework-res re-sign)
is *not* recommended and its blocker is stated in §8.

---

## 1. What was delivered and where

| Artifact | Size / sha256 | Role |
|---|---|---|
| `output/WebView138-Replacement-Magisk.zip` | 18181 B / `b6323730c2fe56894477d2cf854c18c8e1732f4befa04c05ed3572bc89797955` | **the** deliverable (module id `webview138-replacement`) |
| `output/webview138-provider-overlay.apk` | 2688 B / `a78b79788a6cf57a6cdefc1e2d69c9ae7466c88ff6938974d11c2aefce53364a` | static RRO the module carries (payload, byte-identical inside the ZIP) |
| `output/webview138-provider-overlay.manifest` | 25 lines | audit record the builder/refusers bind to |
| `input/webview138_arm64_universal_138.0.7204.179.apk` | 222218902 B / `39f8eee7b6a4588c55e9299f95bfdff0c0943414bf468241becd0ed588e444a0` | the replacement package the module registers (not bundled in the module) |
| `tools/magisk_deploy.sh` | root on-device helper | install / verify / rollback, the tested route |
| `reports/INSTALLATION_GUIDE.md` | | how to install on the guest |
| `reports/ROLLBACK_GUIDE.md` | | every recovery path |
| `reports/VALIDATION_REPORT.md` §9 | | full Magisk test evidence |
| `reports/INTEGRATION_PLAN.md` §4B | | architecture + Option A mapping |

Deterministic build: running `tools/build_magisk.py` twice produced the identical sha256.

---

## 2. Replacement APK — measured, not assumed

Read out of `input/webview138_arm64_universal_138.0.7204.179.apk` by the project's own AXML parser
(`tools/axml.py`), not by filename:

| Property | Value | Android 9 verdict |
|---|---|---|
| `package` | `com.google.android.webview` | the provider the overlay names |
| `versionName` / `versionCode` | `138.0.7204.179` / `720417901` | see §3 gate 2 |
| `minSdkVersion` | 26 | guest is 28 ≥ 26 |
| `maxSdkVersion` | **28** | this is the Android 9 build branch — correct |
| `targetSdkVersion` | **35** | gate 1 (§3): 35 ≥ 28 → pass |
| `compileSdkVersion` | 36 | informational |
| ABIs present | `arm64-v8a`, `armeabi-v7a` | arm64 lib 130550128 B (ELF64/EM_AARCH64), arm lib 78362172 B |
| `multiArch` | **true** | both ABI dirs installed on one package |
| `use32bitAbi` | **true** | see §3.6 — the one ABI subtlety that remains |
| `extractNativeLibs` | **false** | libs loaded from the APK, not extracted (normal for modern WebView) |
| `meta-data com.android.webview.WebViewLibrary` | **`libwebviewchromium.so`** | gate 4 (§3): present → pass |
| `isolatedSplits` / `requiredSplitTypes` | true / (empty) | standalone base APK; `requiredSplitTypes` is an API 29 attribute, ignored on API 28 |
| APK Signing Block | present | signed |
| signing cert sha256 | `6faf3c4140407473400934d117815a21af1cfefc5c0bee61c858bc3d72ba6fe5` | = handoff value, = the certificate the overlay declares |
| signing cert sha1 | `1F387CB25E0069EFCA490ADE28C060E09D37DD45` | = handoff value (fingerprint cross-check only) |

The certificate the overlay embeds is the **full 959-byte X.509 as single-line canonical Base64**
(1280 chars, `cert_base64=` in the manifest) — not a fingerprint. `audit_magisk.py` re-derives it from
the finished bytes and confirms `cert_sha256` matches the 138 APK's own signer (`6faf3c41…` == `6faf3c41…`).

`.181` (`input/webview138.apk`) was measured as **armeabi-v7a-only** and is not used.

---

## 3. Android 9 provider validity — every gate, cited from source

`WebViewUpdater.isValidProvider()` → `validityResult()` (`refs/aosp9/WebViewUpdater.java:428-446`)
applies four gates in order. For each, the measured 138 values:

1. **`UserPackage.hasCorrectTargetSdkVersion`** (`UserPackage.java:87-88`):
   `targetSdkVersion >= MINIMUM_SUPPORTED_SDK` where `MINIMUM_SUPPORTED_SDK = Build.VERSION_CODES.P = 28`
   (`UserPackage.java:37`). 138 targets **35 ≥ 28 → PASS**. This directly answers handoff Finding 2:
   targetSdk is a real gate, and the 138 APK clears it.
2. **Minimum version code** (`WebViewUpdater.java:433-437`): `versionCode >= getMinimumVersionCode()`
   unless debuggable. `getMinimumVersionCode()` (`:481-503`) takes the *minimum* installed
   `getFactoryPackageVersion()` among `availableByDefault && !isFallback` providers;
   `getFactoryPackageVersion` uses `MATCH_FACTORY_ONLY` (`SystemImpl.java:159-163`). The only factory
   provider is 81 at `/system/app/webview/webview.apk` = versionCode `404411700`; a `/data`-only Google
   throws `NameNotFoundException` and is ignored. So minimum = `404411700`; `720417901 ≥ 404411700 →
   PASS`.
3. **Signature** (`providerHasValidSignature`, `:505-521`): if **no** `<signature>` is declared it
   returns `applicationInfo.isSystemApp()`; if **one** is declared it requires exactly one package
   signature and a match. The overlay **declares Google's certificate** for `com.google.android.webview`,
   so the code takes the match branch — **`FLAG_SYSTEM`/`isSystemApp` is NOT required** (handoff
   Finding 3, confirmed). This is what lets a `/data` `pm install` be a valid provider. 138 carries
   exactly one signature and it equals the declared certificate → **PASS (source-level; not runtime)**.
4. **`WebViewFactory.getWebViewLibrary`** (`:442-443`, `WebViewFactory.java:159-163`): returns
   `metaData.getString("com.android.webview.WebViewLibrary")`. Measured value is
   `libwebviewchromium.so` → non-null → **PASS**.

All four gates are satisfied by the *measured* package against the *source* rules. The failure mode to
watch at runtime is a package that registers but fails gate 3/4 for a reason the source read cannot see
(e.g. a relro load error); `dumpsys webviewupdate` reports that as the package appearing under
`Invalid package(s)` — that is the single signal to check after install (INSTALLATION_GUIDE §4).

### 3.1 Provider ordering and fallback — resolved explicitly

`findPreferredWebViewPackage()` (`WebViewUpdater.java:284-321`), after filtering to **valid** providers
(`getValidWebViewPackagesAndInfos`):

1. **`:290-298` user choice first** — `Settings.Global.webview_provider`, if that package is installed
   and enabled for all users, wins *before* document order. This is the one persisted value that can
   overrule the overlay, and the only reason `service.sh` exists (it backs up and, if stale, re-pins it).
2. **`:301-315` document order** (the `availableByDefault` test is `:307`) — the first `availableByDefault` provider that is installed and
   enabled for all users is returned.
3. **`:320`** else `WebViewPackageMissingException`.

The shipped overlay lists, in order: `com.google.android.webview`
(`availableByDefault=true, isFallback=false, 1 signature`) then `com.android.webview`
(`availableByDefault=true, isFallback=false, 0 signatures`). Therefore:

- 138 installed + valid → selected (it is first in document order, and valid).
- 138 absent → the loop skips it (not installed) and returns 81 (second, still `availableByDefault`).
- 81 only → 81. This is the recovery path.
- `isFallback=false` on **both** means neither is eligible for the fallback-logic disable
  (`WebViewUpdateServiceImpl.java:202-220` → `SystemImpl.java:225-235` only act on the `isFallback=true`
  entry). So installing 138 does **not** let the platform switch 81 off, and 81 is never masked.

This satisfies "make 138 default immediately after boot" *and* "81 stays recoverable" with one file.

### 3.2 How the list actually changes on Android 9 (why an RRO, why Magisk)

On API 28 the provider list *is* the resource `android:xml/config_webview_packages`; there is no
separate registry call to make. A **static RRO** targeting `android` and overriding that resource is
the minimal correct unit, and it does **not** require a platform signature: `PackageManagerService`
scans `/vendor/overlay` (`:578`) and `/product/overlay` (`:580`) at `:2609`/`:2616` with
`PARSE_IS_SYSTEM_DIR|SCAN_AS_SYSTEM`, and the platform-cert check lives in the *else* branch.
`/vendor` is mounted `ro` (measured), so the file must arrive via **magic mount**, which Magisk performs
during `post-fs-data` — *before* `system_server` starts and PMS scans. That ordering is why the module
works and why a `service.sh`-time mount would be one boot too late. It is also why the module is
**API 28-only** (from Android 10 a framework RRO must name an `<overlayable>` entry, which
`config_webview_packages` is not — `customize.sh` refuses anything but API 28).

### 3.3 The `use32bitAbi` / `multiArch` question — resolved by a host-side measurement

The 138 package sets `multiArch=true`, `use32bitAbi=true`, `extractNativeLibs=false`. On a guest that
supports *both* ABIs that combination would make the 32-bit arch primary, and `WebViewLibraryLoader`
resolves by bitness against **both** dirs (`getWebViewNativeLibraryDirectory`,
`WebViewLibraryLoader.java:279-292`: `nativeLibraryDir` when the primary arch has the wanted bitness,
else `secondaryNativeLibraryDir`). So a `multiArch` package can serve both WebView zygote bitnesses at
the source level.

But this guest does not need that branch. **MEASURED from `input/rom_9_0_0_1059_3281.zip` →
`manifest.json`:**

```json
"id": "rom_default_9.0.0", "os_version": 9, "minimum_sdk_int": 28,
"support_a32": false, "support_a64": true,
"magisk_uri": "asset:///plugins/magisk.zip?h=true"
```

`support_a32: false` means the guest is **64-bit only**, so `use32bitAbi` cannot take effect: primary
arch is `arm64-v8a`, `getWebViewNativeLibraryDirectory(64-bit)` returns `nativeLibraryDir`, the arm64
library is the one found, and the 32-bit zygote does not exist to find anything. The arm64 library was
re-verified directly from the APK this session: `ELF64`, little-endian, `e_machine = 183 =
EM_AARCH64`, 130550128 bytes.

`support_a64: true` and `minimum_sdk_int: 28` also corroborate the ARM64/API-28 assumptions, and
`magisk_uri` corroborates that the ROM package ships Magisk (consistent with the reported v30).

**Remaining, and only, native-code unknown:** whether the load and relro handshake actually succeeds on
the guest. That is a runtime check (INSTALLATION_GUIDE §4.3), not a host-side one.

## 4. Module architecture — every file, and why

| Entry | Mode | Purpose (and what it deliberately does not do) |
|---|---|---|
| `module.prop` | 644 | `id=webview138-replacement`; name/version/author/description. id must equal the directory name (Magisk requirement) |
| `customize.sh` | 755 | installer-time gates: API==28, payload sha256 == audit manifest, provider logic re-read from the manifest, `module.prop id` == tree; relocates the payload to whichever of `/vendor/overlay` or `/product/overlay` exists. **Refuses** rather than guesses when the conditions are not met |
| `service.sh` | 755 | after boot: `ls` of the scanned dir (MOUNTED / NOT MOUNTED), `pm` + `dumpsys package` for the installed version, `dumpsys webviewupdate`, writes `boot-verify.log` (rotated to `.old`), and fixes **one** stale `webview_provider` pin (backed up before writing, opt-out via `no-pin`). Also the **opt-in** `auto-install` branch that sha-verifies then `pm install -r`s the 138 APK |
| `uninstall.sh` | 755 | restores `webview_provider` from `pref-backup` (`settings delete` if the backup was empty); deletes only files it created inside the module dir |
| `webview138.manifest` | 644 | the audit manifest copied verbatim so the device verifies against the same record |
| `webview138-apk.prop` | 644 | measured package facts (package, version, min/max/target, ABIs, sha256, bytes) — what `service.sh` compares the opt-in APK against |
| `system/vendor/overlay/webview138-provider-overlay.apk` | 644 | payload, **STORED** (uncompressed) so it lands byte-for-byte; sha256 `a78b7978…` |
| `README.md` | 644 | on-device copy of method + verification + honest "not verified" list |
| `META-INF/com/google/android/updater-script` | 644 | `#MAGISK` |
| `META-INF/com/google/android/update-binary` | 755 | **labelled re-implementation** of the ZIP installer; refuses to create `/data/adb/modules` if absent, otherwise stages, copies, sources `customize.sh`, and prints the drop-in commands on any failure. Its compatibility with a specific Magisk build (v30) is **UNTESTED** |

There is **no `post-fs-data.sh`**: the only `post-fs-data` need is the magic mount, and Magisk performs
that itself from the `system/` tree. Adding one would be an unexercised path pretending to be a mechanism.

Deviation stated plainly (Option A item 2): the module does **not** bundle the 222 MB package. A module
*can* carry `/system/app/…`, but that relies on magic mount **creating a brand-new system subdirectory**
and on its SELinux-label behaviour for a fresh 222 MB system app — a Magisk-internal case that is not
documented on the build machine and cannot be fetched (offline rule). The shipped, tested answer is the
`/data` `pm install` the README prints, or the module's own sha-verified `auto-install`.

---

## 5. Testing — performed, and results (all re-run after the last change)

| Suite | Command | Result |
|---|---|---|
| AXML parser | `python3 tools/selftest_axml.py` | **176 / 0** |
| Overlay audit, standalone (no base) | `python3 tools/verify_overlay.py …` | **26 / 0** |
| Overlay audit vs the guest's real `config_webview_packages.xml` | same, `--base-xml work/guest_config_webview_packages.axml` | **31 / 0** — Google added, `com.android.webview` preserved verbatim |
| Overlay audit, 6-provider from-base build (regression) | same, `--base-xml work/standin_host_config.axml` | **37 / 0** (count preserved 6→6) |
| Module ZIP structure + script lint | `python3 tools/audit_magisk.py` | **84 / 0** |
| Module lifecycle in a sandbox | `python3 tools/selftest_magisk.py` | **58 / 0** |

The 58-check sandbox matrix runs the *real* scripts (shimmed `pm`/`settings`/`dumpsys`/`getprop`) and is
organised as: **A** `magisk_deploy.sh` lifecycle incl. refusal of unrooted "absence" claims (A14);
**B** `service.sh` (unset/stale pin, double-run, `no-pin`, package absent, overlay not mounted, log
rotation, and the opt-in `auto-install` refuse-then-install B9–B13); **C** `customize.sh` gates
(API 29 refused, tampered bytes refused, vendor→product relocation, neither-dir refused, fallback
refused, id mismatch refused); **D** `update-binary` refuses without `/data/adb/modules`, plus
`/system/bin/sh -n` (Android 9's own MIRBSD KSH R56) on every script; **E** host integrity — `/vendor/overlay`
listing unchanged, inputs re-hashed to their original md5s (`9c3c90…/5758db…/109c5b…`), host's real
`webview_provider` untouched (`''` → `''`), `/proc/mounts` byte-identical, and a DAC proof that this uid
cannot write `/data` at all.

The auditor's destructive-command scan, with heredoc bodies blanked so printed instructions are not read
as commands: no `mkfs`, `dd of=/dev/`, `mount -o remount`, `pm uninstall`, `pm disable`, `pm clear`,
`settings delete global webview_fallback*`, `fastboot`/`stop`/`start`, `killall`/`pkill`, `curl`/`wget`,
no write to a device node other than `/dev/null`, no `chmod`/`chown`/`restorecon` on `/system|/vendor|/product`,
no `reboot`/`shutdown` command, no recursive `rm /`; every `rm` targets only the module directory or a
scratch path, and `magisk_deploy.sh --remove` is gated by `case "$DEST" in /data/adb/modules/"$MOD_ID"`.

### Unverified — read before installing

1. **Guest Magisk is user-reported as v30, not yet measured in the guest.** The ROM package *does* ship
   a Magisk plugin (`manifest.json → magisk_uri`), which is supporting but not conclusive evidence for
   this guest. On the physical host `/data/adb` is
   *NOINFO* (EACCES to a non-root shell — not proof of absence). `guest_probe.sh §9` now classifies
   PRESENT / ABSENT / NOINFO from `stat`'s errno and must be run **as root in the guest**.
2. **`update-binary` ↔ Magisk v30 ABI** — re-implementation; the drop-in route is the tested path.
3. **Magic-mount of a *new* `system/vendor/overlay/` directory and of a 222 MB new `/data` system app** —
   Magisk-internal, unverified; the scripts *report* the measured `ls -Z` context rather than assume it.
4. **`idmap` success on the guest** — a failure is logged at `PackageManagerService.java:839-841` and the
   overlay is then silently skipped; `boot-verify.log` + `logcat` are the evidence.
5. ~~The guest's real `config_webview_packages.xml`~~ — **RESOLVED.** The user supplied the guest's
   actual file: it lists exactly one provider, `com.android.webview` (`availableByDefault="true"`, no
   fallback, no signature). Rebuilt against it, the overlay is **byte-identical** to the one shipped
   (sha256 `a78b7978…`) and audits 31/0 with the guest entry preserved verbatim — so the shipped 2-entry
   payload is exactly right for this guest and no other provider is dropped. Saved as
   `work/guest_config_webview_packages.xml` (+ `.axml`) and pinned by `selftest_axml.py` T9.
6. **Native 64-bit load** (§3.3) — the ABI-selection risk is *closed* by the `support_a32:false`
   measurement; whether the 64-bit load and relro actually succeed is still runtime-only.

---

## 6. Answers to the required investigation (§10)

1. **Magisk version** — user-reported v30; **UNVERIFIED** (probe §9, run as root).
2. **Guest arch** — **MEASURED** 64-bit only: ROM `manifest.json` → `support_a32: false`,
   `support_a64: true`, `minimum_sdk_int: 28`; guest build `PQ3A.190801.002` (Pixel 4, Android 9/API 28).
   The probe's `PROBE_ABILIST32`/`PROBE_ABILIST64` remain the in-guest confirmation, expected
   `armeabi`-absent / `arm64-v8a`-present.
3. **Systemless overlay paths** — module `system/vendor/overlay/` → magic-mounted over `/vendor/overlay`;
   relocates to `system/product/overlay/` if only that dir exists.
4. **Is `/vendor/overlay` scanned?** — yes on API 28 (`:578`, scanned `:2609`); host confirms the dir exists.
5. **Is `/product/overlay` scanned?** — yes (`:580`, `:2616`); `customize.sh` uses whichever is present.
6. **Static RRO supported?** — yes, API 28, `isStatic=true` + `priority=100`.
7. **Does the provider config already contain Google?** — **No.** The guest's real file lists only
   `com.android.webview`; Google is *added* by the overlay (first, with its certificate), not normalised
   in place. (The *host* file lists Google as a fallback, but that is a different image.)
8. **Standalone or split?** — standalone base APK (`isolatedSplits=true` but `requiredSplitTypes` empty, an
   API 29 attribute ignored on 28).
9. **Native libs match guest?** — **yes at host level**: `lib/arm64-v8a/libwebviewchromium.so` is
   ELF64/`EM_AARCH64` 130550128 B, and the guest is 64-bit only (`support_a32:false`), so the extra
   armeabi-v7a lib is unused. Runtime load/relro unverified (§3.3).
10. **Provider cert valid in intended config?** — yes, declared in the overlay → match branch, no
    `isSystemApp` needed (gate 3). Source-level.
11. **Does targetSdk 35 pass?** — yes, gate 1 (≥ 28), source-confirmed.

---

## 7. Safety posture

- No partition was written, no `/system`/`/vendor`/`/product` file changed, no framework resource
  re-signed, no input file modified (input md5s unchanged after the whole run).
- WebView 81 was never touched; rollback is a reboot, not a reinstall (ROLLBACK_GUIDE).
- Nothing is flashed or installed by this project; installation is user-approved and manual.
- Host integrity is asserted by measurement (E-group), including that this uid *cannot* write `/data`
  (DAC) and that the host's own `webview_provider` was untouched.

## 8. Exact blockers if a path cannot work

- **Option C is blocked, not recommended:** a direct `framework-res.apk` patch needs the ROM's platform
  key to re-sign, which is not in the package, and the ROM's `framework-res.apk` sits inside the
  `?e=x&c=v2` container that is not decryptable here. It would only reopen if the guest is built with a
  publicly known platform key — one extracted file decides that.
- **Option A's only hard prerequisites** are (i) Magisk actually present in the guest and (v) the guest's
  real provider XML if the guest lists more than two providers. Everything else in Option A is satisfied
  by measured artifacts and source rules.

## 9. Runtime — has 138 been installed and runtime-tested?

**No.** Nothing has been installed on the guest or the host, nothing has rebooted, no
`dumpsys webviewupdate`, no rendered page, no user-agent capture. The module is **untested at runtime**
by definition. The nine runtime checks in the handoff (boot, Magisk load, PM recognition, `dumpsys`
current=138, native load, zygote init, page render, JS, UA=Chromium 138) are exactly the acceptance
tests in INSTALLATION_GUIDE §7 (commands in §4) and are to be performed by the user after an approved install. Do not
report success until they pass.

# WebView 138 Compatibility Report

Target: Android 9 (API 28) guest inside Virtual Master, ROM package
`rom_9_0_0_1059_3281.zip`, `rom_version` 1059, build `PQ3A.190801.002`.

Every "MEASURED" value below was obtained by direct parsing in this session; the tool is named.
Anything marked **UNVERIFIABLE FROM INPUTS** could not be determined because the ROM payload is
encrypted (see `ROM_INSPECTION_REPORT.md` §3).

---

## 1. Android version / API compatibility — PASS

| Item | Value | Verdict |
|---|---|---|
| minSdkVersion | 26 | API 28 ≥ 26 ✓ |
| maxSdkVersion | 28 | API 28 ≤ 28 ✓ — this is the "Android 8.0–9.0" branch build |
| targetSdkVersion | 35 | **REQUIRED to be ≥ 28** by `UserPackage.hasCorrectTargetSdkVersion` — 35 passes. See §4 gate 1. NOT irrelevant (this line previously said "irrelevant", which was wrong). |
| `minimum_sdk_int` in the ROM manifest | 28 | matches |
| versionName / versionCode | `138.0.7204.181` / `720418100` | as claimed — MEASURED from binary `AndroidManifest.xml` |
| `compileSdkVersion` | 36 | built with the Android 16 toolchain |

On API level alone, 138 is compatible with this guest.

## 2. ABI compatibility — **FAIL (fatal)**

MEASURED from the supplied APK (`work/apkinfo2.py` → `reports/raw_apk_analysis.txt`):

```
ABI dirs present: ['armeabi-v7a']
   lib/armeabi-v7a/libcrashpad_handler_trampoline.so   3,112 B  -> ELF32, e_machine = EM_ARM (0x28)
   lib/armeabi-v7a/libwebviewchromium.so          78,403,132 B  -> ELF32, e_machine = EM_ARM (0x28)
```

Both native libraries are genuine 32-bit ARM ELF objects and there is no `arm64-v8a` directory.
This confirms the APKMirror filename independently: the supplied metadata was accurate.

MEASURED from the ROM package (`manifest.json`, verbatim): `"support_a32": false`,
`"support_a64": true`. The ROM declares its guest does **not** support 32-bit ARM. Therefore:

- `ro.product.cpu.abilist32` is expected to be empty; `abilist` expected to be `arm64-v8a` only.
- `libwebviewchromium.so` (EM_ARM, 32-bit) cannot be mapped into an `arm64-v8a`-only process. The
  bionic linker cannot load a 32-bit ELF into a 64-bit address space. This is an object-format
  incompatibility, not a permissions or path problem.

### 2.0 What the framework actually does with this APK (corrected, source-verified)

MEASURED from the manifest (`work/AndroidManifest_decoded.txt` line 11): the application node carries
`android:multiArch="true"` and `android:extractNativeLibs="false"`. That changes the predicted
failure mode, and my earlier statement here ("PackageManager finds no common ABI →
`INSTALL_FAILED_NO_MATCHING_ABIS`, so the boot scan skips it") was **only partly right** — the two
paths differ:

- **`adb install` (non-system path).** The installer calls
  `NativeLibraryHelper.findSupportedAbi` / `copyNativeBinariesForSupportedAbi`, whose documented
  contract returns `INSTALL_FAILED_NO_MATCHING_ABIS` when the APK has native code for no supported
  ABI (`NativeLibraryHelper.java:204-211`, AOSP `android-9.0.0_r35`). → install fails with −113.
  This is the practical test in `GUEST_DIAGNOSTICS.sh` §6.
- **Boot scan of `/system/app` (the path this project needs).** `scanPackageDirtyLI` →
  `derivePackageAbi` (`PackageManagerService.java:10605-10608`, `:11670`). Because the app is
  `multiArch`, the 32-bit probe is skipped outright when `Build.SUPPORTED_32_BIT_ABIS.length == 0`
  (`:11715`), and the 64-bit probe returns −113 (`:11743`). The multiarch error handler
  **explicitly ignores** both `NO_NATIVE_LIBRARIES` and `INSTALL_FAILED_NO_MATCHING_ABIS`
  (`maybeThrowExceptionForMultiArchCopy`, `:16077-16084`), so nothing throws and the package is
  **registered anyway**, with `primaryCpuAbi == null`. The scanner then falls back to directory
  guessing for bundled apps (`:10613-10617` → `setBundledAppAbisAndRoots`, `:11690`), which infers a
  lib dir from `/system/lib64|/system/lib` existence.
  Net effect: the APK would very likely *appear* in the package list and even in Developer Options
  (registration does not check ABI), and then fail when `WebViewLoader` dlopens
  `libwebviewchromium.so` — i.e. a broken WebView / crashed renderer, not a clean rejection.
  Only a non-multiArch APK would take the hard `throw` at `:11799-11801`.

  This ABI-fallback sub-analysis rests on one file, `PackageManagerService.java`, which I read from
  a large local mirror dump rather than a pristine upstream checkout; the line numbers there are
  approximate. The conclusion (registration succeeds, load fails at runtime) is a **prediction from
  code, not an observed result** — nothing was booted.

**Verdict: incompatible. Phase 4's stop condition applies.** No attempt was made to convert or
rename ARM32 libraries as ARM64 — that is not physically possible.

Remaining uncertainty: `support_a32:false` is the package author's own capability flag, read from
the manifest; it could not be cross-checked against `/system/lib` vs `/system/lib64` inside the
image because the image is encrypted. The one-command confirmation is inside the guest —
`reports/GUEST_DIAGNOSTICS.sh` §1. **A practical test that needs no shell at all:** sideload
`input/webview138.apk` into the guest and see whether the installer reports a no-matching-ABI error.

### 2.1 The correct artefact already exists on this machine

While checking what was locally available, a **138 build containing arm64-v8a** was found already
installed on the host phone (read-only via `pm path`; nothing on the host was modified):

```
/data/app/com.google.android.webview-.../base.apk      222,218,902 B
  package      : com.google.android.webview
  versionName  : 138.0.7204.179        versionCode: 720417901
  uses-sdk     : minSdkVersion=26  targetSdkVersion=35  maxSdkVersion=28
  ABIs         : lib/arm64-v8a/libwebviewchromium.so  130,550,128 B
                 lib/armeabi-v7a/libwebviewchromium.so 78,362,172 B
  cert SHA-1   : 1F387CB25E0069EFCA490ADE28C060E09D37DD45   (same key as the supplied APK)
  v2 signature : VALID (verified by computation, same code path as §3)
  zip CRC      : clean, 466 entries
  flags        : multiArch=true, extractNativeLibs=false, use32bitAbi=true, isolatedSplits=true
  SHA-256(file): 39f8eee7b6a4588c55e9299f95bfdff0c0943414bf468241becd0ed588e444a0
  copied to    : input/webview138_arm64_universal_138.0.7204.179.apk
```

Notes:

- It is `138.0.7204.179`, not `.181` — same M138 stable branch, one build older. If `.181`
  specifically is required, the artefact needed is APKMirror's **arm64-v8a** `minAPI26/maxAPI28`
  split of `138.0.7204.181`, not the `armeabi-v7a` split now in `input/`.
- As the *universal* APK it is 222 MB; an arm64-only split would be roughly half that.
- It carries `android:use32bitAbi="true"` (the supplied v7a-only APK does not). On a 64-bit-only
  device that request cannot be honoured, which is a reason to prefer a clean arm64-only split for
  a permanent integration over this universal APK.
- Its existence proves the `maxSdkVersion=28` + `arm64-v8a` combination genuinely ships in the 138
  branch — i.e. the user's plan is sound, but with the wrong split.

## 3. Signature validation — PASS

MEASURED (`work/verify_sig.py` → `reports/raw_sig_verification.txt`). No `apksigner`, Java or
OpenSSL exists in this environment, so the APK Signing Block, X.509 and RSA operations were
implemented directly in Python against the published formats.

| Check | Result |
|---|---|
| APK Signing Block present and self-consistent | PASS — `APK Sig Block 42`, block at 91,361,280, size 8,184, leading/trailing size fields agree |
| Signing schemes | v2 (0x7109871a) and v3 (0xf05368c0); **no v1/JAR signature** — fine at API 28 |
| Certificate | X.509 v3, self-signed, `C=US, ST=California, L=Mountain View, O=Google Inc., OU=Android, CN=webview`, serial `0x0d8ba0e00501b8653`, RSA-2048 e=65537, `sha1WithRSAEncryption`, valid 2014-08-08 → 2041-12-24 |
| Certificate SHA-1 | `1F387CB25E0069EFCA490ADE28C060E09D37DD45` — **matches the brief** |
| Certificate SHA-256 | `6FAF3C4140407473400934D117815A21AF1CFEFC5C0BEE61C858BC3D72BA6FE5` — **matches** |
| **v2 signature cryptographic verification** | **VALID** — RSA-2048 PKCS#1 v1.5 SHA-256 over `signedData` (alg id 0x103) |
| Signer public key vs certificate key | identical modulus |
| **Certificate self-signature verification** | **VALID** (SHA-1 over `tbsCertificate`) |
| Second chain, pair 0x6dff800d | `CN=Android, O=Google Inc.`, 1,421 B, SHA-256 `3257D599…` — equals the APK's `stamp-cert-sha256`; this is the Play **stamp** key, not the provider key |
| Full DER certificate recovered | YES — `work/V2_cert.der` (959 B); base64 in `reports/google_webview_signing_cert_base64.txt` (1,280 chars) |

The brief's metadata was therefore independently confirmed rather than assumed. These are
certificate fingerprints; the full DER certificate (what a provider entry actually needs) has been
extracted and is on disk, not paraphrased.

**Stated limit:** the v2 *signature over signed-data* was verified with real modular arithmetic,
which cryptographically binds the signed-data block that contains the content digests. The per-file
1 MiB-chunk content digests were **not** re-derived (that needs `apksigner`/Java or a faithful
reimplementation of the v2 chunked-digest tree). Reported as an omission, not as a pass.

## 4. Provider registration requirements on Android 9 — source-verified

Everything in this section was read off AOSP tag **`android-9.0.0_r35`** (the Android 9 release
branch), fetched and kept at `/data/data/com.termux/files/usr/tmp/aosp9/` in this session. Paths are
relative to `frameworks/base/`. It is *not* the ROM's own source — the ROM's `services.jar` and
`framework-res.apk` are inside the encrypted payload and could not be read (see
`ROM_INSPECTION_REPORT.md` §3). Where AOSP 9 and a vendor build could differ, that is stated.

### 4.1 The provider list is a framework resource, and only that list

`SystemImpl` (the `SystemInterface` implementation inside `services.jar`) reads exactly one resource:

```java
// services/core/java/com/android/server/webkit/SystemImpl.java:84-85
parser = AppGlobals.getInitialApplication().getResources().getXml(
        com.android.internal.R.xml.config_webview_packages);
```

That is `framework-res.apk` → `res/xml/config_webview_packages.xml`. **A package that is not named in
this XML is never considered as a provider, no matter where its APK is installed.** Confirmed against
the upstream resource file itself (`core/res/res/xml/config_webview_packages.xml`), whose entire
content in AOSP 9 is:

```xml
<webviewproviders>
    <!-- The default WebView implementation -->
    <webviewprovider description="Android WebView" packageName="com.android.webview" availableByDefault="true">
    </webviewprovider>
</webviewproviders>
```

So the brief's report of this ROM's extracted content is consistent with *stock* AOSP 9: one entry,
`com.android.webview`. That is corroboration, not confirmation — the ROM's own file was not read.

### 4.2 The exact XML grammar this build parses

From `SystemImpl.java:57-64` and `:87-120`, the parser accepts:

| Token | Kind | Notes (measured from source) |
|---|---|---|
| `webviewproviders` | document root | `XmlUtils.beginDocument(parser, TAG_START)`, `:86` |
| `webviewprovider` | element | anything else is skipped |
| `packageName` | attribute | **missing ⇒ `AndroidRuntimeException` "…missing package name"**, `:95-99` |
| `description` | attribute | **missing ⇒ `AndroidRuntimeException` "…missing description"**, `:100-104` |
| `availableByDefault` | attribute | compared with `"true".equals(...)`, so anything else is false, `:105-106` |
| `isFallback` | attribute | `:107-108`; at most one fallback, and a fallback must be `availableByDefault` — else `AndroidRuntimeException`, `:111-121` |
| `signature` | **child element** | read by `readSignatures(parser)`, `:110`, `:168-181` |

`readSignatures` only accepts `<signature>` children at the current depth; any other child element is
logged ("Found an element in a webview provider that is not a signature") and dropped — it does not
crash. The text of the tag is decoded as:

```java
// core/java/android/webkit/WebViewProviderInfo.java:42  (actual path: services/…/webkit/WebViewProviderInfo.java)
this.signatures[n] = new Signature(Base64.decode(signatures[n], Base64.DEFAULT));
```

`Base64.DEFAULT` **rejects characters outside the base64 alphabet** and treats the input as a single
stream: the certificate must be **one continuous base64 string with no internal whitespace and no
line breaks**, and the tag must be `<signature>BASE64</signature>` with no space between the element
and the text (`parser.nextText()` at `:173-175` is whitespace-sensitive at the edges). That is why
`reports/proposed_webviewprovider_entry.xml` is a single line.

### 4.3 The four validity gates

`WebViewUpdater.validityResult()` (`services/core/java/com/android/server/webkit/WebViewUpdater.java:428-445`)
runs, in order, for a candidate to be a provider at all:

| # | Gate | Code | Supplied 138 APK |
|---|---|---|---|
| 1 | `targetSdkVersion >= Build.VERSION_CODES.P` | `:430` → `UserPackage.java:37,87-88` | targetSdk **35 ≥ 28 → PASS** (MEASURED) |
| 2 | version code branch ≥ minimum, **skipped when the system is debuggable** | `:433-437`; `versionCodeGE` compares `versionCode/100000` (`:464-469`); the floor is the *lowest* `availableByDefault && !isFallback` factory package's version (`getMinimumVersionCode`, `:481-505`) | branch 7204 vs WebView 81's 4044 → **PASS** by arithmetic; needs the ROM's real factory version, unverifiable here |
| 3 | signature | `providerHasValidSignature` `:506-521` | see below |
| 4 | `com.android.webview.WebViewLibrary` meta-data present | `:441` → `WebViewFactory.getWebViewLibrary` `core/java/android/webkit/WebViewFactory.java:159-161` | `= libwebviewchromium.so` — **PASS** (MEASURED) |

Gate 3 has three branches, and they decide the whole installation strategy:

```java
if (systemInterface.systemIsDebuggable()) return true;              // (a)
if (provider.signatures == null || provider.signatures.length == 0) // (b)
        return packageInfo.applicationInfo.isSystemApp();
if (packageInfo.signatures.length != 1) return false;               // (c) exactly one signer
for (Signature s : provider.signatures) if (s.equals(packageInfo.signatures[0])) return true;
```

- **(a) `systemIsDebuggable()` is literally `Build.IS_DEBUGGABLE`** (`SystemImpl.java:263-266`). On a
  `userdebug` or `eng` guest, gates 2 and 3 are **both skipped**. A `user` build skips neither. This
  is why `getprop ro.build.type` / `ro.debuggable` is in the diagnostics script — it can change the
  plan, not merely confirm it.
- **(b) no `<signature>` child ⇒ the package must carry `FLAG_SYSTEM`.** So the minimal XML entry
  (`<webviewprovider … availableByDefault="true"/>` with no signature) forces the APK into the system
  partition.
- **(c) declaring `<signature>` removes the system-app requirement entirely.** With the Google
  WebView certificate in the XML, a **non-system, `adb install`-ed** `com.google.android.webview`
  passes gate 3. This is the single most useful fact found in this phase: one framework-res edit
  makes every later WebView change a normal app install, needing no platform key again and no
  writable `/system`. It requires the *matching* key at install time, which is the real Google key
  this APK is signed with (§3) — nothing invented.

### 4.4 Selection order — and why "automatic after boot" needs one of two edits

`getValidWebViewPackagesAndInfos()` (`WebViewUpdater.java:261-277`) walks the providers in **XML
document order** and keeps the valid ones; there is no sort. Then `getProviderForUser…`
(`:285-315`) returns:

1. `Settings.Global.WEBVIEW_PROVIDER` if set and that provider is installed and enabled **for all
   users** (`SystemImpl.java:190-198`, `isInstalledAndEnabledForAllUsers` `:330`); else
2. the **first** valid provider with `availableByDefault` that is installed/enabled for all users; else
3. `throw new WebViewPackageMissingException("Could not find a loadable WebView package")` — with the
   upstream comment "This should never happen during normal operation (**only with modified system
   images**)", `:312-316`. A framework-res entry naming a package that isn't installed is precisely
   that case.

Therefore "Google WebView selected automatically" requires **either** placing the
`com.google.android.webview` entry **before** the `com.android.webview` entry in the XML, **or**
setting `webview_provider` after boot (Developer Options writes the same key). Note that the Android 9
loop tests only `availableByDefault`, not `!isFallback`, so an `isFallback="true"` entry is still
auto-selectable here — the fallback flag mainly affects the crash-rollback logic.

### 4.5 Runtime library loading (what else the APK must satisfy)

- The `.so` entries in **both** candidate APKs are `compress_type = 0 (STORED)` (MEASURED), which is
  what Android 9's `WebViewFactory.getLoadFromApkPath` requires to map the library straight out of
  the APK when `extractNativeLibs="false"`. A deflated entry would fail here.
- The loader reserves relro address space and creates
  `/data/misc/shared_relro/libwebviewchromium32.relro` / `…64.relro` in an isolated `WebViewLoader-<abi>`
  child running as `Process.SHARED_RELRO_UID`
  (`services/core/java/com/android/server/webkit/WebViewLibraryLoader.java:50,52,129`). Failure is
  non-fatal — "failed to load with relro file, proceeding without" (`:113`) — so relro is not a
  blocker, but the isolated `WebViewLoader` process must be able to start for the guest ABI in use.

### 4.6 What this means for the modification plan (Phase 5), corrected twice

**Withdrawn claim 1** — "RRO overlays cannot help because overlaying a framework resource requires
`<overlayable>` or the target's key." That was wrong and is now disproved three ways, so the
"BLOCKING" characterisation of the provider-registration step (L3) is **dissolved**:

1. **Source.** `PMS:2609-2616` scans `/vendor/overlay` (and `/product/overlay`) with
   `PARSE_IS_SYSTEM_DIR | SCAN_AS_SYSTEM`; the "must be signed with the platform certificate" throw at
   `PMS:11232-11249` sits in the **else** branch, i.e. it only applies to overlays that are NOT on a
   system partition. `PackageParser.java:2055-2094` requires only `targetPackage`, `isStatic` and a
   priority in 0..9999. `<overlayable>`/`<public>` enforcement is Android 10+ (Omap).
2. **Production files on this Android 9 host.** `/vendor/overlay/FrameworksResCommon.apk` is
   `targetPackage="android" isStatic="true"` and overrides **36 non-public** `android` entries —
   including `config_webview_packages`' own sibling entries, i.e. non-public overlaying ships here.
   And `/vendor/overlay/CarrierConfigResCommon.apk` overrides a **file-type xml resource** the way we
   need: entry `xml/vendor` → `STRING 'res/xml/vendor.xml'` at `0x7f020000`. That is byte-for-byte the
   shape `tools/arsc.py::build_xml_override` reproduces (it matches that file's `resources.arsc`
   exactly, 592 B).
3. **The toolchain gap is closed.** `tools/build_overlay.py` writes the whole overlay APK in pure
   Python — AXML manifest, `resources.arsc`, and the provider XML with the certificate as
   `<signature>` element TEXT — and `tools/verify_overlay.py` re-audits the result independently
   (27 checks, 0 failures). No aapt, no Java, no key.

**Withdrawn claim 2** — the earlier draft of this section (and `patch_framework_res.py`, and
`reports/proposed_webviewprovider_entry.xml` v1) offered a `signature="…" ATTRIBUTE` form. Android 9
never reads that attribute; `SystemImpl.java:166-181` takes the certificate as the **text of a child
`<signature>` element** (`parser.nextText()` → `WebViewProviderInfo.java:42`
`Base64.decode(text, Base64.DEFAULT)`). Verified against the real framework resource on this host
(`tools/selftest_axml.py` T7/T8) and enforced by the auditor. `isFallback` was also over-stated: it
does **not** drive selection — document order plus `availableByDefault` does (`WebViewUpdater.java:261-277`).

**The block that remains is write access, not keys.** The overlay must land in the guest's
`/vendor/overlay`, and the ROM payload is an encrypted container (L2). So: *what* to ship is solved;
*getting it into the system partition* still needs either the container format/key or a writable
`/vendor` inside the running guest. See `reports/INTEGRATION_PLAN.md`.

Still untested, and still the cheapest alternative if it holds: the guest's `framework-res.apk` may be
signed with the **public AOSP test key** (`work/aosp_platform_test_cert.pem`, SHA-1
`27196E386B875E76ADF700E7EA84E4C6EEE33DFA`). One file from the guest decides it. Note this is now a
*fallback*, not the only route.

## 5. Known limitations and risks

| # | Item | Status |
|---|---|---|
| L1 | Supplied `input/webview138.apk` is the wrong ABI for the declared guest | **RESOLVED** by `input/webview138_arm64_universal_138.0.7204.179.apk` (§2.1) — the arm32 file stays unusable |
| L2 | ROM payload encrypted; `/system` unreadable/unwritable → no modified ROM ZIP can be built | **FATAL for deliverable D as literally specified** (`?e=x&c=v2` container, no key, no format doc) |
| L3 | Registering a new provider name needs `config_webview_packages.xml` inside `framework-res.apk` | **SUPERSEDED** — a static RRO in `/vendor/overlay` supplies the same resource with no key (§4.6). APK built and audited: `output/webview138-provider-overlay.apk` |
| L4 | The ROM may be signed with the public AOSP test key | UNTESTED — now only needed for the direct framework-res fallback, not for the primary route |
| L4b | Placing the overlay needs a **writable `/vendor/overlay`** in the guest (root/remount, or an unpacked-and-repacked ROM) | **OPEN** — the one step that cannot be done from this Termux shell. Probe steps in `reports/INTEGRATION_PLAN.md` §3 |
| L4c | An RRO **replaces** the whole resource, so the overlay must carry the guest's *complete* provider list or it silently drops the others. The list built here is `[com.google.android.webview, com.android.webview]`; the guest's real list is unknown because its `framework-res.apk` is inside the encrypted container | RISK — remove by extracting one guest file (§4.6 / `INTEGRATION_PLAN.md` §4, `--base-xml`) |
| L5 | Partition space: the whole payload set is 290 MB encrypted. Adding a 222 MB APK (and a 2.7 KB overlay) to a guest `/system`/`/data` may not fit without a filesystem resize, and no ext4 tooling exists here (`mke2fs`, `e2fsdroid`, `debugfs`, `simg2img` all absent) | RISK |
| L6 | WebView 81 → 138 is 57 major revisions. OAT/VDEX regeneration for a swapped system WebView is expected on first boot, and a stale `webview oat` directory can make the first boot slow or fail; whether stale artefacts must be deleted cannot be determined without reading the image | RISK / UNVERIFIABLE |
| L7 | No runtime environment of any kind is available here (no VM app, no emulator, no root, no mount), so no boot/behaviour claim of any kind is made | UNTESTED |
| L8 | The original `com.android.webview` 81 APK could not be read, so no backup of it was taken and Phase 7 (preserve 81 as a recovery option) could not be executed | BLOCKED |
| L9 | **Boot-loop risk from a malformed provider entry.** `SystemImpl` runs inside `system_server`; a `webviewprovider` element missing `packageName` or `description` throws `AndroidRuntimeException` (`SystemImpl.java:95-104`), zero `availableByDefault` throws (`:138-141`), zero `availableByDefault`-and-not-`isFallback` throws (`:141-144`), and a fallback that is not available-by-default throws (`:113-116`). An entry naming a package that is not installed does *not* throw, but yields `WebViewPackageMissingException` (§4.4 step 3). | MITIGATED — every one of those four rules is asserted at build time and re-asserted by `tools/verify_overlay.py` |
| L10 | With `<signature>` declared, the overlay route needs **no** platform key at all; conversely an entry with **no** `<signature>` falls back to `applicationInfo.isSystemApp()` (`WebViewUpdater.java:506-521`), which a `/data` install does not satisfy. So the DER-in-text form is the only one that works for both a partition install and a normal install. | MEASURED from source; encoded in the shipped overlay |
| L11 | If the guest turns out to be `userdebug`/`eng`, gates 2 and 3 are skipped by `systemIsDebuggable()` (§4.3 (a)) — a materially easier target. The *host* phone is `user`, so no bypass there. | UNTESTED — read `ro.build.type` from `/system/build.prop` |
| L12 | The overlay APK is deliberately **unsigned**. Source says that is legal for `/vendor/overlay`, and the file format is proven, but nothing has been executed: a broken label or an unreadable file makes `idmap` log `Failed to generate idmap for …` and the overlay is ignored (silent, not a boot loop). | UNTESTED — needs one boot |

## 6. Overall compatibility verdict

| Axis | Verdict |
|---|---|
| API level (26–28 band) | COMPATIBLE — `minSdkVersion=26`, `targetSdkVersion=35` read from both APK manifests |
| Signature / certificate | VALID; the same 959-byte Google DER is embedded in **both** APKs, byte-identical to the certificate the overlay declares |
| APK integrity | VERIFIED (CRC clean; v2 signature cryptographically valid) |
| Native ABI | **arm32 file: INCOMPATIBLE. arm64 universal file: COMPATIBLE** (`ELF64 / EM_AARCH64` 130.6 MB `libwebviewchromium.so`) |
| Standalone vs splits | **STANDALONE** — `res/xml/splits0.xml` maps all 83 locale keys to `split=""` (the base APK) and all `.pak` data is inline in `assets/` |
| targetSdk / version code / WebViewLibrary meta-data gates | PASS on the arithmetic (§4.3); version-code floor needs the ROM's factory WebView version |
| Provider registration | **ACHIEVABLE without any key** — built and audited as a static RRO (§4.6). Not *deployed*: see L4b |
| Modified ROM ZIP | **NOT PRODUCEABLE** (encrypted container) — the overlay + documented install steps is the substitute deliverable |

`com.google.android.webview` 138 *can* be a valid, auto-selected provider on an Android 9 arm64 guest:
the correct-ABI build is on disk, the registration artefact is built and independently audited, and no
signing key is required for either. What has not been done — and cannot be done here — is putting
those two files into a running guest and observing a boot. See `VALIDATION_REPORT.md` §5 and
`reports/INTEGRATION_PLAN.md`.

---

## 7. Corrections made to this report during the session

Recorded so nothing is quietly retracted.

| Was claimed | Now | Basis |
|---|---|---|
| "targetSdkVersion 35 — irrelevant for a provider APK" | **Relevant**: `targetSdk >= P` is gate 1 of provider validity | `UserPackage.java:37,87-88` |
| "system scan rejects it with `INSTALL_FAILED_NO_MATCHING_ABIS`, so it never appears in Developer Options" | That is the **`adb install`** path. Because the APK is `android:multiArch="true"`, the boot scan swallows −113 and registers it anyway → runtime dlopen failure instead. | `PackageManagerService.java:11715,11743,16077-16084`; manifest line 11 |
| "`framework-res.apk` carries `sharedUserId="android"`, so a re-sign is a boot-loop" | **Withdrawn as unverified** (file never read; mechanism not checked against source this session) | §4.6 |
| "RRO cannot substitute" | **Withdrawn as unverified** — RRO is unassessed, not ruled out | §4.6 |
| "provider list needs the package name; a system-app flag is mandatory for a permanent provider" | Refined: a `<signature>` child **removes** the system-app requirement (§4.3 case (c)) | `WebViewUpdater.java:506-521` |

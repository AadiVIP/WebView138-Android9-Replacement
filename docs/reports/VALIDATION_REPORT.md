# Validation Report — Phase 9

Every test actually executed, and every test that could not be executed. Nothing here is inferred
from a test that did not run. Tooling: pure-Python parsers written for this job
(`work/apkinfo2.py`, `work/verify_sig.py`), plus `unzip`, `brotli`, `xz`, `zstd`, `sha256sum`.
Raw command output is preserved in `reports/raw_apk_analysis.txt` and
`reports/raw_sig_verification.txt`.

---

## 1. APK validation — all PASS

| # | Check | Claimed | Measured | Result |
|---|---|---|---|---|
| 1 | Package name | `com.google.android.webview` | `com.google.android.webview` | PASS |
| 2 | Version name | 138.0.7204.181 | `138.0.7204.181` | PASS |
| 3 | Version code | 720418100 | `720418100` | PASS |
| 4 | minSdkVersion | 26 | `minSdkVersion=26` | PASS |
| 5 | maxSdkVersion | 28 | `maxSdkVersion=28` | PASS |
| 6 | targetSdkVersion | — | `35` | INFO |
| 7 | Native ABI | armeabi-v7a only | only `lib/armeabi-v7a/` present | PASS (confirmed) |
| 8 | ELF architecture | — | both `.so` = **ELF32, `e_machine=EM_ARM (0x28)`** | 32-bit ARM |
| 9 | Required libs | libwebviewchromium.so, libcrashpad_handler_trampoline.so | both present, 78,403,132 B and 3,112 B | PASS |
| 10 | ZIP integrity | — | `ZipFile.testzip() → None` (all 462 entries CRC-OK) | PASS |
| 11 | APK Signing Block | — | magic `APK Sig Block 42` at 91,369,456; block start 91,361,280, size 8,184; size fields agree | PASS |
| 12 | Signing schemes present | — | v2 (0x7109871a) + v3 (0xf05368c0) + 0x6dff800d + 2 vendor pairs; **no v1/JAR pair** | INFO |
| 13 | Cert SHA-1 | `1F387CB25E0069EFCA490ADE28C060E09D37DD45` | identical | **PASS (matches)** |
| 14 | Cert SHA-256 | `6FAF3C4140407473400934D117815A21AF1CFEFC5C0BEE61C858BC3D72BA6FE5` | identical | **PASS (matches)** |
| 15 | Certificate identity | "Issuer/subject identifies Google" | X.509 v3, self-signed, `C=US ST=California L=Mountain View O=Google Inc. OU=Android CN=webview`, serial `0x0d8ba0e00501b8653`, RSA-2048 e=65537, `sha1WithRSAEncryption`, valid 2014-08-08 → 2041-12-24 | PASS |
| 16 | **Cryptographic v2 signature verification** | — | RSA-2048 PKCS#1 v1.5 **SHA-256** over the `signedData` structure: **VALID** | **PASS** |
| 17 | Signer key == cert key | — | modulus comparison: identical | PASS |
| 18 | **Certificate self-signature verification** | — | RSA-2048 PKCS#1 v1.5 **SHA-1** over `tbsCertificate`: **VALID** | **PASS** |
| 19 | `WebViewLibrary` meta-data | — | `com.android.webview.WebViewLibrary = libwebviewchromium.so` | PASS |
| 20 | File SHA-256 | — | `a7de80d7b69d4b38436c6e6cc09479a2e71008083e96b9b620a9abbd9bc13d33` | recorded |

Also observed in the manifest (relevant to integration, not validated as good/bad):
`android:multiArch="true"`, `android:extractNativeLibs="false"`,
`android:isolatedSplits="true"`, `compileSdkVersion=36`, label "Android System WebView",
40 `SandboxedProcessServiceN` + `JsSandboxService0` (isolated, external), `:webview_service`,
`:webview_apk`, `:sandboxed_process*`, `:js_sandboxed_process0` processes, and
`NUM_SANDBOXED_SERVICES=40`. No `android:use32bitAbi` attribute is present.

The full DER signing certificate was recovered and saved
(`work/V2_cert.der`, `reports/google_webview_signing_cert_base64.txt`, 959 bytes / 1,280 base64
chars). A second, unrelated Google chain (CN=Android, 1,421 B, SHA-256 `3257D599…`) is carried in
pair `0x6dff800d`; its SHA-256 equals the APK's `stamp-cert-sha256` entry, i.e. it is the Play
"stamp" verifier key, not the WebView provider key.

**Limits of the APK validation:** the v2 *signature over signed-data* was verified with real
modular arithmetic, which cryptographically binds the signed-data block (and therefore the
content-digest structure inside it). The per-file 1 MiB-chunk content digests were **not**
re-derived, because that requires `apksigner`/Java or a from-scratch reimplementation of the v2
chunked-digest tree, and a partially-correct reimplementation would produce a false negative.
This is stated as an omission, not as a pass.

---

## 2. ROM package validation

| Check | Result |
|---|---|
| Outer ZIP integrity (`unzip -l`, 4 entries, 391,321,487 B of content) | PASS — archive reads cleanly |
| Copy fidelity of both inputs | PASS — SHA-256 identical to the originals in `/sdcard/Download` |
| `manifest.json` parses as JSON, all keys enumerated | PASS |
| Outer ZIP signature / `META-INF/com/google/android/*` | **ABSENT** — the package is unsigned at the ZIP level |
| `system.img` / `vendor.img` / `product.img` / `super.img` / `boot.img` / `vbmeta.img` / `payload.bin` / `system.new.dat(.br)` / `system.transfer.list` | **ABSENT** — none of these exist in the package |
| Install scripts (`update-binary`, `updater-script`, `install.sh`, `update.sh`) | **ABSENT** — there is no script layer to inspect or modify |
| Image format identification (ext4 @1024, sparse magic, cpio, FFS, ext superblock) | **NOT A KNOWN FORMAT** — no filesystem magic at the canonical offsets |
| Embedded-magic sweep of all 3 payloads (ZIP, sparse, ext4, f2fs, squashfs, erofs, 7z, zstd, lz4, gzip, bzip2, ISO9660, FAT) | **NO STRUCTURAL HITS** — every 2-byte count sits within noise of the random baseline; every long magic count is exactly 0 |
| Headerless compression decode (raw DEFLATE wbits −15 / 47, LZMA raw, LZMA alone, bzip2, brotli raw, zstd, gzip) | **ALL FAILED** — `brotli -dc` → `corrupt input`; zlib/lzma/bz2 raised |
| Entropy | 8.0000 / 7.9999 / 8.0000 bits-per-byte; 0.39 % zero bytes | 
| Repeating-XOR / keystream-reuse tests | **NEGATIVE** — index of coincidence flat (0.0037–0.0042 vs 0.0039 baseline) for lags 2–4096; `rom.img XOR rom1.img` has no zero run > 12 B in 4 MiB; printable-run density equals random expectation |
| Verdict | Payloads are **encrypted with a Virtual-Master-private scheme**; the `?e=x&c=v2` container spec and key are only inside the app |

### Configuration / package-registration validation
**NOT PERFORMED — impossible.** There is no readable `/system`. Therefore the following brief
items could not be executed at all, and no substitute assumption was made:

- existing WebView 81 APK, package name, version, signing certificate, native libraries (Phase 2.1–5)
- OAT / VDEX / ODEX artefacts and whether stale compiled files must be deleted (Phase 2.6, 6)
- APK location, ownership, permissions, SELinux contexts (Phase 2.7–9)
- `framework-res.apk` resource table, package IDs, `<webviewproviders>` XML, overlays (Phase 2.11–12, Phase 5)
- `ro.product.cpu.abi*`, bionic linker, `/system/lib` vs `/system/lib64`, zygote config (Phase 4)
- partition layout, filesystem types, dynamic-partition and AVB/dm-verity status (Phase 1.5–8)

Searching the extracted ROM for `com.android.webview`, `webviewproviders`,
`config_webview_packages`, `WebViewLibrary` etc. returns nothing for the obvious reason: the files
are ciphertext. A grep over encrypted bytes is not evidence about their contents, so it was not
presented as a search result.

---

## 3. Rebuild validation

**NOT PERFORMED.** No modified ROM ZIP was built, because the images inside the package cannot be
decrypted, modified and re-encrypted into a container Virtual Master would accept. Producing an
archive with byte-identical `rom.img` / `rom1.img` would contain no WebView 138 and would be a
false deliverable. Correspondingly no `webview81_restore.zip` was produced: there is no change to
roll back, and a rollback ZIP that cannot be imported by the app would be misleading.
See §5 for what *can* be delivered instead.

---

## 4. Boot validation

**NOT PERFORMED — no runtime test of any kind was executed.** Reasons, all verified in this
session:

1. Virtual Master is not installed on this host (full `pm list packages` dump, 274 packages, no
   VM/emulator package).
2. The session runs as a non-root `untrusted_app` with no `mount`, no `su`, no emulator, no
   QEMU/QEMU2, no AVD, and no ext4 userspace tooling (`debugfs`, `mke2fs`, `simg2img` all absent).
3. There is no decrypted guest image to boot.

Accordingly there is **no** evidence that Android boots, that Package Manager recognises Google
WebView, that 138 appears in Developer Options, that it can be selected, or that page rendering
and JavaScript work. Every success criterion that depends on runtime behaviour is untested.

---

## 5. Blocking findings (summary of what stops the project)

| # | Blocker | Severity | Evidence |
|---|---|---|---|
| B1 | Guest is **arm64-only**; the supplied APK is **armeabi-v7a-only** | **FATAL** | `manifest.json "support_a32": false` + both `.so` are ELF32/EM_ARM |
| B2 | ROM partition payload is **encrypted**; `/system` cannot be read or rewritten | **FATAL for a modified ROM ZIP** | §2 entropy/magic/codec/IoC battery |
| B3 | Registering a *new* provider name needs `framework-res.apk` edited and re-signed with the ROM's **platform key**, which is not available | ~~FATAL~~ → **SUPERSEDED, see §7**: a static RRO in `/vendor/overlay` needs no key | framework-res is unreadable (B2); platform signing key not in the package |
| B4 | No ext4 / image tooling, no root, no mount, no emulator in this environment | Prevents local rebuild and all boot testing | §7 of the inspection report |
| B5 | A malformed `config_webview_packages.xml` entry crashes the system server (`AndroidRuntimeException` from `SystemImpl`), so a mistake is a boot loop rather than a fallback | Risk, must be managed before any flash | `SystemImpl.java:95-104`, `:111-121` — see §6 |
| B6 | The overlay must be **placed** in `/vendor/overlay` or `/product/overlay`, i.e. a system partition — B2 blocks writing there | **OPEN**, decides whether the plan in `reports/INTEGRATION_PLAN.md` can be executed | `manifest.json` codec `v2`; probe steps `INTEGRATION_PLAN.md` §3 |

B1 is the one that decides the *choice of APK* and is fixable by the user: an **arm64-v8a** build of
WebView 138 with `maxSdkVersion=28` is the correct artefact for this guest, and the supplied
`armeabi-v7a` APK is the wrong variant regardless of everything else. B2/B3 mean that even with the
right APK, a modified ROM ZIP cannot be produced from these inputs by this route.

---

## 6. Addendum — what changed after the Android 9 source was actually read

The provider-selection requirements in B3 were later verified against AOSP
`android-9.0.0_r35` rather than inferred (see `WEBVIEW_138_COMPATIBILITY.md` §4 for the citations).
Three consequences for this blocker table, none of which changes any verdict above:

- **B3 is narrower than first stated.** If the framework's provider entry declares a
  `<signature>` child containing the Google WebView certificate, `providerHasValidSignature`
  (`WebViewUpdater.java:506-521`) no longer requires `FLAG_SYSTEM`. So **one** successful
  `framework-res.apk` edit is enough, after which every further WebView change is a normal
  `adb install` needing no platform key and no writable `/system`. B3 therefore asks a single
  question: *what key signed this ROM's framework-res.apk?* If it is the public AOSP test key
  (`work/aosp_platform_test_cert.pem`, SHA-1 `27196E38…3DFA`), B3 dissolves legitimately.
- **B1's predicted symptom was corrected.** The supplied APK is `android:multiArch="true"`, so the
  boot scan swallows the ABI error and registers it; the failure would surface as a runtime dlopen
  error, not as a clean install rejection. Still fatal, differently. `WEBVIEW_138_COMPATIBILITY.md`
  §2.0.
- **New risk B5: a malformed provider entry is not a no-op.** `packageName` and `description` are
  mandatory attributes, and `SystemImpl` throws `AndroidRuntimeException` while the system server
  parses the resource (`SystemImpl.java:95-104`, `:111-121`) — i.e. a syntax mistake in
  `config_webview_packages.xml` is a boot loop, not a graceful fallback. The paste-ready entry in
  `reports/proposed_webviewprovider_entry.xml` is written against that grammar and round-trip
  checked (959-byte DER ↔ 1,280-char single-line base64).

Nothing in this addendum was tested at runtime. No ROM was modified, no image was written, nothing
was flashed, and no boot was attempted.


---

## 7. Second addendum — the RRO route, and what was actually built

Everything below was executed in this session; the tests are named so they can be re-run.

**B3 is dissolved, and the reason is a rule I verified rather than assumed.** Android 9 scans
`/vendor/overlay` and `/product/overlay` with `PARSE_IS_SYSTEM_DIR | SCAN_AS_SYSTEM`
(`PMS:2606-2620`), and the "must be signed with the platform certificate" throw
(`PMS:11232-11249`) is in the **else** branch — it applies only to non-system overlays. So a *static*
RRO can supply `android:xml/config_webview_packages` with **no key at all**. `PackageParser.java:2055-2094`
needs only `targetPackage`, an explicit `isStatic="true"` (the default is false) and priority 0..9999;
`<overlayable>`/`<public>` enforcement is Android 10+ and does not apply here.

Production evidence from this host (an Android 9 `user` build, arm64):

| Evidence | Measured |
|---|---|
| `/vendor/overlay/FrameworksResCommon.apk` | `targetPackage="android" isStatic="true"`, overrides **36 non-public** `android` entries → non-public overlaying ships on this OS |
| `/vendor/overlay/CarrierConfigResCommon.apk` | overrides a **file-type xml** resource: `xml/vendor` → `STRING 'res/xml/vendor.xml'` at `0x7f020000` — the exact encoding `tools/arsc.py` produces |
| `tools/arsc.py::build_xml_override` | reproduces that file's `resources.arsc` **byte for byte** (592 B) |
| `tools/selftest_axml.py` T7 | a `<signature>` node and its CDATA chunk I build are **byte-identical to aapt2's** (mod `lineNumber`) on the real `/system/framework/framework-res.apk` |
| `frameworks/native cmds/idmap/scan.cpp` (retrieved for this tag; `create.cpp` came back as binary junk and was deleted, so nothing rests on it) | `:179-182` returns the priority **only** for `is_static_overlay`, else `NO_OVERLAY_TAG`; `:118-120` enforces priority 0..9999; `:148-151` requires an exact target-package string match; and the file contains **zero** signature or certificate code — a second, independent confirmation that nothing in the overlay path checks a signer |

**Artifact built:** `output/webview138-provider-overlay.apk` (2688 B) —
`resources.arsc` (624 B, STORED, data offset 44 → 4-byte aligned for mmap), `AndroidManifest.xml`
(1340 B), `res/xml/config_webview_packages.xml` (1956 B). Provider order
`[com.google.android.webview, com.android.webview]`, Google first, `availableByDefault="true"`, no
`isFallback`, certificate as `<signature>` **element TEXT** (1280-char single-line base64 of the
959-byte Google DER). Deliberately **unsigned**.

**Tests run:** `tools/selftest_axml.py` → **171 checks, 0 failures**;
`tools/verify_overlay.py` → **27 checks, 0 failures**; `tools/patch_framework_res.py inspect` and
`tools/build_overlay.py` round-trip the certificate to the same SHA-1
`1F387CB25E0069EFCA490ADE28C060E09D37DD45`.

**The audit found a real defect, which is the argument for having two tools.** The from-scratch XML
path emitted the base64 as **bare CDATA under `<webviewprovider>`**, not inside `<signature>`. The
builder's own check used `text_values()`, which returns every CDATA in the document regardless of
position, so it passed. Android 9 would have read **zero** signatures and fallen back to
`applicationInfo.isSystemApp()` (`WebViewUpdater.java:506-521`) — a `/data` install fails that. Fixed
in `axml.py::AXMLDoc.element` (now wraps in `<signature>`), both tools switched to one depth-aware
reader `AXML.webview_providers()`, and `selftest_axml.py` **T8** locks the behaviour in both
directions: the wrapper is read, and an identical bare CDATA is **not**.

**Corrections to two earlier claims, both now measured:**
- the `signature="…"` **attribute** form is never read by Android 9 (element text only);
- `isFallback` does **not** drive selection — document order plus `availableByDefault` does
  (`WebViewUpdater.java:261-277`, `:305-315`).

**Newly measured facts that answer open questions:**
- the two supplied WebView APKs are signed by the **same** 959-byte certificate, byte-identical in the
  v2 **and** v3 blocks of each → the overlay is correct for whichever build is installed;
- `input/webview138_arm64_universal_138.0.7204.179.apk` is **standalone**: `res/xml/splits0.xml` maps
  all 83 locale keys to `split=""` (the base APK) and every `.pak` (`chrome_100_percent.pak`,
  `icudtl.dat`, `resources.pak`, `snapshot_blob_32/64.bin`, 83 `stored-locales/*.pak`) is inline in
  `assets/`. **No companion split is required.**
- `minSdkVersion=26` on both → API 28 installs them; `targetSdkVersion=35`; one certificate →
  `packageInfo.signatures.length == 1` gate satisfied (`WebViewUpdater.java:514`).

**What did not change:** B2 still stands, so **deliverable D (a modified ROM ZIP) cannot be produced**
(`rom.img`/`rom1.img`/`play.zip` all `?e=x&c=v2`, same 8-byte container magic, no ext4 superblock at
0x438, no sparse header, no key, no format documentation, no tooling). Deliverable E as specified is
likewise impossible; the functional equivalent — delete the one overlay file, reboot — is in
`reports/INTEGRATION_PLAN.md` §7, and it works because the factory `com.android.webview`
81 is never touched.

**Runtime validation: none performed.** No guest was booted, nothing was flashed, `idmap` was never
executed, and no WebView page was rendered. The remaining unknown is **B6** — write access to a system
partition inside the guest — which is a deployment question, not a design one, and is probed in
`reports/INTEGRATION_PLAN.md` §3.


## 8. Third addendum — deployment preparation (probe, installer, audit chain)

Approved direction: "I approve the RRO approach, subject to runtime verification." This section records
what was prepared for deployment and what is still unverified. **No installation has been performed.**

### Tools added

| Tool | Mode | Status |
|---|---|---|
| `tools/guest_probe.sh` | read-only by default; `--test-write` and `--extract` are separate opt-ins | executed read-only **on this Android 9 host**, and both opt-in branches executed against a sandbox directory. 2 defects found and fixed (§3) |
| `tools/install_overlay.sh` | `check` (default, writes nothing) → `install` / `install-apk` / `uninstall`, each gated behind `--i-reviewed` | full lifecycle exercised in a sandbox: install, idempotent re-install, tamper-refusal, rollback, refusal with no record, refusal for `/system` and foreign targets, fake-`pm` success and failure paths. 2 defects found and fixed (§3) |
| `--write-manifest` in `tools/verify_overlay.py` | emits the sha256 + every `<overlay>` rule + the provider list | written **only** when all checks pass; proven by making one check fail (wrong `--package`) and seeing the manifest refused |

`output/webview138-provider-overlay.manifest` (25 lines) is the link between the off-device audit and the
on-device write: the installer re-hashes the staged file and aborts on any mismatch, so the bytes that
reach `/vendor/overlay` are the bytes that were checked.

### Measured while validating the probe on the host (Android 9, API 28 — the host, not the guest)

- `/vendor/overlay` exists, `drwxr-xr-x root:shell`, label `u:object_r:vendor_overlay_file:s0`,
  **9 APKs** in it; `pm list packages -s | grep -ci overlay` = **15**. Static RROs are a live mechanism
  on Android 9 images of this vintage, which is the class of evidence the guest probe is designed to
  collect.
- `/vendor` mounted `ro` from `/dev/block/dm-2`; no `overlay` line in `/proc/filesystems`; `/` is the
  system-as-root ext4 mount, also `ro`.
- `ro.build.type=user`, `ro.debuggable=0`, `abilist32=armeabi-v7a,armeabi`.
- `/system/bin/idmap` exists but this uid **cannot stat it** — reporting that as "absent" would have
  been wrong, which is why the probe distinguishes the two.
- `dumpsys webviewupdate` as an untrusted uid returns `Permission Denial: ... missing
  android.permission.DUMP`. The verification section therefore gives a root path **and** a no-root path
  (the user-agent string of a rendered page).
- `unzip -p /system/framework/framework-res.apk res/xml/config_webview_packages.xml` produced a
  **5348-byte** file, byte-identical to the stand-in already used to test the builder — so §6 item 1 can
  be obtained by shell *or* by MiXplorer, and the size/hash is checkable either way.

### Test totals right now

`selftest_axml.py` **171 checks / 0 failures**; `verify_overlay.py` on the shipped 2-provider build
**26 checks / 0 failures**; on the 6-provider from-base build (`work/overlay_from_base.apk`, base = the
real Android 9 host file) **36 checks / 0 failures**, including every non-Google provider "carried
verbatim" and `provider count unchanged (6 -> 6)`.

The base-driven build also demonstrated the `isFallback` hazard concretely: the real base file lists
`com.google.android.webview` with `isFallback=True` and no signature. The builder moves it first, sets
`availableByDefault=true`, attaches the certificate, and **forces `isFallback=false`** — because
fallback logic is on by default (`SystemImpl.java:212-216`) and the platform disables the flagged
provider once a valid non-fallback one exists (`WebViewUpdateServiceImpl.java:202-220` →
`SystemImpl.java:225-235`). Without that normalisation, installing 138 would have given the platform a
supported way to switch it off.

### Still unverified (unchanged)

- **Runtime validation: none.** No guest boot, no `idmap` execution, no SELinux label observation on a
  copied file, no page rendered, no `dumpsys webviewupdate` after install.
- **B6** — writability of `/vendor/overlay` or `/product/overlay` inside the guest — is still unknown;
  the probe measures it and the installer reports the real `EACCES`/`EROFS` if it fails.
- The guest's own provider list (§6 item 1) is still unknown; the shipped overlay is the 2-entry build
  until that file arrives, at which point it is rebuilt with `--base-xml` and re-audited.

## 9. Fourth addendum — the Magisk module (Option A), and the seven pre-delivery tests

Deliverable: `output/WebView138-Replacement-Magisk.zip`, 18181 B, sha256
`b6323730c2fe56894477d2cf854c18c8e1732f4befa04c05ed3572bc89797955`, module id
`webview138-replacement`. Built by `tools/build_magisk.py` from the already-audited overlay bytes; the
builder refuses to run without `output/webview138-provider-overlay.manifest` (which `verify_overlay.py`
writes only when every check passed) and refuses a payload whose sha256 differs from it. Method,
entry-by-entry contents and the Option A requirement mapping are in `INTEGRATION_PLAN.md` §4B.

**Nothing in this addendum has been executed on a device.** No Magisk install, no flash, no module
directory written, no reboot, no `settings` change on any Android system — neither the guest nor the
host. Everything below is a static analysis plus a sandboxed re-run of the scripts against shims.

### 9.1 Test totals (all re-run after the last code change)

| Suite | Command | Result |
|---|---|---|
| AXML parser | `python3 tools/selftest_axml.py` | **176 checks / 0 failures** (T9 pins the "guest base lacks Google" path) |
| Overlay audit (standalone, no base) | `python3 tools/verify_overlay.py …` | **26 checks / 0 failures** |
| Overlay audit vs the guest's real `config_webview_packages.xml` | same, `--base-xml work/guest_config_webview_packages.axml` | **31 checks / 0 failures** |
| Overlay audit (6-provider from-base regression, host XML as base) | same, `work/overlay_from_base.apk` | **37 checks / 0 failures** |
| Module ZIP structure + script lint | `python3 tools/audit_magisk.py` | **84 checks / 0 failures** |
| Module lifecycle in a sandbox | `python3 tools/selftest_magisk.py` | **56 checks / 0 failures** |
| Build determinism | `build_magisk.py` run twice | identical sha256 both times (`b3301ec6…` → `b6323730…` after the last fix, then stable) |

### 9.2 The seven pre-delivery tests, each answered with its evidence

1. **Module ZIP structure** — `audit_magisk.py` re-opens the finished archive (it does not read the
   builder's own assumptions): CRC verified on every entry (`testzip()`), no entry name absolute or
   containing `..`, nothing outside `META-INF/com/google/android/` and `webview138-replacement/`,
   largest entry 10227 B (so no smuggled binary), `updater-script` exactly `#MAGISK`,
   `module.prop` has id/name/version/versionCode/author/description with **id == the directory name**
   (Magisk requires this) and no CR / non-ASCII / spaces in the id, exactly one APK in the module and it
   sits at `system/<partition>/overlay/`, that APK is **STORED** (compress_type 0) so it lands byte-for-byte,
   its sha256 equals both the on-disk `output/webview138-provider-overlay.apk` and the embedded
   manifest, and the embedded manifest is byte-identical to the audited one. The staged tree
   `work/magisk_stage/` is compared against the archive entry by entry.
2. **All scripts audited** — `customize.sh`, `service.sh`, `uninstall.sh`, `update-binary` and the
   companion `tools/magisk_deploy.sh` are each linted for forbidden commands and for `rm` targets,
   each must have a shebang and must `exit 0` on success, and each is parsed with
   `/system/bin/sh -n` on this Android 9 machine — whose `/system/bin/sh` is
   `@(#)MIRBSD KSH R56 2018/01/14 Android`, i.e. **Android 9's own mksh**, so this is real API-28 shell
   syntax validation and not a bash approximation. (Two bugs only this could catch were found and
   fixed: a bash-only `${got%%${got:24}}` in a POSIX template, and a `--src` option parser that exited
   on the flag itself.)
3. **Destructive-command scan** — a regex table over every script body, with heredoc bodies blanked
   first so *printed instructions* are not mistaken for *executed* ones: no `mkfs`, no
   `dd … of=/dev/`, no `mount -o remount`, no `pm uninstall`, no `pm disable`, no `pm clear`, no
   `settings delete global webview_fallback*`, no `fastboot`/`stop`/`start`, no `killall`/`pkill`, no
   `curl`/`wget` (offline rule), no write to a device node other than `/dev/null`, no `chmod`/`chown`
   targeting `/system|/vendor|/product`, no `restorecon` on `/system`, no `reboot`/`shutdown` command,
   no recursive `rm` of `/`. Every `rm` must target a path under `$MODPATH`, `$MODDIR`, `$WORK`, `$TMP`,
   `$STAGE`, `$SCRATCH`, `$DEST` or `/data/adb/modules/`. `magisk_deploy.sh` additionally pins its delete
   with `case "$DEST" in /data/adb/modules/"$MOD_ID")` before `rm -rf`, and both `service.sh` and
   `uninstall.sh` may touch only the `webview_provider` key.
4. **It does not touch the host Android system** — proved by measurement, not intention. The sandbox
   matrix ran every script and then asserted: **E1** the real `/vendor/overlay` listing is unchanged and
   no module was created in the real `/data/adb/modules`; **E2** the three input files still hash to
   `9c3c90722621f3020ceb65c33cad5e04` (ROM), `5758db9961beea4708e0a7d27bbb7ffc` (`.181`),
   `109c5b3230e526c1ae447fd7909277bf` (`.179`); **E3** the shipped overlay still matches its manifest;
   **E4** the host's own `Settings.Global.webview_provider` is untouched (`''` before, `''` after); **E5**
   `/proc/mounts` is byte-identical, so nothing was bind-mounted or remounted. E4 exists because the
   first version of the harness **would have written the host's real setting**: `service.sh` prefixes
   `/system/bin` ahead of the shim directory, so `settings` resolved to the framework's. The fix is a
   sandbox-only hook — `service.sh`/`uninstall.sh` honour `QODER_SHIM`, and `magisk_deploy.sh` honours
   `QODER_SHIM`/`QODER_ALLOW_TARGET`/`QODER_UID` — each documented in the script and inert unless
   somebody sets it, which on a device nobody does.
5. **Rollback restores WebView 81** — **B4** runs `uninstall.sh` in the sandbox and asserts the pinned
   value goes back to exactly what was backed up (`com.android.webview`), with **B2** proving the backup
   is taken *before* the first write and **B3** that a second boot does not clobber the backup with its
   own value; **A12** shows `--remove` runs that rollback and deletes only this module's directory, and
   **A10/A13** show it refuses to delete a foreign module or an absent path. WebView 81 is never
   modified by anything here, so after removal + reboot the factory provider is authoritative again —
   this is a *reboot*, not a reinstall, which is why the "do not remove 81 until 138 is valid and
   selectable" rule is satisfied structurally rather than by timing.
6. **Provider registration logic** — re-derived from the finished ZIP, not from the builder: provider #1
   is `com.google.android.webview`, `availableByDefault=true` (else `WebViewUpdater.java:306-316` never
   auto-selects it), `isFallback=false` (else `WebViewUpdateServiceImpl.java:202-220` →
   `SystemImpl.java:225-235` **disables** it), `provider_count >= 2` so the factory entry survives (else
   `SystemImpl.java:138-144` throws and the device has no WebView), exactly one Google entry,
   `targetPackage=android`/`isStatic=true`, the `<signature>` is the full 959-byte Google certificate
   as single-line canonical Base64 (1280 chars, `WebViewProviderInfo.java:42` uses `Base64.DEFAULT`), it
   decodes and matches `cert_sha256`, and it is the same certificate the 138 APK carries
   (`6faf3c41…ba6fe5` == `6faf3c41…ba6fe5`). `customize.sh`'s own gates are exercised separately: **C2**
   refuses API 29, **C4** refuses tampered bytes, **C5** relocates to `/product/overlay`, **C6** refuses
   when neither scanned directory exists, **C7** refuses a Google-is-fallback list, **C8** refuses an id
   mismatch. **B7** covers the failure mode that matters most: if magic mount did not deliver the file,
   the log says `OVERLAY NOT MOUNTED` instead of assuming success.
7. **What remains untested** — in §9.4.

### 9.3 Bugs this round of testing found (all fixed, all re-proved)

- `service.sh`'s opt-in install read its source path through `tr -d ' \t'` written inside a raw Python
  template, so `tr` received a literal backslash-t and deleted every **t** in the path
  (`/daa/daa/com.ermux/…`); the branch then reported "does not exist" for a file that did.
- `selftest_magisk.py` truncated `webview138-apk.prop` before reading it (`open(p,'w').write(re.sub(…,
  open(p).read()))` — evaluation order), which made B10 test a blank file instead of an install.
- The auditor's redirect rule flagged `2>/dev/null` as a device-node write; it now allows `/dev/null`.
- The B13 case as first written set the Google package to *installed*, which correctly skips the whole
  auto-install branch — so it was passing for the wrong reason; it now leaves the package absent.
- `guest_probe.sh` §9 and `magisk_deploy.sh` both printed "no Magisk / DOES NOT EXIST" from
  `[ -d /data/adb ]`. Measured here: `stat /data/adb` and `stat /data/adb/nonexistent-xyz-123` return
  the *same* EACCES to uid 10180, because `/data` is `0771` under SELinux — so absence was not
  knowable, only silence was. Both now distinguish PRESENT / ABSENT / NOINFO from the errno
  (`guest_probe.sh` `classify()`, verdict `PROBE_MAGISK_DATA_ADB=NOINFO` here) and the helper refuses
  an install from a non-root shell instead of concluding the device is unrooted. Pinned by
  `audit_magisk.py` and by selftest **A14** (2 checks). `PROBE_SU` was also clarified: a `su` *binary*
  is on PATH in Termux while the shell is uid 10180, so `PROBE_UID` is emitted next to it.
- A sandbox `run()` helper silently dropped per-call environment overrides, so an early version of the
  matrix aimed `MODULES_DIR` and `VDIR` at the **real framework paths**; that is the direct cause of the
  `QODER_SHIM`/`QODER_ALLOW_TARGET` guards and the E4/E5 assertions in §9.2 item 4.

### 9.4 Explicitly unverified — read before installing

1. **Whether the guest has Magisk at all — currently an open question, not a "no".** On the physical
   host `/data/adb` is **NOINFO**: an unprivileged shell cannot tell absence from unsearchability
   (`/data` is `0771` + SELinux; `stat` answers EACCES for both). Inside the guest it is measurable only
   from root, which is what `tools/guest_probe.sh` §9 is for (`PROBE_MAGISK_DATA_ADB`,
   `PROBE_MAGISK_MODULES_DIR`, `PROBE_MAGISK_MODULES`, `PROBE_MAGISK_VERSION`, `PROBE_UID`,
   `PROBE_ENFORCE`). Without Magisk in the guest, Method B does not exist and only Method A or C
   applies. A `su` binary's presence is not proof of a working root (`PROBE_UID` is printed next to
   `PROBE_SU` for that reason), and `magisk_deploy.sh` refuses to install — rather than to create
   `/data/adb/modules` — when it cannot see a Magisk module directory.
2. **`update-binary` compatibility.** It is a re-implementation because Magisk's template and
   `util_functions.sh` are not on this machine and may not be downloaded (offline rule). The drop-in
   directory route (`magisk_deploy.sh --install`) is the interface Magisk consumes at boot and the one
   the 54-check matrix exercises; the flashable path is convenience and is unproven against an unknown
   Magisk build.
3. **Magic-mount semantics for what this module asks.** Whether a *brand-new* `system/vendor/overlay/`
   directory is created by magic mount on this Magisk version, and whether SELinux labels on files
   copied from `/sdcard` satisfy what PMS needs to read them, are properties of Magisk and of the
   device's policy. The tooling **reports** the measured `ls -Z` context instead of guessing, and
   compares it against a neighbouring real module.
4. **`idmap` success on the guest.** Android 9 logs an idmap failure at
   `PackageManagerService.java:839-841` and then silently skips the overlay. Evidence is
   `boot-verify.log` plus `logcat`; absence of that evidence is not success.
5. ~~**The guest's real `config_webview_packages.xml`.**~~ — **RESOLVED.** The user supplied the
   guest's actual file: exactly one provider, `com.android.webview` (`availableByDefault="true"`, no
   fallback, no signature). `tools/xml_to_axml.py` compiles it to AXML, the overlay is rebuilt against it,
   and the result is **byte-identical** to the shipped payload (sha256 `a78b7978…`) — auditing 31/0 with
   the guest entry preserved verbatim. No other provider is dropped, because the guest has no other
   provider. Pinned by `selftest_axml.py` T9.
6. **API 28 only, by construction.** `maxSdkVersion 28` on the package and an explicit
   `API -eq 28` gate in `customize.sh`: from Android 10 a framework RRO must name an `<overlayable>`
   entry, which `config_webview_packages` is not, so this cannot work there and the scripts say so.

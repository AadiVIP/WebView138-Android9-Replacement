# Integration Plan — Android 9 (API 28) Virtual Master ROM + Google WebView 138

Written 2026-11-04, extended 2026-11-06 with **Method B, the Magisk module** (§4B), which is the
current preferred route. Supersedes the framework-res patch route as the primary method.
Every claim here is either a **MEASURED** fact about a file on this machine, a **SOURCE** rule quoted
from `refs/aosp9/` (Android 9 `frameworks/base`), or an **UNTESTED** step that needs the guest.
Nothing in this document has been executed against a running Android 9 guest, and no boot claim is
made anywhere in it.

---

## 1. What is on disk right now

| File | Size | What it is | State |
|---|---|---|---|
| `output/webview138-provider-overlay.apk` | 2688 B | static RRO `com.qoder.webviewprovider.overlay` that replaces `android:xml/config_webview_packages` | BUILT, 26/26 audit checks pass, **UNSIGNED by design**, **never executed** |
| `output/webview138-provider-overlay.manifest` | 25 lines | audit output: sha256 + every `<overlay>` rule + the provider list; **only emitted when every check passed** | consumed by `tools/install_overlay.sh` to bind the on-device bytes to this audit |
| `input/webview138_arm64_universal_138.0.7204.179.apk` | 222 MB | Google WebView 138.0.7204.**179**, arm64-v8a + armeabi-v7a universal | MEASURED: `ELF64/EM_AARCH64` 130.6 MB `libwebviewchromium.so`, `minSdk=26`, standalone |
| `input/webview138.apk` | 91 MB | Google WebView 138.0.7204.**181**, **armeabi-v7a only** | MEASURED: unusable on this guest (`manifest.json "support_a32": false`) |
| `work/V2_cert.der` | 959 B | the X.509 that signs **both** WebView APKs, byte-identical to what the overlay embeds | MEASURED, SHA-1 `1F387CB25E0069EFCA490ADE28C060E09D37DD45` |
| `output/WebView138-Replacement-Magisk.zip` | 18181 B / sha256 `b6323730c2fe56894477d2cf854c18c8e1732f4befa04c05ed3572bc89797955` | Method B: the module that delivers the overlay above systemlessly (§4B) | BUILT, deterministic, 83/83 structural+script audit, 54/54 sandbox lifecycle tests, **never run on a Magisk device** |
| `tools/magisk_deploy.sh` | 265 lines | the drop-in installer/verifier/rollback for that module — the route that was actually tested end to end | same test suite |
| `input/rom_9_0_0_1059_3281.zip` | 391 MB | the ROM. `rom.img`/`rom1.img`/`play.zip` are all `?e=x&c=v2` containers | MEASURED: not ext4, no magic, not decryptable here |

Full Base64 of the certificate the overlay declares (a fingerprint is not a substitute for it), from
`tools/verify_overlay.py` — this is the exact 1280-character string stored as `<signature>` TEXT:

```
MIIDuzCCAqOgAwIBAgIJANi6DgBQG4ZTMA0GCSqGSIb3DQEBBQUAMHQxCzAJBgNVBAYTAlVTMRMwEQYDVQQIDApDYWxpZm9ybmlh
MRYwFAYDVQQHDA1Nb3VudGFpbiBWaWV3MRQwEgYDVQQKDAtHb29nbGUgSW5jLjEQMA4GA1UECwwHQW5kcm9pZDEQMA4GA1UEAwwH
d2VidmlldzAeFw0xNDA4MDgyMzIwMjBaFw00MTEyMjQyMzIwMjBaMHQxCzAJBgNVBAYTAlVTMRMwEQYDVQQIDApDYWxpZm9ybmlh
MRYwFAYDVQQHDA1Nb3VudGFpbiBWaWV3MRQwEgYDVQQKDAtHb29nbGUgSW5jLjEQMA4GA1UECwwHQW5kcm9pZDEQMA4GA1UEAwwH
d2VidmlldzCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAMbtaFX0r5aZJMAbPVMAgK1ZZ29dTn91VsGxXv2hqrQo7Ipq
Ey2JmPvPnoMsSiuTAe+UcQy8oKDQ2aYVSAd1DGIy+nSRyFTt3LSIAdwSBkB1qT4a+OqkpsR6bSNXQXQ18lCQu9gREY3h3QlYBQAy
zRxw4hRGlrXAzuSz1Ec4W+6x4nLG5DG61MAMR8ClF9XSqbmGB3kyZ70A0X9OPYYxiMWP1ExaYvpaVqjyZZcrPwr+vtW8oCuGBUtH
pBUH3OoG+9s2YMcgLG7vCK9awKDqlPcJSpIAAj6uGs4gORmkqxZRMskLSTWbhP4p+3Ap8jYzTVB6Y1/DMVmYTWRMcPW0macCAwEA
AaNQME4wHQYDVR0OBBYEFJ6bAR6/QVm4w9LRSGQiaR5Rhp3TMB8GA1UdIwQYMBaAFJ6bAR6/QVm4w9LRSGQiaR5Rhp3TMAwGA1Ud
EwQFMAMBAf8wDQYJKoZIhvcNAQEFBQADggEBAEQu8QiVxax7/diEiJrgKE1LwdXsIygJK/KnaKdnYEkAQpeu/QmrLiycm+OFbL1q
HJIB7OuI/PQBUtcaNSiJSCVgtwtEbZWWIdsynqG/Nf4aGOndXegSQNRH54M05sRHLoeRycPrY7xQlEwGikNFR76+5UdwFBQI3Gn2
2g6puJnVukQm/wXQ+ajoiS4QclrNlixoDQsZ4STLH4+Wju2wIWKFFArIhVEIlbamq+p6BghuzH3aIz/Fy0YTQKi7SA+0fuNeCaql
Sm5pYSt6p5CH89y1Fr+wFc5r3iLRnUwRcy08ESC7bZJnxV3d/YQ5valTxBbzku/dQbXVj/xg69H8l8M=
```

## 2. Rebuild and re-audit (the exact scripts)

```sh
cd /data/data/com.termux/files/home/webview138
python3 tools/selftest_axml.py                     # 171 checks, must be 0 failures
python3 tools/build_overlay.py \
    --out output/webview138-provider-overlay.apk \
    --cert work/V2_cert.der \
    --base-xml work/guest_config_webview_packages.axml  # the guest's VERIFIED config (§6 item 1), compiled to AXML by tools/xml_to_axml.py
python3 tools/verify_overlay.py output/webview138-provider-overlay.apk \
    --cert work/V2_cert.der --package com.qoder.webviewprovider.overlay \
    --base-xml work/guest_config_webview_packages.xml \
    --apk input/webview138_arm64_universal_138.0.7204.179.apk \
    --write-manifest output/webview138-provider-overlay.manifest
```

`--write-manifest` is written **only if every check passed** (verified: a deliberately wrong
`--package` produced `1 failures` and the manifest was refused). That manifest is what the on-device
installer checks against, so a file on the guest cannot silently drift from the file that was audited.

`--base-xml` matters: **an RRO replaces the resource, it does not merge into it.** Without it the
overlay ships the list `[com.google.android.webview, com.android.webview]`, and any *other* provider
the guest's own file lists (e.g. a Chrome entry) is removed from the candidate set. `build_overlay.py`
refuses to build if that base list already names `com.google.android.webview`.

The module is assembled from the *already audited* overlay bytes, never re-generated, and its builder
refuses to run unless the manifest is the one `verify_overlay.py` wrote:

```sh
python3 tools/build_magisk.py                    # needs output/webview138-provider-overlay.manifest
python3 tools/audit_magisk.py --report work/magisk_audit.txt     # 83 checks, independent re-read of the ZIP
python3 tools/selftest_magisk.py --report work/magisk_selftest.txt  # 54 checks, sandbox lifecycle + host integrity
```

Two tools, not one, on purpose: `build_overlay.py` asserts with the builder's own assumptions, and
`verify_overlay.py` re-reads the finished bytes with a separate parser. That split found a real defect
(this session): the from-scratch path emitted the certificate as bare CDATA under `<webviewprovider>`
instead of inside `<signature>`; `text_values()` could not see the difference so the build "passed",
while Android 9 would have read **zero** signatures and fallen back to
`applicationInfo.isSystemApp()` (`WebViewUpdater.java:506-521`), which a `/data` install fails. Both
tools now share one depth-aware reader, `AXML.webview_providers()`, and `selftest_axml.py` T8 pins the
shape against the real framework resource.

## 3. Prerequisite probe — `tools/guest_probe.sh`

The overlay only works from a **system partition**, and Android 9 scans exactly two candidate
directories: `/vendor/overlay` (`PackageManagerService.java:578`) and `/product/overlay` (`:580`), read
at `:2609` and `:2616` with `PARSE_IS_SYSTEM_DIR | SCAN_AS_SYSTEM`. `/system/overlay` and
`/oem/overlay` are **not** scanned. So the whole plan hinges on one question: *can a 2.7 KB file be
placed in one of those two directories?*

`tools/guest_probe.sh` answers that and eight related questions in one read-only run.

```sh
# put the script on the guest (MiXplorer copy), then from any shell in the guest:
sh /sdcard/Download/guest_probe.sh                > /sdcard/Download/probe.txt 2>&1
sh /sdcard/Download/guest_probe.sh --test-write   # adds ONE create+delete dot-file per scanned dir
sh /sdcard/Download/guest_probe.sh --extract      # also writes 2 files, under /sdcard/Download only
```

| Flag | What it does | Why it is separate |
|---|---|---|
| *(none)* | reads only: props, dir listings, `/proc/mounts`, `pm`, `dumpsys`, file sizes/checksums | a read-only run **cannot** prove writability, so it does not pretend to |
| `--test-write` | `echo probe > /vendor/overlay/.qoder-write-probe.tmp`, `sync`, then `rm -f` | the only honest answer to "is it writable"; SELinux can still refuse what DAC allows, which is why the mount flags and labels are reported too |
| `--extract` | saves `dumpsys webviewupdate` as the before-baseline and pulls `res/xml/config_webview_packages.xml` out of `framework-res.apk` with `unzip -p` | gets §6 item 1 without MiXplorer if the guest shell has `unzip` |

The probe measures nine things, each tied to a source rule quoted in the script header: the two scanned
directories (`:578`, `:580`), whether the signature gate applies (`ro.build.type`,
`WebViewUpdater.java:507-509`), the mount state that actually contains each directory, whether the
kernel even has `overlay` in `/proc/filesystems`, whether `idmap` exists (`:832-834`), whether
`/data/resource-cache` is populated (the direct proof that idmap assignment works on that image), the
live `dumpsys webviewupdate` provider list, the factory package's state, and the sizes/checksums of the
files to extract.

**Dry-run evidence.** The script was executed read-only on this host phone — also Android 9 / API 28,
also `/vendor/overlay` — and it worked. Measured host output: `/vendor/overlay` present with **9 APKs at
the top level and 15 overlay packages registered** (`android.overlay.common`,
`com.android.carrierconfig.overlay.common`, …), mode `drwxr-xr-x root:shell` labelled
`u:object_r:vendor_overlay_file:s0`, mounted **`ro`** from `/dev/block/dm-2`, no `overlay` line in
`/proc/filesystems`, `PROBE_BUILD_TYPE=user`, `PROBE_ABILIST32=armeabi-v7a,armeabi`. Those numbers
describe the **host**, not the guest — the point is that the script produces correct output on a real
Android 9 image, and that the mechanism it looks for demonstrably exists in Android 9 builds of this
vintage. Two real defects were found and fixed this way: toybox `awk` rejected the original mount
resolver (`awk: illegal jump type 339`), so it is now a pure-`case` longest-prefix loop, and `idmap`
must be reported as "present but this uid cannot stat it" rather than "absent".

Also measured with `--extract`: `unzip -p /system/framework/framework-res.apk
res/xml/config_webview_packages.xml` on a real Android 9 toybox produced a **5348-byte** file
byte-identical to the one already used as the stand-in base for the builder tests. So §6 item 1 can be
obtained without MiXplorer if the guest has a shell.

**If `/vendor/overlay` cannot be written, this plan stops.** Say so rather than improvising: the
alternatives are the direct framework-res edit (§5) or a repacked ROM (§8).

## 4. Method A — `tools/install_overlay.sh`, then the APK, then a manual reboot

Two files end up somewhere: the 2.7 KB overlay (the only thing that needs a system partition) and the
222 MB WebView APK (a normal `/data` install). **WebView 81 is not part of this procedure at all.**

```sh
# stage these three on the guest with MiXplorer: the overlay, its manifest, the 138 APK
sh /sdcard/Download/install_overlay.sh \
     --overlay  /sdcard/Download/webview138-provider-overlay.apk \
     --manifest /sdcard/Download/webview138-provider-overlay.manifest
     # READ THIS OUTPUT — this mode writes nothing

sh /sdcard/Download/install_overlay.sh --overlay ... --manifest ... --install --i-reviewed
sh /sdcard/Download/install_overlay.sh --webview-apk /sdcard/Download/webview138_arm64_universal.apk \
     --install-apk --i-reviewed
# reboot by hand - the script never reboots
sh /sdcard/Download/install_overlay.sh --uninstall --i-reviewed      # full rollback, see §7
```

What the installer refuses to do, and why (each line was exercised; test log below):

| Guard | Reason |
|---|---|
| refuses `--target /system/...` | Android 9 never scans it (`:578`, `:580`), and `/system/app/webview/webview.apk` lives there |
| refuses if `sha256 != manifest` | the bytes on the guest must be the bytes `verify_overlay.py` audited |
| refuses if the target path exists with different bytes | it will not overwrite something it did not create |
| refuses if `overlay_package` is already a known package | duplicate-overlay behaviour is not something I can prove from source |
| refuses to delete a file whose sha256 differs from its own record | rollback cannot be turned into a destruction tool |
| refuses `--install` / `--uninstall` / `--install-apk` without `--i-reviewed` | the brief's item 8: the user reviews first |
| re-checks `targetPackage=android`, `isStatic=true`, `priority` in 0..9999, Google first, `isFallback=false`, `provider_count>=2` | `PackageParser.java:2075-2094` silently ignores an overlay that violates the first four; `isFallback` would let the platform disable 138 itself |
| never reboots, remounts, changes verified boot, runs `pm uninstall`/`pm disable`, or installs a module | standing safety rules |

The install is staged: `cat > $TARGET_DIR/.new-<name>`, `sync`, re-hash the copy, `chmod 0644`, `chown
root:root`, `restorecon`, then `mv` (atomic rename within one filesystem). Any failure removes the temp
file and prints "nothing was installed". `restorecon` matters because the probe measures the directory
as `u:object_r:vendor_overlay_file:s0`; with the wrong label installd cannot open the file, PMS logs
`Failed to generate idmap for ...` (`:839-841`) and **silently skips the overlay** — no crash, no boot
loop, no dialog. That failure mode is why §10 has to be read rather than assumed.

**Installer test log** (everything below ran on this machine in a sandbox directory, never on a system
partition; `QODER_ALLOW_TARGET=1` and `QODER_FAKE_PM=1` exist only to make those paths testable and are
never set on a device). Uninstall with no record → refused. Install → staged copy verified
`a78b7978…`, temp renamed, `installed.env` written. Re-install → `NOTHING WRITTEN: already identical`.
Append 4 bytes to the installed file, uninstall → **refused, file kept**. Restore, uninstall → removed,
record removed, directory empty. Tampered target + install → `a different file occupies the target
path`. `--target /system/app` → refused. `--target /tmp/x` → refused. `--install` without
`--i-reviewed` → refused. One extra byte in the staged APK → `sha256 MISMATCH … ABORT`. `--install-apk`
with the fake `pm`: success path staged, logged, temp removed; failure path aborts before touching
anything. Two real bugs came out of this cycle: `--uninstall` tripped its own "target path exists"
guard, and sourcing `installed.env` died on `installed_at=Wed Nov 4 …` (not a shell literal) — the
record is now parsed with `sed`, the timestamp is `date -u '+%Y-%m-%dT%H:%M:%SZ'`, and an
`installed_path` pointing into `/system` is refused before any deletion.

Why the 138 APK may stay in `/data`: the overlay declares Google's DER as `<signature>` TEXT and
`providerHasValidSignature` (`WebViewUpdater.java:506-521`) compares it against
`packageInfo.signatures[0]` — MEASURED: exactly one certificate in the v2 and v3 blocks of that APK,
identical to `work/V2_cert.der`. A system partition would only be required if the overlay declared **no**
signature, whereupon `applicationInfo.isSystemApp()` decides.

Ordering: the two installs are independent, and the selection changes at the next boot — that is when
PMS parses `/vendor/overlay` (`:2609`, `:2616`) and `WebViewUpdateService` re-evaluates. Both installs
can be done before a single reboot. Selection itself is `findPreferredWebViewPackage()`: the user choice
if it is valid, otherwise the **first** `availableByDefault` provider in **document order** that is
installed, enabled and passes the gates (`WebViewUpdater.java:261-277`, `:305-315`). The overlay puts
Google first with `availableByDefault="true"` and no `isFallback`, so with the APK installed Google 138
wins and `com.android.webview` 81 remains a candidate if 138 is ever removed.

**What to look at afterwards** (verification, not expectation):

```sh
adb shell dumpsys webviewupdate          # "Current WebView package (name, version)"
adb shell dumpsys package com.google.android.webview | head -30
adb logcat -d | grep -iE "idmap|WebViewUpdate|SystemImpl|webview"
```

Expected on success: `Current WebView package = (com.google.android.webview, 138.0.7204.179)`.
Expected on overlay-never-loaded: `Failed to generate idmap for …` at boot, and the current package
stays `com.android.webview 81.0.4044.117`. Expected on parse failure of our XML: an
`AndroidRuntimeException` from `SystemImpl` and `system_server` restarts — the four rules that cause
that are asserted at build time, but this is the failure mode to watch for, and it is why a test
guest (not the production one) should take this file first.

**No version claim is being made about `.179` vs `.181`.** The user asked for 138.0.7204.181; the
arm64 artefact available is 138.0.7204.179 (same M138 stable branch, one build older). Both carry the
identical Google certificate, so the overlay is correct for either. If `.181` arm64 turns up, drop it
in at step 3 with no other change.

## 4B. Method B — the Magisk module (preferred; `output/WebView138-Replacement-Magisk.zip`)

Built 2026-11-06 in response to "Option A — Magisk module (preferred)". It is the same mechanism as
Method A — one static RRO that replaces `android:xml/config_webview_packages` — but it stops depending
on `/vendor/overlay` being writable, which was Method A's open blocker **B6** (the host measurement is
`/vendor` mounted `ro`, and `/proc/filesystems` on this build has no `overlayfs`, so a plain
`mount -o remount,rw` or an overlayfs trick is not available). Magisk's *magic mount* binds module
files into `/vendor` during `post-fs-data`, which init runs **before** `zygote-start` and therefore
before `system_server`/`PackageManagerService` scans `/vendor/overlay` (`PackageManagerService.java:578`,
scanned at `:2609`). That ordering is the whole reason the module works and is also why a
`service.sh`-time mount would have been exactly one boot too late.

### 4B.1 What is in the archive

| Entry | Mode | Purpose |
|---|---|---|
| `webview138-replacement/module.prop` | 644 | `id=webview138-replacement`, name/version/author/description/update |
| `webview138-replacement/customize.sh` | 755 | installer-time gates: API must be 28, sha256 must equal the audit manifest, provider logic re-read, then relocates the payload to whichever of `/vendor/overlay` or `/product/overlay` exists (Android 9 scans only those two) |
| `webview138-replacement/service.sh` | 755 | after boot: reads reality (`ls` of the scanned dir, `pm`, `dumpsys webviewupdate`), writes `boot-verify.log`, and fixes **one** setting if and only if it is stale (§4B.4) |
| `webview138-replacement/uninstall.sh` | 755 | restores `webview_provider` from the backup taken before the first `settings put`; deletes only its own files |
| `webview138-replacement/webview138.manifest` | 644 | the audit manifest, copied verbatim so the device can verify the bytes against the same record this machine verified |
| `webview138-replacement/webview138-apk.prop` | 644 | measured facts about the 138 package (package, versionName/Code, minSdk/maxSdk/targetSdk, ABIs, sha256, bytes) read out of the real APK by the shared AXML parser |
| `webview138-replacement/system/vendor/overlay/webview138-provider-overlay.apk` | 644 | the payload — byte-identical (STORED) to `output/webview138-provider-overlay.apk`, sha256 `a78b7978…53364a` |
| `webview138-replacement/README.md` | 644 | on-device copy of the method, the verification commands and the honest "not verified" list |
| `META-INF/com/google/android/update-binary` | 755 | ZIP installer shim (see §4B.3 — this is a re-implementation, not Magisk's) |
| `META-INF/com/google/android/updater-script` | 644 | `#MAGISK` |

There is deliberately **no `post-fs-data.sh`**: the only thing the module needs at `post-fs-data` time
is the magic mount, and Magisk performs that itself from the `system/` tree. Adding a script there
would be an unexercised code path pretending to be a mechanism.

### 4B.2 Option A's seven requirements, answered literally

1. **Systemlessly replace/mask WebView 81** — *partially, deliberately.* The module does not mask,
   remove or disable 81; it changes the *provider list* so Google 138 is entry #1 with
   `availableByDefault=true`, and Android 9's `findPreferredWebViewPackage()`
   (`WebViewUpdater.java:306-316`) then selects it. 81 stays installed and enabled, which is exactly
   what "Do not remove WebView 81 until WebView 138 is verified as valid and selectable" asks for, and
   it is what makes rollback a reboot instead of a reinstall.
2. **Install 138 in the correct system location** — *not done by the module itself, and stated as a
   deviation rather than hidden.* A module **can** carry `/system/app/…`, but that means (a) shipping
   222 MB inside a module directory, (b) relying on magic mount to *create* a brand-new system
   subdirectory — a case whose SELinux-label behaviour is part of Magisk, is not documented on the
   machine that built this, and cannot be fetched here (offline rule). The tested-and-shipped answer is
   the location Android 9 provably accepts on this build (`/data`, as
   `com.google.android.webview`), reached by one command the README prints, or by the module itself if
   and only if you create the opt-in flag: `touch /data/adb/modules/webview138-replacement/auto-install`.
   That branch re-verifies the APK's sha256 against `webview138-apk.prop` before invoking `pm install -r`
   and refuses on any mismatch (`selftest_magisk.py` B9–B13 prove all five behaviours).
3. **Register it as the default provider** — yes: the overlay is the registration (`config_webview_packages`
   *is* the registration list on API 28), plus `service.sh` clearing a stale `webview_provider`.
4. **Preserve native libs, metadata, permissions, SELinux contexts** — the module never repacks the
   WebView APK, so `.so`s, manifest, permissions and signing stay as Google shipped them; the payload
   is copied with `cp -a`, installed STORED so no recompression occurs, and `magisk_deploy.sh` prints
   `ls -Z` for the written files and for a neighbouring real module so the **measured** context is
   visible instead of assumed. No `restorecon`/`chcon` is issued: guessing a label policy is not a fix.
5. **Handle provider signature requirements correctly** — the overlay declares Google's certificate as
   `<signature>` TEXT (full Base64 in §1 above, SHA-1 `1F387CB2…37DD45` as a cross-check only), because
   a `/data` install is not `isSystemApp()` and `providerHasValidSignature` (`WebViewUpdater.java:506-521`)
   would otherwise reject it. `build_magisk.py` refuses to build if that string is not single-line
   canonical Base64, and `audit_magisk.py` re-derives it from the finished bytes.
6. **Survive VM reboot** — the module directory is persistent state and the RRO is re-scanned every
   boot; `boot-verify.log` (rotated to `.old`) records what each boot actually selected, so survival is
   *evidenced* rather than asserted. Nothing in the module re-applies itself at runtime.
7. **Reliable uninstall/rollback** — `uninstall.sh` restores the one setting it may have changed;
   `magisk_deploy.sh --remove` verifies `module.prop id` before deleting and refuses to touch anything
   else; WebView 81 was never modified, so after removal + reboot the factory
   `com.android.webview` provider is authoritative again.

### 4B.3 Install — the drop-in route is the one that was tested

```sh
# stage on the guest with MiXplorer: the ZIP and tools/magisk_deploy.sh
su -c 'sh /sdcard/Download/magisk_deploy.sh --check'      # reads everything, writes nothing
su -c 'sh /sdcard/Download/magisk_deploy.sh --install \
          --src /sdcard/Download/webview138-replacement --i-reviewed'
su -c reboot                                              # you decide when; the script never reboots
su -c 'cat /data/adb/modules/webview138-replacement/boot-verify.log'
su -c 'dumpsys webviewupdate | head -20'                  # expect (com.google.android.webview, 138.0.7204.179)
su -c 'sh /sdcard/Download/magisk_deploy.sh --remove --i-reviewed'   # rollback, then reboot
```

Why a helper script sits next to the ZIP at all: a module ZIP is installed by
`META-INF/com/google/android/update-binary`, whose contract belongs to Magisk. Magisk's own template
and `util_functions.sh` are not on this machine and the offline rule forbids fetching them, so the
shipped `update-binary` is a **labelled re-implementation whose compatibility with an unknown Magisk
build cannot be claimed**. `/data/adb/modules/<id>/module.prop` + files is the interface Magisk itself
consumes at boot, is what the drop-in writes, and is what the 54-check sandbox matrix exercises. Flashing
the ZIP in a Magisk app is the convenience path; `update-binary` refuses to invent `/data/adb/modules`
if it is absent, and on failure prints the drop-in commands instead of half-installing.

### 4B.4 The one piece of persisted state that can overrule the module

`Settings.Global.WEBVIEW_PROVIDER` (key string `"webview_provider"`, AOSP 9 `Settings.java:9425`; read
by `WebViewUpdater.java:287-301` **before** document order). If somebody pinned the old provider — or a
previous experiment did — the overlay is correct and still ignored. `service.sh` therefore:

- reads the value; if it already names `com.google.android.webview`, does nothing;
- if it names something else, backs it up to `$MODPATH/pref-backup` **before** writing, then
  `settings put global webview_provider com.google.android.webview` and verifies by reading back;
- never runs if the 138 package is absent (no point pinning an invalid provider);
- never writes any other key — `webview_fallback_logic_enabled` is deliberately out of scope (the
  overlay's `isFallback=false` is the correct fix, and disabling the fallback feature system-wide would
  be a broader change than replacing a provider);
- opts out entirely with `touch /data/adb/modules/webview138-replacement/no-pin`.

### 4B.5 What this module has **not** been shown to do

No Magisk device — guest or host — has ever run any part of this. Specifically unverified: (i) that the
guest has Magisk at all (**unobservable from an unprivileged shell**: `/data` is `0771` + SELinux, so
`/data/adb` and `/data/adb/never-created` both answer EACCES — `guest_probe.sh` §9 now classifies this
as PRESENT / ABSENT / NOINFO from `stat`'s errno instead of guessing from `[ -d ]`, and reports
`PROBE_MAGISK_DATA_ADB=NOINFO` on this machine); (ii) the `update-binary` ↔ Magisk ABI (§4B.3); (iii) magic mount's handling of a *new*
`system/vendor/overlay/` directory and of a 222 MB new system app; (iv) that `idmap` succeeds for this
RRO on the guest — Android 9 logs the failure at `PackageManagerService.java:839-841` and silently
skips the overlay, so `boot-verify.log` and `logcat` are the evidence to look for. ~~(v) the guest's real
provider list~~ is **RESOLVED**: the guest's actual `config_webview_packages.xml` names exactly one
provider, `com.android.webview`, so the 2-entry payload (Google first, 81 second) is complete and the
rebuild against that base is byte-identical to the shipped overlay (audits 31/0).

## 5. Method C — direct `framework-res.apk` patch (fallback, needs a key)

`tools/patch_framework_res.py` remains for this route: `inspect` prints the provider list exactly as
Android 9 parses it, `patch` inserts the Google entry (certificate as `<signature>` TEXT) and rebuilds
the ZIP preserving each entry's compression, **refusing to sign**. It is *not* the primary method: it
requires (a) a readable `framework-res.apk` — the ROM's is inside the encrypted container — and (b) a
re-signature with the ROM's platform key, which is not in the package. If the guest turns out to be
built with the public AOSP test key (`work/aosp_platform_test_cert.pem`, SHA-1
`27196E386B875E76ADF700E7EA84E4C6EEE33DFA`) the route reopens; one extracted file decides it. Do not
substitute a different key: `framework-res` participates in the `android` UID and a mismatched signer
breaks every system package in that UID.

## 6. Extraction list — what I actually need from the running VM

Everything below is optional and each item has a concrete reason. The overlay builds and audits without
any of it. Do not extract anything else.

| # | Exact path in the guest | Why | What it changes |
|---|---|---|---|
| 1 | `/system/framework/framework-res.apk` → only its `res/xml/config_webview_packages.xml` | the overlay must carry the guest's **complete** provider list, not the two entries assumed here; also tells us whether the guest already lists `com.google.android.webview` (if it does, no overlay is needed at all) | feeds `build_overlay.py --base-xml`, removes risk L4c |
| 2 | `/system/build.prop` | `ro.build.type` (signature-gate bypass) and `ro.product.cpu.abilist32/64` (ABI, without ADB) | turns two UNTESTED assumptions into MEASURED facts |
| 3 | one `.apk` listing from `/vendor/overlay/` (a directory listing is enough — no need to extract the file) | proves this ROM's Android 9 image actually boots static RROs from that directory | decides whether Method A is real for this guest |
| 4 | only if #3 is empty: `/product/overlay/` listing | same question for the other scanned directory | picks the target directory |

Item 1 is the only one that can change the artefact's contents. Items 2–4 change *confidence*, not
files. I am not asking for `webview.apk` (the guest's factory 81): it would only let me measure the
version-code floor, and `138 >> 81` is already certain from the arithmetic in
`WEBVIEW_138_COMPATIBILITY.md` §4.3.

### 6.1 Doing it in MiXplorer (no shell needed)

MiXplorer can open an APK as an archive, which is what makes item 1 possible without `unzip`.

| # | Where to go in MiXplorer | Action | What to hand back |
|---|---|---|---|
| 1 | `/system/framework/framework-res.apk` | **long-press → "Open archive"** (or open it, then "View as archive") → `res/` → `xml/` → `config_webview_packages.xml` | long-press that entry → **Extract** (or Copy) into `/sdcard/Download/`; it is a few KB |
| 2 | `/system/build.prop` | copy | `/sdcard/Download/build.prop` (~5 KB) |
| 3 | `/vendor/overlay/` | just look at it | a **screenshot or typed list** of the names, and whether the folder exists at all. Do **not** copy the APKs |
| 4 | `/product/overlay/` | only if 3 is missing or empty | the names, same as 3 |

Everything lands in `/sdcard/Download/`. Bring them out of the VM with Virtual Master's own
file-share / "import from device", or by copying on the host with MiXplorer, into
`/data/data/com.termux/files/home/webview138/work/`.

**Verify on arrival — do not trust the transfer.** The probe printed the size and `sha256` of items 1
and 2 *inside* the guest (section 8), so the received copy is compared against a measured number, not a
hope:

```sh
cd /data/data/com.termux/files/home/webview138/work
mv config_webview_packages.xml guest_config_webview_packages.xml
wc -c guest_config_webview_packages.xml          # must equal the probe's number
sha256sum guest_config_webview_packages.xml      # must equal the probe's number
python3 -c "
import sys; sys.path.insert(0,'../tools')
from axml import AXML
d = AXML(open('guest_config_webview_packages.xml','rb').read())
print('root =', d.dump()[0][1])
for p in d.webview_providers(): print(p)
"
```

If that prints `root = webviewproviders` and one line per provider, the file is genuine compiled XML
from an Android 9 framework and goes straight into `build_overlay.py --base-xml`. A truncated copy, or
a plain-text (uncompiled) export, fails at `AXML(...)` instead of quietly producing a wrong overlay —
which is the whole reason for checking the hash before building.

Item 1 has been extracted and the overlay re-audited against it (byte-identical, 31/0). Had it not been
extracted, the shipped 2-entry overlay would stay valid **only if** the probe's
`dumpsys webviewupdate` baseline lists no provider besides `com.android.webview`. That baseline is why
`--extract` (or redirecting the probe output) is worth running.

## 7. Rollback

Rollback is deliberately trivial, which is a property of the RRO design: **the factory WebView is never
touched, never deleted, and never re-signed.** Nothing in this plan modifies `framework-res.apk`,
`/system/app/webview/webview.apk`, or any file in the ROM package.

```sh
# 1. remove the overlay — this is the whole rollback, and it is what the installer records and checks
sh /sdcard/Download/install_overlay.sh --uninstall --i-reviewed
#    it deletes ONLY /vendor/overlay/webview138-provider-overlay.apk, and only after the file's sha256
#    matches its own install record. Different bytes -> it refuses and touches nothing.

# 2. reboot by hand (the script never reboots)

# 3. optional, only if you also ran --install-apk: remove the /data copy of 138
pm uninstall com.google.android.webview        # or Settings ▸ Apps ▸ Google WebView ▸ Uninstall
```

`/data/resource-cache` does **not** need clearing for this rollback. An overlay that is absent from the
scan set (`:2609`, `:2616`) is never parsed, so no idmap for it is consulted; PMS regenerates the
directory's contents for the overlays that *are* present. `install_overlay.sh --purge-idmap` exists if
you want the files physically deleted, and it deletes only entries whose name contains our overlay's
basename — note honestly that **the exact naming scheme of `/data/resource-cache` was not verified from
AOSP source**, which is why the flag lists first and is off by default. I am deliberately not
recommending `rm -rf /data/resource-cache/*`: that directory holds the idmaps of every other overlay on
the image (on the host, 15 of them), and "delete a system data directory and hope it regenerates" is not
a rollback, it is a gamble.

After step 2 the effective `config_webview_packages.xml` is the ROM's own again and
`com.android.webview` 81.0.4044.117 is selected exactly as before. `input/rom_9_0_0_1059_3281.zip` is
unmodified (`-rw-rw---- everybody`, never written to), so re-importing it also restores the original
state. Every write this plan makes is to a path it created itself; no existing guest file is ever
replaced, which is why there is no `work/guest_backup/` step to document.

Deliverable E (`webview81_restore.zip`) as literally specified — a flashable restore package — **cannot
be produced**, for the same reason as deliverable D below: it would have to contain a modified
`framework-res.apk` re-signed with a key that is not available, inside a container format that is not
documented. The commands above are the functional equivalent, and the only one that is honest.

## 8. Deliverable D — the patched ROM ZIP

**Not produceable here, and not attempted.** `manifest.json` declares
`"rom_uri":["rom.img?e=x&c=v2", "rom1.img?e=x&c=v2"]` — `e=x` encrypted, cipher `v2`. MEASURED: all
three payload files begin with the same 8-byte container magic `12 00 84 96 46 6a 69 47` and contain
no ext4 superblock signature at 0x438, no sparse header, and no recognisable plaintext. There is no
key, no format documentation, and no unpacking tool on this machine; fabricating a ZIP that merely
*looks* like the original would produce a package that fails to import or, worse, imports and boots a
half-written image. Per the project rule "Do not claim the ROM is flashable if you have only modified
an extracted directory" — and because not even an extracted directory is reachable — the substitute
deliverable is `output/webview138-provider-overlay.apk` plus this plan.

## 9. Probe result matrix — what each answer means before you install

| Probe answer | If YES | If NO |
|---|---|---|
| `PROBE_SCANNED_DIRS_EXIST vendor_overlay=1` | target exists, go on | the dir may be created only if the partition is `rw`; `mkdir` failure in the installer **is** that answer |
| `PROBE_DAC_WRITABLE vendor_overlay=yes` **and** section 3 shows `rw` | Method A works | section 3 says `READ-ONLY` → stop; §5 (needs the platform key) or §8 (needs the container) are the only routes, and both are blocked here |
| `PROBE_MEASURED_WRITE` shows `WRITABLE (created the probe file)` / `removed again: yes` | confirmed by measurement | `NOT WRITABLE: Read-only file system` → same conclusion, but now it is measured rather than inferred from mount flags |
| `PROBE_OVERLAY_PKGS` > 0 with `.apk` files in the dir | static RROs demonstrably run on this image | 0 overlays *and* an empty dir = the mechanism is untested on this image; the installer's `Failed to generate idmap` warning becomes the thing to look for after the first boot |
| `PROBE_IDMAP_BINARY=present` | required, nothing works without it | `absent` → **stop**: PMS cannot map the overlay at all |
| `PROBE_RESOURCE_CACHE=readable` with `.idmap` files | the idmap step succeeded for existing overlays | `unreadable` is normal without root; run the probe as root if the guest offers it |
| `PROBE_BUILD_TYPE=user` | the `<signature>` TEXT is what passes the gate — this overlay carries it | `userdebug`/`eng` also fine (`systemIsDebuggable()`, `WebViewUpdater.java:507-509`) |
| `PROBE_ABILIST32=` empty | expected; the **arm64** APK is the payload | lists `armeabi-v7a` → the 91 MB `.181` v7a APK becomes usable; prefer whichever ABI the device really runs |
| `PROBE_FALLBACK_ENABLED=1` or blank | blank means `settings` was unreadable, not disabled. Google is forced `isFallback=false` in the overlay, so this cannot bite the new provider | — |
| `PROBE_CURRENT_PROVIDER=(com.android.webview, 81…)` | the baseline; after install it must read `(com.google.android.webview, 138.0.7204.179)` | if the baseline already says Google, the guest already has a working 138 and nothing here is needed |

## 10. Post-install verification — runtime evidence, not expectation

**Nothing in this document has been run against a guest yet.** These commands exist so that the claim
"WebView 138 is installed and selected" is something you *observe*, not something I assert.

### 10.1 Did PMS actually load the overlay? (needs root in the guest)

```sh
su -c 'ls -l /data/resource-cache' | grep webview138        # an idmap for our file exists
su -c 'logcat -d | grep -iE "idmap|overlay"' | head -20     # look for: Failed to generate idmap for ...
pm list packages -s | grep com.qoder.webviewprovider         # PMS registered the overlay package
```

If there is no idmap and the log says `Failed to generate idmap for`, the overlay was skipped: check the
file label (`ls -Z /vendor/overlay/`) against its neighbours, then reboot again.

**If you installed Method B (the Magisk module), three more observations come first** — they answer
"did the module load at all" and "did magic mount deliver the file", which §10.1 cannot distinguish
from "the overlay was skipped":

```sh
su -c 'ls -Z /vendor/overlay/'            # our apk is listed AND /vendor is still ro -> magic mount worked
su -c 'grep -c . /data/adb/modules/webview138-replacement/boot-verify.log'   # service.sh ran this boot
su -c 'cat /data/adb/modules/webview138-replacement/boot-verify.log'
su -c 'ls /data/adb/modules/webview138-replacement | grep -E "^(disabled|remove)$"'  # empty = module enabled
```

`boot-verify.log` prints `OVERLAY MOUNTED` / `OVERLAY NOT MOUNTED` from its own `ls` of the scanned
directories, `PACKAGE INSTALLED: … versionName=…` read from `dumpsys package` rather than assumed, the
`dumpsys webviewupdate` lines of §10.2, and what it did (or deliberately did not do) about
`webview_provider`. It is rotated to `boot-verify.log.old`, so one reboot of history is always
available. `magisk_deploy.sh --check` re-prints the same state plus the sha256 of what is installed.

### 10.2 Does the framework see Google as a provider? (the decisive one)

```sh
su -c dumpsys webviewupdate          # non-root gets "Permission Denial: ... android.permission.DUMP"
```

Read three things in it, in this order:

1. `Current WebView package (name, version): (com.google.android.webview, 138.0.7204.179)`
   (`WebViewUpdater.java:529`). This is the selection result.
2. The `WebView packages:` block (`:557-590`) — this list **is** the overlaid resource as the framework
   parsed it. Diff it against the `webviewupdate-before.txt` baseline from the probe:
   * `Valid package com.google.android.webview (versionName: 138.0.7204.179, ...) is installed/enabled
     for all users` → the overlay took effect **and** the signature gate passed.
   * `Invalid package com.google.android.webview (...), reason: <text>` → the entry is present (so the
     overlay worked) but a gate rejected it; the reason string tells which one.
   * Google missing from the list entirely, while §10.1 showed an idmap → the overlay parsed but the
     file replaced a resource the framework did not re-read; reboot.
3. `Minimum WebView version code: <n>` (`:533`) — the version floor derived from the factory package.
   MEASURED for the 138 APK: versionCode **720417901** (`reports/WEBVIEW_138_COMPATIBILITY.md` §6).
   The guest's 81 versionCode was **not** measured (its APK was never extracted), so do not assert the
   margin from memory: read the printed minimum here and check 720417901 exceeds it. A `reason:` of
   "version too low" on the Google line would mean that floor is above 720417901, which the arithmetic
   of `138.0.7204` vs `81.0.4044` makes implausible but does not prove.

Also confirm WebView 81 is untouched, which is a requirement rather than a side effect:

```sh
su -c 'dumpsys package com.android.webview' | grep -E "versionName|enabled|flags" | head
pm path com.android.webview            # must still be /system/app/webview/webview.apk
```

### 10.3 Does an actual WebView render a page? (needs no root, and is the only end-to-end proof)

`dumpsys` proves the framework's bookkeeping. A rendered page proves the provider works. Any app that
hosts a `WebView` will do; the guest already has one — Chrome/WebView-based in-app browsers, or the ROM's
own browser. What to look for:

1. Open a page with real content (not `about:blank`), e.g. `https://example.com`, and confirm it paints.
2. Get the user agent, which names the engine version. The least-code way is a page that prints it:
   open `https://www.whatismybrowser.com/detect/what-is-my-user-agent/`, or paste this into any
   address bar that accepts `javascript:`:
   `javascript:alert(navigator.userAgent)`
   Expect `... AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/138.0.7204.179 Mobile
   Safari/537.36`. `Chrome/138.*` **is** the proof that 138's renderer is what executed.
   `Chrome/81.*` means the framework still used 81.
   (A WebView shows the *framework's* selected provider in that string, so this single check covers
   §10.2's conclusion from the application side.)
3. One capability that 81 lacks and 138 has, as a secondary discriminator: in the same page run
   `javascript:alert(window.performance.memory? 'memory API ok':'no memory API')` or check
   `CSS.supports('selector(:is(p))')` — `:is()` is unsupported in 81 and supported in 138. Report the
   observed value, do not infer it.

### 10.4 What to send back

`probe.txt` (and `--extract` output), the two `dumpsys webviewupdate` captures (before/after), the `ls
-Z /vendor/overlay/` line, the `logcat` idmap lines, and a photo/screenshot of the user-agent string
from §10.3. Until those arrive, the status of this integration is **"prepared, audited off-device,
unverified at runtime"** — which is what `VALIDATION_REPORT.md` says now and will keep saying until
runtime evidence exists.

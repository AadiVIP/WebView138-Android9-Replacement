# WebView 138 replacement Magisk module (v1.0)

Registers the Google-signed **WebView 138.0.7204.179 (arm64)** as the default WebView provider of an
**Android 9 (API 28)** system, without editing or re-signing a single signed partition file, and
without deleting the factory WebView.

## What is in here

| file | purpose |
|---|---|
| `module.prop` | module identity (`id=webview138-replacement`) |
| `system/vendor/overlay/webview138-provider-overlay.apk` | **the whole mechanism** - a 2.7 KB static RRO, byte-for-byte the file `tools/verify_overlay.py` audited (sha256 `a78b79788a6cf57a6cdefc1e2d69c9ae7466c88ff6938974d11c2aefce53364a`, 2688 bytes) |
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
   modify that file - it overlays it. `2` providers are declared, `com.google.android.webview`
   **first**, `availableByDefault=true`, `isFallback=false`; every other provider from the base list is
   carried verbatim, so nothing is ever left without a WebView.
   Selection is document order: `WebViewUpdater.java:306-316` returns the first
   `availableByDefault` provider that is installed, enabled and valid.
2. **The signature gate.** A provider installed into `/data` is not a system app, so
   `WebViewUpdater.providerHasValidSignature` (`:506-521`) needs an explicit `<signature>` child
   whose base64 text is the real Google certificate (that is what Android 9 reads - the
   `signature=` *attribute* is never consulted by this version). 1280 characters,
   certificate sha256 `6faf3c4140407473400934d117815a21af1cfefc5c0bee61c858bc3d72ba6fe5`, extracted from the APK Signing Block of the 138 package
   itself, not typed in and not a fingerprint.

The overlay is scanned at boot only from `/vendor/overlay` or `/product/overlay`
(`PackageManagerService.java:578,580`, scanned at `:2609,:2616` with `SCAN_AS_SYSTEM`;
`/system/overlay` is **not** scanned on this version). Those partitions are mounted `ro` in a
Virtual Master guest, which is exactly the problem Magisk solves: magic mount binds the module file
into the directory during `post-fs-data`, **before** `system_server`/`PackageManagerService` starts,
so `idmap` runs and the RRO applies at normal boot. No root remount, no partition write.

## What this module deliberately does NOT do

* **It does not bundle the 138 package.** The APK is 222218902 bytes
  (`input/webview138_arm64_universal_138.0.7204.179.apk`, sha256 `39f8eee7b6a4588c55e9299f95bfdff0c0943414bf468241becd0ed588e444a0`, native libs for arm64-v8a,armeabi-v7a). Putting it inside the module would mean
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
| package | `com.google.android.webview` | must equal `provider_1_packageName` in the overlay, or the list names something that is not there |
| versionName / versionCode | `138.0.7204.179` / `720417901` | `Minimum WebView version code` gate, computed from the factory package |
| minSdkVersion | 26 | 26 ≤ 28 ✓ |
| **maxSdkVersion** | **28** | **exactly the Android 8.0-9.0 branch - this is why 138 can be installed on API 28 at all** |
| targetSdkVersion | 35 | `UserPackage.hasCorrectTargetSdkVersion` requires >= 28 ✓ |
| native libs | arm64-v8a,armeabi-v7a | the guest's `ro.product.cpu.abilist64` must contain arm64-v8a |
| size / sha256 | 222218902 B / `39f8eee7b6a4588c55e9299f95bfdff0c0943414bf468241becd0ed588e444a0` | what `service.sh` verifies before any opt-in install |

The module does **not** contain the 222218902-byte package. Installing it is one command:

    su -c 'pm install -r /data/local/tmp/webview138.apk'      # you watch it happen

or, if you would rather the module did it: `touch /data/adb/modules/webview138-replacement/auto-install` (optionally
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
    su -c cat /data/adb/modules/webview138-replacement/boot-verify.log

Expect: `Current WebView package (name, version): (com.google.android.webview, 138.0.7204.179)`;
`WebView packages:` lists `Valid package com.google.android.webview ...` **first**; the overlay file
visible under `/vendor/overlay` or `/product/overlay`; one `.idmap` for it under
`/data/resource-cache`; no `Failed to generate idmap for` line in the log. The final proof is a real
page in a WebView app plus `navigator.userAgent` containing `Chrome/138.0.7204.179`.

## Rollback

    magisk --remove-module webview138-replacement        (or the Magisk app's Remove button)
    # or: su -c 'sh /data/local/tmp/magisk_deploy.sh --remove --i-reviewed'
    su -c reboot

`uninstall.sh` restores `Settings.Global.webview_provider` if `service.sh` pinned it. The RRO and its
idmap effect disappear with the module directory, so the factory list inside `framework-res.apk` is
authoritative again and **WebView 81 is selected**. 138 remains installed but unused; remove it with
`pm uninstall com.google.android.webview` if you want the original state exactly.

## Why `service.sh` is here at all

`Settings.Global.WEBVIEW_PROVIDER` (`Settings.java:9425`, android-9.0.0_r35) is checked *before*
document order (`WebViewUpdater.java:287-301`). Its own documentation says: *"if unset the provider
is instead determined by the system"*. If anyone ever picked `com.android.webview` in Developer
options, that stale value would overrule the overlay and the module would look broken. `service.sh`
fixes only that case: it saves the old value to `pref-backup`, pins `com.google.android.webview`, re-reads to confirm,
and `uninstall.sh` restores it. Create the empty file `no-pin` in the module directory to disable
even that. Everything else the script does is read-only diagnostics into `boot-verify.log`.

## What is and is not verified

Verified on the build machine: the overlay bytes pass 2+ structure/signature/provider
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

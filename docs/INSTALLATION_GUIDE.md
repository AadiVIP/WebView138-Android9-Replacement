# Installation Guide — WebView 138 Magisk module (Option A)

Companion to `output/WebView138-Replacement-Magisk.zip` (sha256
`b6323730c2fe56894477d2cf854c18c8e1732f4befa04c05ed3572bc89797955`, 18181 B).
This is the **operational** how-to for the Virtual Master Android 9 guest. Every step is written
for the environment you actually have: **no working ADB**, root inside the guest (Magisk is reported
as v30 — §1 below verifies that instead of assuming it), and **MiXplorer** to move files.

Nothing here flashes a partition. The module is installed into `/data/adb/modules/` and the WebView
APK is a normal `pm install`. Read the end-of-§4 "what can actually go wrong" before you start.

Files that must reach the guest (stage them wherever MiXplorer can see and root can read —
`/sdcard/Download/` is used below):

| Local file (this project) | Staged as | Why it is needed |
|---|---|---|
| `tools/guest_probe.sh` | `guest_probe.sh` | read-only prerequisite probe — run this FIRST |
| `output/WebView138-Replacement-Magisk.zip` | `WebView138-Replacement-Magisk.zip` | the module (drop-in route below, or flash) |
| `tools/magisk_deploy.sh` | `magisk_deploy.sh` | the drop-in installer/verifier/rollback — the tested route |
| `input/webview138_arm64_universal_138.0.7204.179.apk` | `webview138.apk` | the 222 MB Google-signed package the module registers |

Do **not** stage `input/webview138.apk` (the `.181`): it is armeabi-v7a-only and the guest is ARM64.

---

## 1. Before installing anything — prove the environment (read-only)

Push `guest_probe.sh` into the guest and run it. It writes nothing.

```sh
# inside the guest, root shell (Magisk app → Terminal, or su from MiXplorer's root)
sh /sdcard/Download/guest_probe.sh 2>&1 | tee /sdcard/Download/probe.txt
```

Read the verdict lines at the bottom. You need **all four** of these before continuing:

```
PROBE_MAGISK_DATA_ADB = PRESENT        # a NOINFO here means you are not root — re-run under su
PROBE_MAGISK_MODULES_DIR = PRESENT     # /data/adb/modules exists -> Magisk is really installed
PROBE_MAGISK_VERSION  = Magisk v<..>   # non-empty
PROBE_CURRENT_PROVIDER = com.android.webview   # the 81 you are replacing, currently active
```

The rest of the guide assumes `PROBE_MAGISK_DATA_ADB=PRESENT`. If the probe says `NOINFO`, you were
not root when it ran — `su` and re-run; it is not evidence Magisk is missing. If it says `ABSENT`
from a root shell, Magisk is not installed in this guest and Option A cannot work here — stop and
tell me; do not try to install Magisk as a side effect of this.

The probe also prints `PROBE_SCANNED_DIRS_EXIST vendor_overlay=… product_overlay=…`. Exactly one of
`/vendor/overlay` or `/product/overlay` must exist — that is where Android 9 scans for the RRO, and
the module places its payload in whichever one is present.

## 2. Install the module (drop-in route — the one that was actually tested end to end)

First **unzip** the module. In the guest:

```sh
cd /sdcard/Download
unzip -o WebView138-Replacement-Magisk.zip -d mod        # -> /sdcard/Download/mod/webview138-replacement
ls /sdcard/Download/mod/webview138-replacement           # expect module.prop, customize.sh, service.sh, ...
```

Dry run — verifies the source tree byte-for-byte against its audit manifest and reports the target,
writing nothing:

```sh
su -c 'sh /sdcard/Download/magisk_deploy.sh --check \
          --src /sdcard/Download/mod/webview138-replacement'
```

If that prints the payload sha as *matching the audit manifest* and `module_present=no`, install:

```sh
su -c 'sh /sdcard/Download/magisk_deploy.sh --install \
          --src /sdcard/Download/mod/webview138-replacement --i-reviewed'
```

What the installer does, in order, and what it **refuses** to do (each refusal is a test-proven
behaviour, not a hope):

- re-checks the payload sha256, the provider logic, and that `module.prop id == webview138-replacement`;
- refuses to write unless the API is 28;
- refuses if `/data/adb/modules` is missing (it does **not** create it);
- refuses to overwrite a directory at the target path that is not already our module;
- copies the tree to `/data/adb/modules/webview138-replacement/`, re-verifies the copy, and runs the
  module's own `customize.sh` as a child (so the flashed path and the drop-in path validate alike);
- prints the `ls -Z` SELinux context of what it wrote **and** a neighbouring real module for
  comparison — it reports the label, it does not guess one or run `restorecon`.

It then prints the remaining steps. **It never reboots the guest.**

The *flashable* route (Magisk app → Install → pick the ZIP) uses the ZIP's `update-binary`. That
binary is a re-implementation because Magisk's own template is not on the build machine and may not be
downloaded (offline rule); its compatibility with v30 specifically is **unverified** (§FINAL report).
If the flash path and the drop-in path disagree, trust the drop-in path — it is the one the 58-check
sandbox matrix exercised.

## 3. Install the 138 package (one command, you watch it)

The module does **not** bundle the 222 MB APK (see the §FINAL report for why). Registering a provider
and installing the package are two different things; the module does the first, this command does the
second:

```sh
su -c 'pm install -r /sdcard/Download/webview138.apk'      # expect: Success
su -c 'pm list packages com.google.android.webview'        # expect: package:com.google.android.webview
```

Alternative: have the module do it on next boot, only after it has re-verified the bytes. Create the
opt-in flag (optionally with an absolute path on line 1):

```sh
su -c 'echo /sdcard/Download/webview138.apk > /data/adb/modules/webview138-replacement/auto-install'
```

`service.sh` then re-checks the sha256 against the module's `webview138-apk.prop` before invoking
`pm install -r`, and refuses on any mismatch. Without the flag file it **never** installs anything.

## 4. Reboot, then verify (do not assume)

```sh
su -c reboot
```

After the guest is back up:

```sh
# 1) the module loaded and magic mount delivered the file
su -c 'ls -Z /vendor/overlay/' | grep webview138
su -c 'ls /data/adb/modules/webview138-replacement | grep -E "^(disabled|remove)$"'   # empty = enabled
su -c 'cat /data/adb/modules/webview138-replacement/boot-verify.log'

# 2) the framework sees Google as a valid provider and picked it (the decisive check)
su -c 'dumpsys webviewupdate | head -25'
#    expect a line:  Current WebView package (name, version): (com.google.android.webview, 138.0.7204.179)
#    and 138 listed under "Valid package(s)", NOT only under "Invalid package(s)"

# 3) a real page renders, and the engine is 138 not 81
#    open any web app, then (where the app exposes a JS console): alert(navigator.userAgent)
#    expect "Chrome/138.0.7204.179" ... a "Chrome/81.*" means the framework still used 81
```

`boot-verify.log` is the module's own evidence from that boot: it records whether the overlay was
mounted (it does its own `ls` of the scanned directory), what `pm`/`dumpsys package` say the installed
version is, the `dumpsys webviewupdate` lines, and exactly what it did (or deliberately did not do)
about the `webview_provider` setting. It is rotated to `boot-verify.log.old`, so the previous boot's
history is always available too.

### What can actually go wrong, and what you will see

| Symptom in `boot-verify.log` / `dumpsys` | Meaning | Fix |
|---|---|---|
| `OVERLAY NOT MOUNTED` | magic mount did not deliver the file | the module dir may not have been picked up; check §1 verdict lines, reboot again, then `--remove` + `--install` once |
| `Current WebView package` still `com.android.webview 81` | 138 present but not selected — usually the `webview_provider` pin overrode the list | the module's `service.sh` handles this on the next boot; confirm `boot-verify.log` shows it pinning, then reboot again |
| 138 under `Invalid package(s)` | WebViewUpdateService rejected it (signature / targetSdk / ABI) | `logcat -d \| grep -iE "webview"`, then tell me the line; do **not** remove 81 (it is still your fallback) |
| `REFUSED:` anywhere in the installer output | the module protected you from a bad state | read the reason it printed; nothing was changed |

## 5. Rollback

See `ROLLBACK_GUIDE.md`. The short version: because WebView 81 was never modified, rollback is
"remove the module + reboot" — 81 comes back as the active provider by itself.

## 6. The guest's provider list — already matched (no further extraction needed)

The guest's real `config_webview_packages.xml` was supplied and it lists **exactly one provider**:
`com.android.webview` (`availableByDefault="true"`, no fallback, no signature). It was compiled to AXML
(`tools/xml_to_axml.py`) and the overlay rebuilt with `--base-xml`; the result is **byte-identical** to
the shipped payload (sha256 `a78b7978…`) and audits **31/0** with the guest entry preserved verbatim.
So the shipped 2-entry overlay (Google first, `com.android.webview` second) is complete for this guest —
nothing is dropped, because the guest has no other provider to drop. Saved as
`work/guest_config_webview_packages.xml` / `.axml`; pinned by `selftest_axml.py` T9.

If the guest's provider list ever changes (a ROM update, a new provider added), re-run this to
re-matched the overlay. An RRO *replaces* the whole `config_webview_packages` resource, so a provider
the guest lists that is absent here would drop out of the candidate set; the builder preserves every
existing provider and re-orders/flags only the Google entry.

**Exact file to extract with MiXplorer (root):**

- Guest path: `/system/framework/framework-res.apk`
- Inside it, extract: `res/xml/config_webview_packages.xml`

Steps: in MiXplorer (root) open `/system/framework/framework-res.apk` (it is a ZIP) → open
`res/xml/config_webview_packages.xml` → Extract / Save to `/sdcard/Download/`. Send me that one file.
It is compiled (binary AXML), and that is exactly the format `build_overlay.py --base-xml` reads — do
not try to "beautify" it into plain XML.

Two things I can **already** see from the ROM package (no extraction needed, from
`input/rom_9_0_0_1059_3281.zip → manifest.json`): `support_a32:false`, `support_a64:true`,
`minimum_sdk_int:28`, and `magisk_uri` pointing at a Magisk plugin — so the guest is 64-bit-only and
the 32-bit ABI concern is closed (the 138 package's arm64 `libwebviewchromium.so`, verified
`ELF64/EM_AARCH64`, is the one that will load). The in-guest `abilist32`/`abilist64` (probe
`PROBE_ABILIST32`/`PROBE_ABILIST64`) are the confirmation, expected to come back 32-bit-empty.

**Not needed:** the 222 MB WebView APK (you stage it yourself, §3), the guest's `webview81` APK
(we never touch it), or the encrypted ROM containers.

## 7. Post-install verification — the runtime evidence that actually counts

Do not call this a success until **all** of these are observed (they are the handoff's acceptance tests):

1. Guest boots.
2. Magisk loaded the module — `ls /data/adb/modules/webview138-replacement` has no `disabled`/`remove`.
3. PMS recognised it — `ls -Z /vendor/overlay/ | grep webview138` shows the overlay, and
   `boot-verify.log` says `OVERLAY MOUNTED`.
4. `dumpsys webviewupdate` reports `Current WebView package (name, version):
   (com.google.android.webview, 138.0.7204.179)`, and 138 appears under **Valid package(s)**, not only
   under Invalid.
5. A real app renders a page (not `about:blank`).
6. JS runs on that page.
7. `navigator.userAgent` contains `Chrome/138.0.7204.179` (a `Chrome/81.*` means 81 is still in use).

If §4.1's table shows 138 under Invalid, the failure is in the provider-validation chain — capture
`logcat -d | grep -iE "webview"` and send it; do **not** remove 81 (it is still the working fallback).

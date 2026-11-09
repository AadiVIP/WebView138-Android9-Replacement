# Troubleshooting

Symptom → meaning → action. All commands run on the guest with `su` unless noted. The module's
`boot-verify.log` (rotated to `.old`) is the primary evidence source — read it before guessing.

## 0. Before anything: was the environment ever right?

| Check | Command | Expected |
|---|---|---|
| API is 28 | `getprop ro.build.version.sdk` | `28` — on anything else this module refuses to install and cannot work (Android 10+ framework RROs need an `<overlayable>` entry) |
| 64-bit ABI present | `getprop ro.product.cpu.abilist64` | contains `arm64-v8a` |
| Magisk present | `ls -d /data/adb/modules` as root | exists. Note: an **unprivileged** shell cannot distinguish "absent" from "not readable" (`/data` is `0771` + SELinux) — a `NOINFO` from the probe means *you were not root*, not *Magisk is missing* |
| Magisk version | `magisk` / Magisk app | user-reported v30 for this ROM; the ROM package ships a Magisk plugin (`magisk_uri`), supporting but not conclusive |
| A scanned overlay dir exists | `ls -d /vendor/overlay /product/overlay 2>/dev/null` | at least one — Android 9 scans only these two |
| Static RROs live here | `ls /vendor/overlay/` | real APKs (on the measured host: 9, with 15 overlay packages registered) |

`tools/guest_probe.sh` performs all of this read-only in one run; `--test-write` adds one
create+delete dot-file per scanned directory (the only honest writability answer).

## 1. `OVERLAY NOT MOUNTED` in boot-verify.log

Magic mount did not deliver the file to `/vendor/overlay`.

1. Is the module actually loaded? `ls /data/adb/modules/webview138-replacement | grep -E '^(disabled|remove)$'` — any output means disabled/removing; clear the marker or re-enable in the Magisk app.
2. Does the module directory still contain the payload? `ls /data/adb/modules/webview138-replacement/system/*/overlay/`.
3. Reboot once more. If it persists: `magisk_deploy.sh --remove --i-reviewed`, reboot, re-stage, `--check`, `--install --i-reviewed`, reboot.
4. Still failing → this is the unverified "magic mount of a new overlay directory" case (ARCHITECTURE §8.3). Capture `logcat -d | grep -iE 'magisk|overlay'` and the `ls -Z` of the module's payload vs a neighbouring real module's files, and report it. Do not try remounting `/vendor` rw — that is not available on this image (`/proc/filesystems` has no overlayfs; measured).

## 2. `Current WebView package` is still `com.android.webview` 81

Two causes, in order of likelihood:

- **A stale `webview_provider` pin overrode the list.** The module's `service.sh` handles exactly
  this: it backs the old value up to `pref-backup` and pins Google, then it takes effect **at the
  next boot**. Confirm the log line `PREFERENCE: was '…', backed up …, now pinned to
  com.google.android.webview.` and reboot again. Opt-out file: `no-pin` in the module dir.
- **The 138 package is not installed.** The overlay names a provider that is absent, so Android
  keeps the factory one. The log says `PACKAGE NOT INSTALLED`. Install it (INSTALLATION_GUIDE §3)
  or create the opt-in `auto-install` file; then reboot.

## 3. 138 appears under `Invalid package(s)` in `dumpsys webviewupdate`

The overlay worked (the entry is *present*) but a validity gate rejected the package. The `reason:`
text says which:

| reason (approx.) | Gate | What to check |
|---|---|---|
| version too low | versionCode floor | read the printed `Minimum WebView version code:` — the tested package is `720417901`, far above 81's `404411700`; if the floor prints above that, the guest's factory version is unexpected — capture the full dump |
| signature-related | gate 3 | the installed package must carry exactly the cert the overlay declares (SHA-256 `6faf3c41…`). Verify the file with `tools/download_webview_apk.sh` — a re-signed or different build will fail here |
| otherwise | targetSdk / library | the tested APK has `targetSdk 35` and the `WebViewLibrary` meta-data; anything else means a different file was installed |

**Do not remove WebView 81** — it is still your working fallback while you diagnose. Capture
`logcat -d | grep -iE 'webview'` and file it as a report with the dump.

## 4. Page renders but `navigator.userAgent` says `Chrome/81.*`

The framework still used 81 for rendering: selection changed only at boot, or the pin case in §2
is still pending. Re-run §2, reboot, re-check `dumpsys webviewupdate` *and* the user-agent.
`Chrome/138.0.7204.179` in the user-agent is the end-to-end proof; everything else is bookkeeping.

## 5. `REFUSED:` / `!!` from the installer or `customize.sh`

The module protected you from a bad state; **nothing was changed**. Read the printed reason:

| Message | Meaning |
|---|---|
| `module.prop id is …` | you staged the wrong tree or a foreign module — re-unzip the ZIP |
| `overlay sha256 mismatch` | the payload bytes are not the audited ones — re-transfer/re-extract the ZIP; verify against `checksums/SHA256SUMS.txt` |
| `this module is built for API 28` | wrong device — this module is API 28-only by construction |
| `neither /vendor/overlay nor /product/overlay exists` | Android 9 would scan nothing — the module refuses to invent a directory on a read-only partition |
| `provider #1 is not …` / `isFallback=true` / `only 1 provider(s)` | the manifest no longer describes a safe provider list — the archive is not the release build |
| `no sha256sum on this shell` | the guest shell lacks the tool — install a toybox/BusyBox with sha256sum or use the Magisk app terminal |
| `/data/adb/modules absent` (update-binary) | Magisk is not installed/enabled in this guest — install Magisk first; the installer deliberately does not create it |

## 6. `Failed to generate idmap for …` in logcat

`idmap` (installd) could not read/label the overlay file → the overlay is **silently skipped**
(no boot loop, no dialog). Check `ls -Z /vendor/overlay/webview138-provider-overlay.apk` against
neighbouring overlays' labels; if the context differs from the neighbours', report the measured
values (the scripts report rather than guess labels). Reboot once; if it persists, this is the
unverified SELinux-label case (ARCHITECTURE §5) — gather the `ls -Z` output and file it.

## 7. Flashing the ZIP in the Magisk app misbehaves, or reports a strange/unknown API

Expected, and by design a non-fatal path:

- The `update-binary <api> <tmpdir> <zipfile>` contract hands the script an **`api` argument
  supplied by the flasher** — in some contexts it arrives empty or as a placeholder like
  **`dummy`**, so the flashable path *cannot* verify the device's API and only warns. The
  standalone `tools/magisk_deploy.sh` **measures** `ro.build.version.sdk` and enforces API 28
  itself — that is the tested route (ARCHITECTURE §4).
- The shipped `update-binary` is a labelled re-implementation; its compatibility with the guest's
  specific Magisk build is unverified. If the flash path and the drop-in path disagree, **trust
  the drop-in path** — it writes exactly the directory Magisk consumes at boot, and the 58-check
  sandbox matrix exercised it end to end.
- The `update-binary` refuses to create `/data/adb/modules` and prints the drop-in commands on
  failure instead of half-installing.

## 8. Rollback did not seem to change anything

After `--remove` + reboot, `dumpsys webviewupdate` must read
`Current WebView package (name, version): (com.android.webview, 81.0.4044.117)` and
`ls /vendor/overlay | grep -c webview138` must be `0`. If Google is still *selected* after
removal with the 138 package still installed, that is a lingering `webview_provider` pin, not a
broken state: `settings delete global webview_provider` (or restore `pref-backup`), reboot
(ROLLBACK_GUIDE §5). 138 still appearing in the package list after removal is correct — the
package is installed but no longer declared as a provider.

## 9. The guest will not boot after installing

The module is systemless; recovery never needs filesystem surgery:

1. Disable the module at next boot (Magisk app toggle, or the `disabled` marker in the module dir)
   — with it disabled, nothing is mounted and the guest behaves as before installation.
2. Reachable root shell: `rm -rf /data/adb/modules/webview138-replacement`, reboot.
3. Only if truly nothing is reachable: mount the guest data and delete that one directory.

There is no "flash the ROM back" step — the ROM was never modified and no partition was written.

## 10. First boot after install is slow

Expected for a 57-major-revision WebView jump: OAT/VDEX for the new provider is generated on
first boot (COMPATIBILITY L6). Measure, don't fix by guessing: if slowness or a crash persists
past the first boot, capture `logcat -d | grep -iE 'webview|relro'`. Relro failure itself is
non-fatal by source ("failed to load with relro file, proceeding without").

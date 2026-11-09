# Rollback Guide — WebView 138 Magisk module

Every path back to the original state, in order from cheapest to most drastic. The important property
of this solution: **WebView 81 was never modified, disabled or removed** by anything this project did,
so rollback is not a restore — it is simply removing our one module and letting the original
`config_webview_packages.xml` become authoritative again.

What the module is the only thing that changes:

| State changed | Where it lives | What rollback does |
|---|---|---|
| The provider list | `/data/adb/modules/webview138-replacement/` + a bind mount over `/vendor/overlay/` | remove the directory → nothing to mount at next boot |
| `Settings.Global.webview_provider` | only if `service.sh` found a stale value and pinned it | `uninstall.sh` restores `pref-backup` verbatim |
| WebView 138 package | `/data` install (or `pm install`) | **not touched** by rollback — remove it yourself only if you want it gone |
| WebView 81 `com.android.webview` | `/system/app/webview/webview.apk` | **never touched by any of this** |

---

## 1. Normal rollback (module installed, guest boots normally)

```sh
# remove the module: verifies module.prop id first, runs the module's uninstall.sh, deletes ONLY our dir
su -c 'sh /sdcard/Download/magisk_deploy.sh --remove --i-reviewed'

# reboot so Magisk has no files to mount and the framework re-reads the real config
su -c reboot
```

What `--remove` will refuse to do (each proven by a sandbox test):

- refuses without `--i-reviewed` (it changes boot state, so it asks);
- refuses if `/data/adb/modules/webview138-replacement` does not exist — it will not invent a path;
- refuses if the `module.prop` id at that path is not `webview138-replacement` — it will not delete
  somebody else's module;
- after `rm -rf`, it re-checks that the path is really gone and stops with an error rather than
  claiming success over a path that survived.

After the reboot, with no overlay present:

- `/vendor/overlay` shows the real read-only partition contents again;
- the framework's own signed `config_webview_packages.xml` is authoritative again;
- the first `availableByDefault` provider from *that* file is selected — normally
  `com.android.webview` (81) as it was before you started.

Confirm:

```sh
su -c 'dumpsys webviewupdate | head -25'
#    expect:  Current WebView package (name, version): (com.android.webview, 81.0.4044.117)
su -c 'settings get global webview_provider'          # expect: (empty) or com.android.webview
su -c 'ls -l /vendor/overlay/' | grep -c webview138   # expect: 0
```

## 2. If you want WebView 138 gone as well (optional)

Rollback does not uninstall it, because a spare installed package is harmless and is useful for a
retry. To remove it:

```sh
su -c 'pm uninstall com.google.android.webview'
```

This is the **only** place any destructive command belongs, and it names the Google package explicitly
— never `pm uninstall com.android.webview`, which would take away your working fallback.

## 3. If `magisk_deploy.sh` itself is unavailable or refusing

You do not need the script to roll back; it only automates the same three steps. Manually:

```sh
# a) restore the setting the module may have pinned
su -c 'cat /data/adb/modules/webview138-replacement/pref-backup' 2>/dev/null
#    if it prints a value:   settings put global webview_provider "<that value>"
#    if it is empty/absent:  settings delete global webview_provider
#    (this module only ever writes the webview_provider key, so there is nothing else to undo)

# b) delete exactly this one directory
su -c 'rm -rf /data/adb/modules/webview138-replacement'

# c) reboot
su -c reboot
```

Step (b) is scoped to our module id on purpose. Verify before you type it that the path is what you
expect — `ls -d /data/adb/modules/webview138-replacement` — and stop if it is not.

## 4. If the guest fails to boot or WebView crashes after installing

Because the module is systemless, the recovery route never needs filesystem surgery:

1. **Boot with modules disabled.** Hold the Magisk recovery key combo / select the module in the
   Magisk app and disable it (create the `disabled` marker in the module dir, or use the Magisk app's
   per-module toggle on a boot where the UI is reachable). With the module disabled nothing is
   mounted and the guest behaves exactly as it did before installation.
2. If the Magisk app UI is reachable: Modules → WebView 138 provider → Remove, then reboot.
3. If only `adb`/root shell is reachable: `su -c 'rm -rf /data/adb/modules/webview138-replacement'`,
   reboot (this is step 3(b) above).
4. Only if none of that is reachable and the guest truly will not boot, clear Magisk's module state
   by mounting the guest's data elsewhere (MiXplorer with root is usually enough) and deleting the
   same directory.

No partition was written, no `/system` file was changed, no framework resource was re-signed — there
is no "flash the ROM back" step, because the ROM was never modified.

## 5. What is NOT a rollback failure

- `webview_provider` showing `com.google.android.webview` **after** removal, with the 138 package
  still installed: that is a lingering pin, not a broken state. Run step (a) in §3 or `settings delete
  global webview_provider` and reboot; 81 has been present and valid the whole time.
- 138 still appearing in `dumpsys webviewupdate` after removal: correct — the package is installed,
  it is just no longer *listed as a provider* by the framework, because the overlay that named it is
  gone. §2 removes it if you want.
- `boot-verify.log` absent after rollback: expected, we deleted the module directory that held it.

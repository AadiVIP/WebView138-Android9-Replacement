# ROM Inspection Report — `rom_9_0_0_1059_3281.zip`

Analysis date: 2026-11-04
Analysis host: Termux (Android, arm64, non-root, uid 10180) — **read-only with respect to all inputs**
Working root: `/data/data/com.termux/files/home/webview138/`

---

## 0. Input integrity (pristine copies)

| File | Bytes | SHA-256 |
|---|---|---|
| `/sdcard/Download/rom_9_0_0_1059_3281.zip` (original, untouched) | 391,439,957 | `953706c48432e8e79a06b68963c8463e45f100eea630ae7a7a057cb924532093` |
| `input/rom_9_0_0_1059_3281.zip` (working copy, `cp -p`) | 391,439,957 | identical (verified by `sha256sum`) |
| `input/webview138.apk` (copy of the APKMirror-named APK) | 91,400,472 | `a7de80d7b69d4b38436c6e6cc09479a2e71008083e96b9b620a9abbd9bc13d33` |

No byte of either original input has been written to. All extraction went into `work/`.
Sizes match the stated metadata (373.30 MiB / 87.16 MiB).

---

## 1. Top-level ZIP structure — this is NOT a flashable recovery ZIP

```
Archive:  rom_9_0_0_1059_3281.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
      410  2026-10-10 05:08   manifest.json
101252928  2026-10-10 05:00   play.zip
121024566  2026-10-10 05:00   rom.img
169043583  2026-10-10 04:59   rom1.img
---------                     -------
391321487                     4 files
```

Only four entries. There is **no** `META-INF/`, no `update-binary`, no `updater-script`, no
`system.img`, no `vendor.img`, no `product.img`, no `super.img`, no `boot.img`, no `vbmeta.img`,
no `payload.bin`, no `system.new.dat(.br)`, no `system.transfer.list`, no `install.sh`.

**Conclusion (Phase 1 items 1–4, 8–10):** this is a *Virtual Master VM ROM distribution package*,
not an OTA, not a recovery-flashable ZIP, and not a Google factory image. It is consumed by the
Virtual Master application, which imports the images into a guest disk. There is no recovery
installer and no scripting layer in this package, so there is no install-script surface to modify.

## 2. `manifest.json` (verbatim, 410 bytes)

```json
{
    "id":"rom_default_9.0.0",
    "display_name":"Android 9.0.0",
    "rom_version":1059,
    "os_version":9,
    "support_a32":false,
    "support_a64":true,
    "minimum_sdk_int":28,
    "minimum_app_ver":"3.2.16",
    "rom_uri":["rom.img?e=x&c=v2", "rom1.img?e=x&c=v2"],
    "magisk_uri":"asset:///plugins/magisk.zip?h=true",
    "su_uri":"",
    "xposed_uri":"",
    "play_uri":"play.zip"
}
```

Decisive fields for this project:

- **`"support_a32": false`** — the package itself declares that this guest does **not** support
  32-bit ARM. `"support_a64": true`. See §5.
- `minimum_sdk_int: 28` — API 28 = Android 9, matches the target environment.
- `rom_uri` — two image files, each with the query string `?e=x&c=v2` (a Virtual-Master-private
  container/encoding selector; `c=v2` is a container version tag). The images are referenced by
  name + parameters rather than as plain partition images.
- `magisk_uri: asset:///plugins/magisk.zip?h=true` — Magisk support is advertised, and the Magisk
  payload lives **inside the Virtual Master app APK as an asset**, not in this ZIP.
- `play_uri: play.zip` — the Google-Apps / Play payload, also an opaque container (§3).
- `su_uri` / `xposed_uri` empty.

## 3. Image container forensics — payload is encrypted, not merely compressed

All three payloads (`rom.img`, `rom1.img`, `play.zip`) were tested read-only.

**Magic bytes.** `rom.img` and `rom1.img` both begin with the identical 8-byte value
`12 00 84 96 46 6a 69 47`, then differ for 8 bytes, then share 12 more bytes
(`25 7a 38 39 47 76 69 43 4d 30 4b 6b`) before diverging again. `play.zip` shares none of this.
No filesystem, archive or compression magic is present at offset 0 or at the ext4 superblock
offset 1024 (observed 2-byte value at 1024 is random for all three files).

**Byte entropy (first 4 MiB of each):**

| file | entropy (bits/byte) | zero bytes in 4 MiB |
|---|---|---|
| rom.img | 8.0000 | 16,235 (0.39%) |
| rom1.img | 7.9999 | — |
| play.zip | 8.0000 | — |

A real ext4 / sparse-ext4 / cpio image contains large runs of zeros; these files contain almost none.

**Embedded-magic scan of the complete files.** Every magic was compared with the count expected
for uniformly random bytes:

| magic | expected (random) | rom.img | rom1.img | play.zip |
|---|---|---|---|---|
| ext4 superblock signature `53 ef` | ~1,847 | 1,814 | 2,660 (of 2,579) | 1,584 (of 1,545) |
| `ef 53` | ~1,847 | 1,857 | 2,605 | 1,557 |
| f2fs `10 c1` | ~1,847 | 1,764 | 2,644 | 1,628 |
| gzip `1f 8b` | ~1,847 | 1,923 | 2,584 | 1,520 |
| ZIP local header `PK\x03\x04` | ~46 | **0** | **0** | **0** |
| Android sparse `ed 3a 16 16` | ~46 | **0** | **0** | **0** |
| squashfs `hsqs`, erofs, 7z, lz4, zstd, ISO9660 `CD001`, FAT | ~46 | **0** | **0** | **0** |

Every 2-byte magic sits within noise of the random expectation, and every *long* magic is absent
completely. There is no plaintext filesystem, archive or partition table anywhere in any of the
three payloads.

**Headerless-compression test.** Each file was offered to raw DEFLATE (`zlib`, wbits −15 and 47),
LZMA raw + `.lzma`, bzip2, brotli (raw, via `brotli -dc` → `corrupt input [con]`), gzip and zstd.
All failed. None of these formats produces a valid stream from these bytes.

**Repeating-keystream test (many-time-pad / short-XOR-key).** Index of coincidence of `rom.img`
was measured at lags 2–4096: every lag returned 0.0037–0.0042 against the 0.0039 baseline for
uniformly random data — i.e. perfectly flat, no period. Separately, `rom.img XOR rom1.img` over
the first 4 MiB contained **no** zero run longer than 12 bytes, so the two payloads are not the
same plaintext under the same keystream. A printable-string sweep of the whole files found only
3,911 / 5,337 / 3,312 runs of ≥10 printable bytes (0.034 % of file), exactly what random data
yields at that threshold.

**Conclusion (Phase 1 items 5–9):** the partition content of this ROM is **cryptographically
opaque**. It is protected with a real cipher (AES-class or equivalent) whose key and the
`c=v2` container specification exist only inside the Virtual Master application. It is not
compressed-only, not XOR-obfuscated, not sparse, and not headerless-compressed.

Consequences, stated plainly:

1. The guest `/system` partition **cannot be read**, so WebView 81, `framework-res.apk`,
   `config_webview_packages.xml`, `build.prop`, SELinux contexts, OAT/VDEX artefacts and the
   partition layout **cannot be inspected** (Phase 1.7–1.10, Phase 2 and Phase 3 of the brief are
   not performable from these inputs).
2. The guest `/system` partition **cannot be modified**, so no "modified ROM ZIP" can be built —
   the modified archive could not be re-encrypted into a container Virtual Master would accept.
3. Any ZIP we produced that preserved these images byte-for-byte would *not* contain Google
   WebView 138. Shipping such a file would be a false deliverable, so it has not been produced.

**What would unblock this:** the Virtual Master app APK (so the `c=v2` container and its key
derivation can be analysed locally), or a Virtual Master *export* of the guest image in raw /
sparse form, or a host that runs the same ROM package where the decrypted image can be captured.
Note that `support_a32:false` (§5) blocks the project independently of this.

---

## 4. Structure summary

| Item | Finding |
|---|---|
| Package type | Virtual Master VM ROM distribution package (app-private format) |
| Install method | Import by the Virtual Master app (`minimum_app_ver` 3.2.16); no recovery/TWRP flashing |
| Distributions | 2 disk images + 1 GApps payload, all encrypted |
| Partitions visible | none — no per-partition images are exposed |
| Dynamic partitions | not determinable (opaque) |
| AVB / dm-verity / vbmeta | not present in the package; integrity is enforced by the container cipher instead |
| Prebuilt apps visible | none |
| First-boot scripts visible | none (no script layer at all) |
| Signature of the ZIP itself | none — the outer ZIP is unsigned; there is no `META-INF/com/google/android/*` |

Because the outer ZIP carries no signature, the "does modification invalidate the signature"
question in Phase 8 is moot for the container: the *content* is what is protected, and it is
protected by a cipher we do not hold.

---

## 5. Guest ABI — the first hard blocker

`manifest.json` declares **`support_a32: false` / `support_a64: true`**: this Android 9 guest image
is 64-bit ARM only. The replacement APK is 32-bit only (independently verified, see
`WEBVIEW_138_COMPATIBILITY.md` §2): both native libraries are `ELF32` with
`e_machine = EM_ARM (0x28)`, i.e. real 32-bit ARM code, and the only ABI directory in the archive
is `lib/armeabi-v7a`.

`armeabi-v7a` code cannot be mapped by an `arm64-v8a`-only process. This is not a renaming or
repackaging problem and cannot be patched around by any file-level edit.

Status: **verified as far as the available inputs allow.** The ROM-side evidence is the package's
own capability flag; the APK-side evidence is direct ELF inspection. The one remaining
empirical confirmation is inside the guest, which requires the app:

```sh
getprop ro.product.cpu.abilist
getprop ro.product.cpu.abilist32
getprop ro.product.cpu.abilist64
unzip -l /system/app/webview/webview.apk | grep 'lib/'
dumpsys package com.android.webview | grep -iE 'CpuAbi|abi'
dumpsys webviewupdate
```

If `abilist32` is empty (as `support_a32:false` predicts), installing the supplied APK will fail
with `INSTALL_FAILED_NO_MATCHING_ABIS (-113)`.

*Correction added later in the session:* the same sentence previously claimed a system-partition
copy "would be skipped during the boot package scan". That is wrong for this APK. It declares
`android:multiArch="true"`, and in that path `PackageManagerService` deliberately ignores
`INSTALL_FAILED_NO_MATCHING_ABIS` (`maybeThrowExceptionForMultiArchCopy`), so a `/system/app` copy
would be **registered** and would fail only later, when the 32-bit library is dlopened. Details and
line references: `WEBVIEW_138_COMPATIBILITY.md` §2.0.

---

## 6. Existing WebView (Phase 2) — NOT PERFORMED, and why

Every Phase 2 item requires reading `/system` out of `rom.img`/`rom1.img`. Those images are
encrypted (§3). No part of the existing WebView 81 APK, its certificate, its OAT/VDEX artefacts,
its permissions, owner or SELinux label, and no part of `framework-res.apk` could be inspected.
Nothing here was assumed or filled in from generic documentation; the work is simply not possible
from these inputs, and is reported as such.

Two secondary facts, marked as **unverified user-supplied context** (not confirmed by this
analysis): the guest's `config_webview_packages` currently contains a single
`<webviewprovider packageName="com.android.webview" availableByDefault="true"/>`; and the guest
reports model "Pixel 4", build `PQ3A.190801.002`.

---

## 7. Tooling actually available in this environment

`unzip`, `brotli`, `xz`, `zstd`, `python3` 3.14 (with `zlib`, `lzma`, `hashlib`, `zipfile`,
`sqlite3`, `ctypes`), `tar`, `losetup`, `pm`.
Absent: `zip`, `7z`, `mke2fs`/`e2fsdroid`/`debugfs`/`fsck.ext4` (no ext4 tooling at all),
`simg2img`/`img2sdat`/`lpdump`/`magiskboot`, `openssl`, `java`, `apksigner`, `aapt`/`aapt2`,
`python-cryptography`, `gcc`/`clang`. No `mount`, and the session is a non-root `untrusted_app`.

This matters even if the images were readable: with no ext4 userspace tooling, no root and no
mount, rebuilding a guest filesystem here would itself require installing packages (which needs
explicit authorisation) or writing an ext4 implementation from scratch. APK inspection was done
with a purpose-written pure-Python binary-AXML / APK-Signing-Block / DER / RSA parser
(`work/apkinfo2.py`, `work/verify_sig.py`) precisely to avoid installing anything.

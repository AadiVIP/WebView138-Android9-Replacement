# Source provenance for the §4 citations

Every "file:line" in `WEBVIEW_138_COMPATIBILITY.md` §4 refers to AOSP tag
**`android-9.0.0_r35`** in `platform/frameworks/base`, downloaded read-only in this session and
kept outside the project tree at `/data/data/com.termux/files/usr/tmp/aosp9/`.

Fetch form (verified working for these paths):

    https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-9.0.0_r35/<path>?format=TEXT

which returns base64; the local copies are the decoded result. `core/res/res/xml/…`,
`services/core/java/com/android/server/webkit/…`, `services/core/java/com/android/server/pm/…` and
`core/java/android/webkit/…` are the four directories involved.

## SHA-256 of each local copy used

| File (repo-relative) | SHA-256 (local copy) | Used for |
|---|---|---|
| `core/res/res/xml/config_webview_packages.xml` | `0e622fc5…42cf` | stock AOSP 9 provider list = `com.android.webview` only |
| `services/core/java/com/android/server/webkit/SystemImpl.java` | `43637e54…a140` | tag/attribute grammar, resource id, `systemIsDebuggable`, `Settings.Global.WEBVIEW_PROVIDER` |
| `services/core/java/com/android/server/webkit/WebViewProviderInfo.java` | `794d73f2…13a08` | `new Signature(Base64.decode(text, Base64.DEFAULT))` |
| `services/core/java/com/android/server/webkit/WebViewUpdater.java` | `831b4222…6b6a3` | `validityResult`, `versionCodeGE`, `getMinimumVersionCode`, `providerHasValidSignature`, selection order |
| `services/core/java/com/android/server/webkit/WebViewUpdateService.java` | `4c0b75d3…82ef` | `onShellCommand` wiring (existence of `cmd webviewupdate`) |
| `services/core/java/com/android/server/webkit/WebViewLibraryLoader.java` | `f286ae10…2eac` | relro paths, `SHARED_RELRO_UID`, non-fatal relro failure |
| `core/java/android/webkit/WebViewFactory.java` | `fac7b7c0…f0bd7` | `com.android.webview.WebViewLibrary` meta-data lookup |
| `core/java/android/webkit/UserPackage.java` | `cacdeffa…9641d` | `MINIMUM_SUPPORTED_SDK = Build.VERSION_CODES.P`, `hasCorrectTargetSdkVersion` |
| `services/core/java/com/android/server/pm/NativeLibraryHelper.java` | `277733eb…350ad` | `findSupportedAbi` contract (−113 vs NO_NATIVE_LIBRARIES) |
| `services/core/java/com/android/server/pm/PackageManagerService.java` | `0a187f45…20cdf` | `derivePackageAbi`, `maybeThrowExceptionForMultiArchCopy`, `scanDirLI` error handling, `setBundledAppAbisAndRoots` |
| `services/core/java/com/android/server/pm/PackageParser.java` | `1ca38e5b…c2b3` | not cited in §4 (kept for completeness) |
| `core/java/android/content/pm/ApplicationInfo.java` | `bce57611…b71b30` | `isSystemApp()` definition behind gate 3(b) |

Note on the last two `pm/` files: their raw downloads arrived as a single base64 line, so the
decoded copies (`PackageManagerService.java.dec`, `PackageParser.java.dec`) are what was read; the
line numbers quoted in the reports are those of the decoded content, i.e. of the file itself.

## What this does NOT establish

- It is **not** the ROM's code. The ROM's `services.jar`, `framework-res.apk` and
  `PackageManagerService` live inside the encrypted `rom.img`/`rom1.img` and were never read.
  A vendor can patch any of these gates; the build in question is a `PQ3A.190801.002` image of
  unknown provenance, not a pristine AOSP build.
- Nothing here was executed. No emulator, no guest, no boot, no install was performed, so every
  "the framework will do X" statement in these reports is a **reading of source**, not an
  observation.
- `UserPackage.java` was located by following `import android.webkit.UserPackage;` from
  `WebViewUpdater.java:25`, i.e. under `core/java/android/webkit/`, not under `server/webkit/`.
  Two earlier path guesses returned `NOT_FOUND`; the file was not paraphrased from memory.

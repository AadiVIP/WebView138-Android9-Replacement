# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-09

First public release of the audited, deterministic build.

### Added
- Static RRO overlay `com.qoder.webviewprovider.overlay` (2688 B, unsigned by design) that
  replaces `android:xml/config_webview_packages` on Android 9, listing
  `com.google.android.webview` first (Google certificate as `<signature>` element text) and
  preserving the factory `com.android.webview` entry verbatim.
- Magisk module `webview138-replacement` (`WebView138-Replacement-Magisk.zip`, 18181 B)
  delivering the overlay to `/vendor/overlay` (or `/product/overlay`) systemlessly:
  `customize.sh` install gates, `service.sh` boot-time verification log + one backed-up
  `webview_provider` pin fix, `uninstall.sh` preference restore.
- `tools/magisk_deploy.sh` — drop-in install / verify / rollback (the tested deployment route).
- `tools/download_webview_apk.sh` — obtain + SHA-256-verify helper for the proprietary
  Google WebView 138.0.7204.179 package (the 222 MB APK is not redistributed).
- Build and audit toolchain in pure Python (AXML + resources.arsc writers, independent
  overlay auditor, module ZIP auditor, sandboxed lifecycle test) — no aapt, Java or signing
  key anywhere.
- Documentation: installation guide, rollback guide, architecture, compatibility analysis,
  troubleshooting, the original engineering reports verbatim, and the AOSP
  `android-9.0.0_r35` reference sources they cite.
- `checksums/SHA256SUMS.txt` for every artifact in the repository.

### Notes
- Release artifacts are the exact audited bytes: deterministic rebuild reproduced the
  overlay, manifest and module ZIP byte-for-byte (ZIP SHA-256
  `b6323730c2fe56894477d2cf854c18c8e1732f4befa04c05ed3572bc89797955`).
- 409 checks across six suites, 0 failures (see README "Quality assurance evidence").
- Runtime behaviour on the target guest is intentionally NOT claimed; the acceptance tests
  are `docs/INSTALLATION_GUIDE.md` §7.

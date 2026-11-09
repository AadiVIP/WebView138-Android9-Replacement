# Security Policy

## Scope

This project is a Magisk module + static RRO overlay that changes which WebView provider an
Android 9 (API 28) ARM64 guest selects. Its security-relevant surface is small and deliberate:

- it installs **one 2688-byte unsigned-by-design RRO** into a scanned overlay directory;
- it may write **exactly one setting** (`Settings.Global.webview_provider`), always backing up
  the previous value first;
- it optionally, **only on explicit opt-in** (`auto-install` flag file), runs
  `pm install -r` on a package whose SHA-256 it re-verifies first;
- it never writes partitions, never touches `/system` or the factory WebView, and its scripts
  are linted for a denylist of destructive commands (`tools/audit_magisk.py`).

## Supply-chain posture

- The release artifacts are the audited bytes. Verify them before use:
  `checksums/SHA256SUMS.txt` lists the SHA-256 of every artifact in this repository.
- The module re-verifies its own payload SHA-256 against the embedded audit manifest
  (`webview138.manifest`) on install; a tampered overlay refuses to install.
- The 222 MB Google WebView package is **not distributed by this project**. Obtain it from an
  authorized channel and run `tools/download_webview_apk.sh` against it — it refuses on any
  SHA-256 or identity mismatch and explicitly rejects the ARMv7-only 138.0.7204.181 build.
- The build chain is deterministic: the overlay, manifest and module ZIP rebuild
  byte-identically from `src/inputs/` + `tools/`, so "the ZIP I audited is the ZIP you have"
  is checkable by SHA-256 alone.

## What this project does NOT do (and reports as unverified rather than claiming)

Runtime behaviour on the target guest (Magisk version, magic-mount of a new overlay directory,
`idmap` success, native library load) is **not verified** in this repository. See
`docs/ARCHITECTURE.md` §8 for the exact list and the commands that settle each item.

## Reporting a vulnerability

Report security issues **privately** by opening a security advisory on this repository
(GitHub: Security → Advisories → New draft) or by emailing the repository owner through the
GitHub account associated with the repository. Please include:

- which artifact and SHA-256 you were testing;
- the observed behaviour and a reproduction path;
- whether the issue could change the provider selection or write state beyond the module
  directory and the single documented setting.

Please do **not** file public issues for security concerns, and do not publish proof-of-concept
payloads targeting other users' devices.

## Supported versions

v1.0.0 is the only released version. It is built and gated for **Android 9 / API 28, ARM64,
Magisk** only; `customize.sh` and `tools/magisk_deploy.sh` refuse to install on anything else.

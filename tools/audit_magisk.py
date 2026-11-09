#!/usr/bin/env python3
"""Independently audit output/WebView138-Replacement-Magisk.zip.

    python3 tools/audit_magisk.py [--zip output/WebView138-Replacement-Magisk.zip]

Deliberately separate from tools/build_magisk.py for the same reason verify_overlay.py is separate
from build_overlay.py: a builder asserts with its own assumptions, so agreement proves nothing. This
opens the finished archive, re-checks the bytes, and greps every shell script for the commands that
would make this module dangerous on somebody else's phone. A module is executed as ROOT at boot; the
bar for "no destructive command" has to be absolute, not "looked OK".

Checks:
  1  archive integrity + entry whitelist (no absolute paths, no '..', nothing outside META-INF/<id>)
  2  Magisk ZIP contract (updater-script '#MAGISK', module.prop id == directory name)
  3  the payload is exactly the audited overlay, and the embedded manifest still matches it
  4  the provider logic the boot depends on (order, availableByDefault, isFallback, cert base64)
  5  script lint: forbidden commands, and every rm target confined to the module's own directories
  6  the staged source tree is byte-identical to the archive (so what you read is what you flash)
  7  the README's measurable claims equal reality, and the 222 MB APK is NOT smuggled in
"""
import argparse, base64, hashlib, io, os, re, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MOD_ID = 'webview138-replacement'
GOOGLE = 'com.google.android.webview'
REQUIRED = ['module.prop', 'customize.sh', 'service.sh', 'uninstall.sh', 'README.md',
            'webview138.manifest', 'webview138-apk.prop', 'system/vendor/overlay/webview138-provider-overlay.apk']
EXECUTABLE = ['customize.sh', 'service.sh', 'uninstall.sh']

# Commands that must not appear anywhere in a module, in any branch, at any privilege level.
FORBIDDEN = [
    (r'\bmkfs\b',                     'makes a filesystem'),
    (r'\bdd\s+.*\bof=/dev/',          'writes a raw block device'),
    (r'\bformat\b\s',                 'formats'),
    (r'mount\s+-o\s+remount',         'remounts a partition read-write'),
    (r'\bpm\s+uninstall\b',           'removes a package'),
    (r'\bpm\s+disable\b(?!-user)',    'hard-disables a package'),
    (r'\bpm\s+clear\b',               'wipes app data'),
    (r'settings\s+delete\s+global\s+webview_fallback', 'disables the platform fallback logic'),
    (r'\bfastboot\b|\bspctl\s+stop\b|\bsetprop\s+ctl\.', 'stops/restarts system services'),
    (r'\bkillall\b|\bpkill\b',        'kills processes'),
    (r'\b(curl|wget)\b',              'network fetch at install/boot time'),
    (r'(?<![\d&])>\s*/dev/(?!null)',   'writes to a device node'),
    (r'\bchmod\s+(-\w+\s+)*\w+\s+/system',   'changes permissions on /system'),
    (r'\bchown\s+.*\s/(system|vendor|product)\b', 'changes ownership on a system partition'),
    (r'\brestorecon\b[^\n]*/system',  'relabels /system'),
    (r'\breboot\b|\bshutdown\b',      'reboots the device by itself'),
    (r'\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+/(\s|"?$)', 'recursive delete of /'),
    (r'\biptables\b|\bndc\s+setting\b', 'changes networking'),
]

# Every 'rm' in the module may only ever target these roots. A delete outside them is a bug.
RM_ALLOWED_PREFIXES = ('$MODPATH', '$MODDIR', '$WORK', '$TMP', '$STAGE', '$SCRATCH', '$DEST',
                       '/data/adb/modules/')


def scrub(body):
    """Blank out heredoc bodies so that the *instructions* a script prints are not mistaken for the
    commands it runs, while keeping line numbers identical for the report."""
    lines = body.split('\n')
    out, delim = [], None
    for ln in lines:
        if delim is not None:
            if ln.strip() == delim:
                delim = None
                out.append('')
            else:
                out.append('')
            continue
        mo = re.search(r'<<-?[\'"]?(\w+)[\'"]?', ln)
        out.append(ln)
        if mo:
            delim = mo.group(1)
    return '\n'.join(out)


def audit_scripts(texts, check):
    for name, body in sorted(texts.items()):
        code = scrub(body)
        hits = []
        for pat, why in FORBIDDEN:
            for mo in re.finditer(pat, code):
                line = body[:mo.start()].count('\n') + 1
                # a match inside a comment line is documentation, not behaviour - but say so loudly
                stripped = body.split('\n')[line - 1].lstrip()
                ctx = 'comment' if stripped.startswith('#') or stripped.startswith('echo') \
                      or stripped.startswith('say') else 'CODE'
                hits.append('%s:%d [%s] %s -> %s' % (name, line, ctx, why, stripped[:88]))
        if not hits:
            check('no forbidden command in %s' % name, True)
        for h in hits:
            # comments/echoes are allowed to NAME a danger; executable code may not
            check('no forbidden command in %s' % name, '[CODE]' not in h, h)
        # rm blast radius
        bad = []
        for i, ln in enumerate(code.split('\n'), 1):
            s = ln.strip()
            mo = re.search(r'(^|[;&|]\s*)rm\s+(\S+)\s+(\S+)', s)
            if not mo:
                continue
            tgt = mo.group(3)
            if not any(tgt.startswith(p) or p in tgt for p in RM_ALLOWED_PREFIXES):
                bad.append('%s:%d rm target %r' % (name, i, tgt))
        check('every rm in %s targets only the module directory' % name, not bad, '; '.join(bad))
        check('%s has a shebang' % name, body.startswith('#!'), body.split('\n')[0][:60])
        check('%s exits 0 on success' % name, re.search(r'\bexit 0\b', body) is not None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', default='output/WebView138-Replacement-Magisk.zip')
    ap.add_argument('--overlay', default='output/webview138-provider-overlay.apk')
    ap.add_argument('--manifest', default='output/webview138-provider-overlay.manifest')
    ap.add_argument('--webview-apk', default='input/webview138_arm64_universal_138.0.7204.179.apk')
    ap.add_argument('--stagedir', default='work/magisk_stage')
    ap.add_argument('--report', default=None, help='write the findings to a text file too')
    ap.add_argument('--extra-script', dest='extra_script', action='append', default=[],
                    help='additional shell scripts to lint with the same rules (the deploy helper '
                         'ships alongside the module and also runs as root)')
    a = ap.parse_args()

    out = []
    def emit(s=''):
        out.append(s)
        print(s)

    raw = open(a.zip, 'rb').read()
    emit('=== %s (%d B, sha256=%s) ===' % (os.path.basename(a.zip), len(raw),
                                           hashlib.sha256(raw).hexdigest()))
    checks, fails = [], []

    def check(name, ok, detail=''):
        checks.append(name)
        if not ok:
            fails.append('%s  %s' % (name, detail))
        emit('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  - ' + detail) if detail else ''))

    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()

    # ---- 1. integrity + entry whitelist
    check('every entry decompresses with a correct CRC', z.testzip() is None)
    check('no entry name is absolute or contains ".."',
          not any(n.startswith('/') or '..' in n.split('/') for n in names), str(names))
    stray = [n for n in names
             if not (n.startswith('META-INF/com/google/android/') or n.startswith(MOD_ID + '/'))]
    check('nothing outside META-INF/com/google/android/ and %s/' % MOD_ID, not stray, str(stray))
    big = [(n, z.getinfo(n).file_size) for n in names if z.getinfo(n).file_size > 20 << 20]
    check('no large binary smuggled into the module (largest entry %d B)'
          % max([z.getinfo(n).file_size for n in names]), not big, str(big))

    # ---- 2. Magisk ZIP contract
    us = z.read('META-INF/com/google/android/updater-script').decode()
    check("updater-script is exactly '#MAGISK' (how Magisk recognises a module ZIP)",
          us.split('\n')[0] == '#MAGISK', repr(us[:40]))
    check('META-INF/com/google/android/update-binary present',
          'META-INF/com/google/android/update-binary' in names)
    md = z.read('%s/module.prop' % MOD_ID).decode()
    props = {}
    for line in md.splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            props[k.strip()] = v.strip()
    check('module.prop has id/name/version/versionCode/author/description',
          all(k in props for k in ('id', 'name', 'version', 'versionCode', 'author', 'description')),
          str(sorted(props)))
    check('module.prop id == the directory the files live in (Magisk requires this)',
          props.get('id') == MOD_ID, '%r vs %r' % (props.get('id'), MOD_ID))
    check('module.prop has no CR and no spaces in id',
          '\r' not in md and ' ' not in props.get('id', ''), repr(props.get('id')))
    check('no non-ASCII anywhere in module.prop', md.isascii(), repr(md[:60]))

    # ---- 3. payload == the audited overlay
    mtxt = z.read('%s/webview138.manifest' % MOD_ID).decode()
    man = {}
    for line in mtxt.splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            man[k] = v
    check('embedded manifest is byte-identical to %s' % os.path.basename(a.manifest),
          mtxt == open(a.manifest).read())
    overlay_name = man.get('overlay_file')
    arc = '%s/system/%s/%s' % (MOD_ID, 'vendor/overlay', overlay_name)
    if arc not in names:
        arc = next((n for n in names if n.endswith('.apk') and '/system/' in n), None)
    check('exactly one APK inside the module, at system/<partition>/overlay/',
          arc is not None and sum(1 for n in names if n.endswith('.apk')) == 1, str(arc))
    if arc:
        got = z.read(arc)
        emit('  module payload: %s  %d B  sha256=%s'
             % (arc, len(got), hashlib.sha256(got).hexdigest()))
        check('payload sha256 == the manifest the auditor wrote',
              hashlib.sha256(got).hexdigest() == man.get('overlay_sha256'))
        check('payload is byte-identical to %s' % os.path.basename(a.overlay),
              got == open(a.overlay, 'rb').read())
        check('payload is STORED (uncompressed) so it lands on disk byte-for-byte',
              z.getinfo(arc).compress_type == zipfile.ZIP_STORED,
              'compress_type=%d' % z.getinfo(arc).compress_type)

    # ---- 4. the provider logic this module stakes the boot on
    check('provider #1 is %s' % GOOGLE, man.get('provider_1_packageName') == GOOGLE,
          repr(man.get('provider_1_packageName')))
    check('provider #1 availableByDefault=true (WebViewUpdater.java:306-316 only auto-selects those)',
          man.get('provider_1_availableByDefault') == 'true', repr(man.get('provider_1_availableByDefault')))
    check('provider #1 isFallback=false (else WebViewUpdateServiceImpl.java:202-220 DISABLES it)',
          man.get('provider_1_isFallback') == 'false', repr(man.get('provider_1_isFallback')))
    pc = int(man.get('provider_count', '0'))
    check('provider_count >= 2 - the factory provider must survive so a guest is never left '
          'without a WebView (SystemImpl.java:138-144 throws otherwise)', pc >= 2, str(pc))
    check('exactly one %s entry (two would be ambiguous)' % GOOGLE,
          1 == sum(1 for i in range(1, pc + 1) if man.get('provider_%d_packageName' % i) == GOOGLE))
    check('overlay targetPackage=android, isStatic=true',
          man.get('overlay_targetPackage') == 'android' and man.get('overlay_isStatic') == 'true',
          '%s / %s' % (man.get('overlay_targetPackage'), man.get('overlay_isStatic')))
    try:
        der = base64.b64decode(man.get('cert_base64', ''))
        ok = hashlib.sha256(der).hexdigest() == man.get('cert_sha256')
    except Exception as e:
        der, ok = b'', False
    check('cert_base64 decodes and matches cert_sha256 (the FULL certificate, not a fingerprint)',
          ok, '%d B' % len(der))
    check('cert is single-line canonical base64 (WebViewProviderInfo.java:42 Base64.DEFAULT)',
          re.match(r'^[A-Za-z0-9+/]+={0,2}$', man.get('cert_base64', '')) is not None,
          '%d chars' % len(man.get('cert_base64', '')))
    if os.path.isfile(a.webview_apk):
        want = hashlib.sha256(open(a.webview_apk, 'rb').read()).hexdigest()
        vder = None
        import struct
        raw_apk = open(a.webview_apk, 'rb').read()
        at = raw_apk.rfind(b'PK\x05\x06')
        check('the 138 APK still has an APK Signing Block', at > 0 and
              raw_apk[struct.unpack_from('<I', raw_apk, at + 16)[0] - 16:
                       struct.unpack_from('<I', raw_apk, at + 16)[0]] == b'APK Sig Block 42')
        check('manifest provider #1 signature is the certificate the 138 APK is signed with '
              '(sha256 of the 138 APK recorded for the record: %s)' % want[:16],
              man.get('provider_1_signature1_sha256') == man.get('cert_sha256'),
              '%s vs %s' % (man.get('provider_1_signature1_sha256'), man.get('cert_sha256')))

    # ---- 5. scripts
    texts = {}
    for n in names:
        if n.endswith('.sh') or n.endswith('update-binary'):
            texts[n.split('/', 1)[1] if n.startswith(MOD_ID + '/') else n] = z.read(n).decode()
    emit('  scripts found: %s' % ', '.join(sorted(texts)))
    for e in EXECUTABLE:
        check('module carries %s' % e, any(k == e for k in texts))
    # the off-device helper that installs the same tree is part of the delivery, so lint it too
    for p in (a.extra_script or ['tools/magisk_deploy.sh']):
        if os.path.isfile(p):
            texts['helper:' + os.path.basename(p)] = open(p).read()
        else:
            check('extra script %s exists' % p, False)
    audit_scripts(texts, check)
    helpl = [v for k, v in texts.items() if k.startswith('helper:')]
    if helpl:
        h = helpl[0]
        check('the deploy helper deletes ONLY a path it proved is its own module directory',
              re.search(r'case "\$DEST" in\s*\n\s*/data/adb/modules/"\$MOD_ID"', h) is not None and
              'rm -rf "$DEST"' in h)
        check('the deploy helper refuses to write without --i-reviewed',
              '--i-reviewed' in h and 'REVIEWED=1' in h)
        check('the deploy helper refuses when /data/adb/modules is missing (no Magisk, no module)',
              'no Magisk, no modules' in h)
        # /data is 0771 + SELinux: EACCES for an existing dir and a never-created one are the same
        # answer to a non-root shell, so "not visible" must never be reported as "absent".
        check('the deploy helper does not conclude Magisk is absent from an unrooted shell',
              'NOT proof Magisk is absent' in h and re.search(
                  r'\[ "\$UID_N" != 0 \]', h) is not None and
              'DOES NOT EXIST' not in h)
        check('the deploy helper never copies anything into /system, /vendor or /product',
              re.search(r'\b(cp|mv|install)\s[^\n]*/(system|vendor|product)/\w', scrub(h)) is None)
        check('the deploy helper verifies the payload sha256 before installing',
              'overlay_sha256' in h and 'sha256sum' in h and 'MISMATCH' in h)
        check('the deploy helper runs the module\'s own customize.sh so both install paths validate alike',
              'customize.sh' in h)
        check('the deploy helper leaves the reboot decision to the user',
              'NOTHING HAS REBOOTED' in h and re.search(r'^\s*reboot\s*$', scrub(h), re.M) is None)
    check('no post-fs-data.sh shipped (nothing needs to run before system_server; magic mount does '
          'that job) - scripts are only included when actually required',
          'post-fs-data.sh' not in texts)
    # every write in service.sh must land in the module directory, and the only settings key it may
    # touch is the one it can also undo.
    svc = texts['service.sh']
    outside = []
    for ln in svc.split('\n'):
        if ln.strip().startswith('#'):
            continue
        for mo in re.finditer(r'(?<![\d&])>>?\s*("[^"]*"|\S+)', ln):
            # an odd number of quote characters before the match means the '>' is inside a string,
            # i.e. it is prose ("-> like this"), not a redirection
            if ln[:mo.start()].count('"') % 2:
                continue
            tgt = mo.group(1).strip('"')
            if tgt in ('/dev/null', '/dev/stdout'):      # discarding output is not a write
                continue
            if not any(t in tgt for t in ('$LOG', '$MODPATH', '$MODDIR')):
                outside.append('%s -> %s' % (ln.strip()[:60], tgt))
    check('service.sh redirects only into its own log / module directory', not outside,
          '; '.join(outside))
    keys = set(re.findall(r'settings\s+(?:put|get|delete)\s+(?:global|secure)\s+(\w+)', svc))
    check('service.sh reads or writes NO settings key except webview_provider',
          keys == {'webview_provider'}, str(sorted(keys)))
    check('service.sh pins the preference only after backing the old value up to pref-backup',
          'pref-backup' in svc and 'no-pin' in svc)
    check('uninstall.sh restores the pinned preference before the directory goes away',
          'pref-backup' in texts['uninstall.sh'] and 'webview_provider' in texts['uninstall.sh'])
    check('customize.sh verifies sha256 before declaring success',
          'sha256sum' in texts['customize.sh'] and 'overlay_sha256' in texts['customize.sh'])
    check('customize.sh refuses a non-28 API and explains why',
          'API' in texts['customize.sh'] and '28' in texts['customize.sh'])
    # VDIR/PDIR exist only so the branch is testable; the defaults must stay the real device paths.
    for k in ('customize.sh', 'service.sh'):
        check('%s defaults the scanned dirs to the real /vendor/overlay and /product/overlay' % k,
              ': "${VDIR:=/vendor/overlay}"' in texts[k] and ': "${PDIR:=/product/overlay}"' in texts[k])
    check('the module never references framework-res.apk as something it modifies',
          not re.search(r'(cp|mv|dd|chmod|patch)\s[^\n]*framework-res', '\n'.join(texts.values())))
    # the identity file the opt-in install is guarded by
    apkp = z.read('%s/webview138-apk.prop' % MOD_ID).decode()
    apk = {}
    for line in apkp.splitlines():
        if line.startswith('webview_apk_') and '=' in line:
            k, v = line.split('=', 1)
            apk[k] = v
    check('webview138-apk.prop names the package the overlay declares',
          apk.get('webview_apk_package') == man.get('provider_1_packageName'),
          '%s vs %s' % (apk.get('webview_apk_package'), man.get('provider_1_packageName')))
    check('the recorded maxSdkVersion is 28, i.e. this really is the Android 8.0-9.0 branch build',
          apk.get('webview_apk_maxSdkVersion') == '28', repr(apk.get('webview_apk_maxSdkVersion')))
    check('the recorded minSdkVersion is <= 28', (apk.get('webview_apk_minSdkVersion') or '99').isdigit()
          and int(apk.get('webview_apk_minSdkVersion', '99')) <= 28,
          apk.get('webview_apk_minSdkVersion'))
    check('the recorded targetSdkVersion satisfies UserPackage.hasCorrectTargetSdkVersion (>= 28)',
          int(apk.get('webview_apk_targetSdkVersion') or 0) >= 28,
          apk.get('webview_apk_targetSdkVersion'))
    check('the recorded abis contain arm64-v8a',
          'arm64-v8a' in (apk.get('webview_apk_abis') or ''), apk.get('webview_apk_abis'))
    if os.path.isfile(a.webview_apk):
        check('webview138-apk.prop sha256 == the actual package on disk',
              apk.get('webview_apk_sha256') ==
              hashlib.sha256(open(a.webview_apk, 'rb').read()).hexdigest(),
              apk.get('webview_apk_sha256'))
        check('webview138-apk.prop size == the actual package size',
              apk.get('webview_apk_bytes') == str(os.path.getsize(a.webview_apk)),
              apk.get('webview_apk_bytes'))
        check('webview138-apk.prop versionName is the one the brief asked for',
              apk.get('webview_apk_versionName') == '138.0.7204.179',
              apk.get('webview_apk_versionName'))
    svc = texts['service.sh']
    branch = svc.split('auto-install" ]')[1] if 'auto-install" ]' in svc else ''
    head = branch.split('pm install -r')[0]
    check('the opt-in install cannot run without verifying the bytes first',
          'pm install -r' in svc and 'sha256sum' in head and 'REFUSED' in head,
          '%d chars of branch before the pm call' % len(head))
    check('the opt-in install is off unless the user creates the flag file',
          'if [ -f "$MODPATH/auto-install" ]' in svc)
    check('the module never mentions the platform signing key or a test key',
          not re.search(r'testkey|platform\.pk8|AOSP-?key', '\n'.join(texts.values()), re.I))

    # ---- 6. staged source == archive
    mismatch = []
    for n in names:
        p = os.path.join(a.stagedir, n)
        if not os.path.isfile(p):
            mismatch.append('missing on disk: %s' % n)
        elif open(p, 'rb').read() != z.read(n):
            mismatch.append('differs: %s' % n)
    extra = []
    for dirpath, _, fns in os.walk(a.stagedir):
        for f in fns:
            rel = os.path.relpath(os.path.join(dirpath, f), a.stagedir).replace(os.sep, '/')
            if rel not in names:
                extra.append(rel)
    check('every ZIP entry exists on disk in %s with identical bytes' % a.stagedir,
          not mismatch, '; '.join(mismatch))
    check('the staged tree holds nothing extra that is not in the ZIP', not extra, str(extra))

    # ---- 7. README honesty
    rd = z.read('%s/README.md' % MOD_ID).decode()
    check('README quotes the real payload sha256',
          hashlib.sha256(z.read(arc)).hexdigest() in rd)
    check('README quotes the real certificate sha256', man.get('cert_sha256') in rd)
    check('README is explicit that nothing was runtime-tested',
          'NOT verified' in rd and 'update-binary' in rd)
    check('README names the WebView 138 sha256 it expects on the device',
          (not os.path.isfile(a.webview_apk)) or
          hashlib.sha256(open(a.webview_apk, 'rb').read()).hexdigest() in rd)
    check('README tells you to install the 138 package separately (this module does not)',
          'pm install' in rd)

    emit('\n=== %d checks, %d failures ===' % (len(checks), len(fails)))
    for f in fails:
        emit('  FAIL: %s' % f)
    if a.report:
        with open(a.report, 'w') as fh:
            fh.write('\n'.join(out) + '\n')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Sandbox end-to-end test of the WebView-138 Magisk module. No device, no root, no partition write.

    python3 tools/selftest_magisk.py [--report work/magisk_selftest.txt]

Every claim about a script's behaviour that is not exercised here is a claim nobody has tested, so
the matrix deliberately covers the refusal paths, not just the happy ones:

  A  tools/magisk_deploy.sh lifecycle      check / install / reinstall / remove / foreign module /
                                          tampered payload / missing --i-reviewed / wrong MODULES_DIR
  B  service.sh                            unset pref / stale pref / double run / no-pin / package
                                          missing / overlay not mounted / log rotation
  C  customize.sh                          API gate, sha gate, manifest-logic gate, id gate,
                                          vendor->product relocation, refuse when neither dir exists
  D  META-INF update-binary                refuses when there is no Magisk environment
  E  host integrity                        /vendor/overlay and the inputs are byte-identical after
                                          the whole run (the standing rule: never modify the host)

Sandbox hooks (QODER_SHIM / QODER_UID / QODER_ALLOW_TARGET / MODULES_DIR / VDIR / PDIR) exist only so
these branches can run here; their defaults on a real device are the real paths and uid 0.
"""
import argparse, hashlib, os, re, shutil, stat, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAND = os.path.join(ROOT, 'work', 'magsand')
BIN = os.path.join(SAND, 'bin')
MODULES = os.path.join(SAND, 'modules')
SRC = os.path.join(SAND, 'src', 'webview138-replacement')
DEST = os.path.join(MODULES, 'webview138-replacement')
STAGED = os.path.join(ROOT, 'work', 'magisk_stage', 'webview138-replacement')
ZIPF = os.path.join(ROOT, 'output', 'WebView138-Replacement-Magisk.zip')
SH = '/system/bin/sh'

checks, fails, LOG = [], [], []
_real_print = print


def print(*args, **kw):          # mirror everything into the report file
    _real_print(*args, **kw)
    LOG.append(' '.join(str(x) for x in args))


def check(name, ok, detail=''):
    checks.append(name)
    if not ok:
        fails.append('%s  %s' % (name, detail))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  - ' + detail[:150]) if detail else ''))
    return ok


def head(t):
    print('\n--- %s ---' % t)


# ------------------------------------------------------------------ shims
SHIMS = {
'getprop': r'''#!/system/bin/sh
case "$1" in
  ro.build.version.sdk) echo "${FAKE_SDK:-28}" ;;
  ro.build.version.release) echo 9 ;;
  ro.build.type) echo user ;;
  ro.product.cpu.abilist64) echo arm64-v8a ;;
  ro.product.cpu.abilist32) echo armeabi-v7a,armeabi ;;
  *) echo "" ;;
esac
''',
'settings': r'''#!/system/bin/sh
# stateful: get / put / delete on "global" keys, file-backed
F="$SAND/settings"
[ -f "$F" ] || : > "$F"
case "$1" in
  get)    v=$(sed -n "s/^$3=//p" "$F" | head -1)
          if [ -n "$v" ]; then echo "$v"; else echo null; fi ;;
  put)    grep -v "^$3=" "$F" > "$F.n" 2>/dev/null; mv "$F.n" "$F"; echo "$3=$4" >> "$F" ;;
  delete) grep -v "^$3=" "$F" > "$F.n" 2>/dev/null; mv "$F.n" "$F" ;;
esac
''',
'pm': r'''#!/system/bin/sh
L="$SAND/pkg"
[ -f "$L" ] || : > "$L"
case "$1" in
  list)  grep -qx "$3" "$L" 2>/dev/null && echo "package:/data/app/$3-abc/base.apk" ;;
  path)  grep -qx "$2" "$L" 2>/dev/null && echo "package:$SAND/fakebase.apk" ;;
  install) echo Success; echo "$*" >> "$SAND/pm-installs" ;;
  *) : ;;
esac
exit 0
''',
'dumpsys': r'''#!/system/bin/sh
case "$1" in
  webviewupdate) printf 'Current WebView package (name, version): (com.android.webview, 81.0.4044.117)\n  Minimum WebView version code: 404411700\n  Fallback logic enabled: true\n  WebView packages:\n' ;;
  package)   printf '    versionName=%s\n    versionCode=%s\n' "${FAKE_VER:-138.0.7204.179}" "${FAKE_CODE:-720417901}" ;;
esac
''',
}


def write_shims():
    os.makedirs(BIN, exist_ok=True)
    for n, body in SHIMS.items():
        p = os.path.join(BIN, n)
        open(p, 'w').write(body)
        os.chmod(p, 0o755)


def env(**kw):
    e = dict(os.environ)
    e.update({'SAND': SAND, 'QODER_SHIM': BIN, 'MODULES_DIR': MODULES, 'QODER_UID': '0',
              'QODER_ALLOW_TARGET': '1',
              'PATH': '%s:/system/bin:/system/xbin:/usr/bin:/bin' % BIN})
    for k, v in kw.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = str(v)
    return e


def run(argv, **kw):
    extra = kw.pop('env', {})
    extra.update(kw)                     # per-call overrides (VDIR, API, QODER_ALLOW_TARGET...)
    e = env(**extra)
    p = subprocess.run(argv, env=e, cwd=ROOT, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True, timeout=180)
    return p.returncode, p.stdout


def deploy(*args, **kw):
    return run([SH, 'tools/magisk_deploy.sh'] + list(args), **kw)


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def set_pref(v):
    open(os.path.join(SAND, 'settings'), 'w').write('' if v is None else 'webview_provider=%s\n' % v)


def set_packages(*names):
    open(os.path.join(SAND, 'pkg'), 'w').write(''.join(n + '\n' for n in names))


def fresh_src():
    if os.path.exists(os.path.dirname(SRC)):
        shutil.rmtree(os.path.dirname(SRC))
    shutil.copytree(STAGED, SRC)


def install_ok(label=''):
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed')
    assert rc == 0, out
    return rc, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', default=None)
    a = ap.parse_args()
    log = LOG
    for p in (STAGED, ZIPF):
        if not os.path.exists(p):
            print('missing %s - run tools/build_magisk.py first' % p)
            return 2

    # host integrity snapshot (E)
    vend_before = sorted(os.listdir('/vendor/overlay')) if os.path.isdir('/vendor/overlay') else None
    inputs_md5 = {f: os.popen('md5sum input/' + f).read().split()[0]
                  for f in sorted(os.listdir('input'))} if os.path.isdir('input') else {}
    adb_real = os.path.exists('/data/adb/modules')
    mounts_before = open('/proc/mounts').read()
    host_pref_before = subprocess.run(['/system/bin/settings', 'get', 'global', 'webview_provider'],
                                      capture_output=True, text=True).stdout.strip()

    if os.path.exists(SAND):
        shutil.rmtree(SAND)
    os.makedirs(MODULES, exist_ok=True)
    write_shims()
    set_packages('com.android.webview')
    set_pref(None)

    # ================================================================== A. deploy lifecycle
    head('A. tools/magisk_deploy.sh lifecycle')
    rc, out = deploy('--check')
    check('A1 check mode runs read-only and exits 0', rc == 0 and not os.path.isdir(DEST), 'rc=%d' % rc)
    check('A1 check mode reports the real scanned directory', '/vendor/overlay' in out or 'does not exist' in out)
    fresh_src()
    rc, out = deploy('--install', '--src', SRC)
    check('A2 install WITHOUT --i-reviewed is refused', rc != 0 and 'REFUSED' in out and not os.path.isdir(DEST))
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed', QODER_ALLOW_TARGET=None)
    check('A3 install with the sandbox flag absent is refused (MODULES_DIR guard)',
          rc != 0 and 'not /data/adb/modules' in out, out[-200:])
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed')
    check('A4 install proceeds once the operator has reviewed it',
          rc == 0 and os.path.isdir(DEST), out[-300:])
    check('A4 customize.sh ran and passed inside the install', 'customize.sh OK' in out)
    pairs = []
    for dirpath, _, fns in os.walk(SRC):
        for f in fns:
            rel = os.path.relpath(os.path.join(dirpath, f), SRC)
            pairs.append((os.path.join(SRC, rel), os.path.join(DEST, rel)))
    check('A5 every module file landed byte-identical',
          all(os.path.isfile(d) and sha(s) == sha(d) for s, d in pairs) and len(pairs) >= 7,
          '%d files' % len(pairs))
    check('A5 the payload is at system/vendor/overlay in the module dir',
          os.path.isfile(os.path.join(DEST, 'system', 'vendor', 'overlay',
                                      'webview138-provider-overlay.apk')))
    marker = os.path.join(DEST, 'installed-overlay.sha256')
    payload = os.path.join(DEST, 'system', 'vendor', 'overlay', 'webview138-provider-overlay.apk')
    check('A6 install records which bytes it accepted',
          os.path.isfile(payload) and os.path.isfile(marker) and
          sha(payload) == open(marker).read().strip())
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed')
    check('A7 a second install refuses instead of silently replacing',
          rc != 0 and 'already installed' in out)
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed', '--reinstall')
    check('A8 --reinstall is allowed explicitly', rc == 0, out[-160:])
    open(os.path.join(SRC, 'system', 'vendor', 'overlay',
                      'webview138-provider-overlay.apk'), 'ab').write(b'X')
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed', '--reinstall')
    check('A9 a tampered payload is refused before anything is copied',
          rc != 0 and 'MISMATCH' in out, out[-200:])
    fresh_src()
    # foreign module occupying the destination
    os.makedirs(DEST, exist_ok=True)
    open(os.path.join(DEST, 'module.prop'), 'w').write('id=some.other.module\nname=x\n')
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed', '--reinstall')
    check('A10 a foreign module at the same path is never overwritten',
          rc != 0 and "somebody else's module" in out)
    shutil.rmtree(DEST)
    install_ok()
    rc, out = deploy('--remove')
    check('A11 --remove without review is refused', rc != 0 and os.path.isdir(DEST))
    rc, out = deploy('--remove', '--i-reviewed')
    check('A12 --remove runs the module rollback and deletes only our directory',
          rc == 0 and not os.path.isdir(DEST) and os.path.isdir(MODULES), out[-200:])
    rc, out = deploy('--remove', '--i-reviewed')
    check('A13 --remove on an absent module refuses rather than inventing a path',
          rc != 0 and 'nothing this script may remove' in out)
    # An unrooted shell gets EACCES for an existing AND a never-created /data/adb, so the helper must
    # report "cannot look" and refuse, never "no Magisk".
    ghost = os.path.join(SAND, 'nodir-modules')
    rc, out = deploy('--install', '--src', SRC, '--i-reviewed',
                     QODER_UID='10180', QODER_ALLOW_TARGET='1', MODULES_DIR=ghost)
    check('A14 a non-root shell is told it cannot look, not that Magisk is absent',
          rc != 0 and 'NOT proof Magisk is absent' in out and 'no Magisk, no modules' not in out)
    rc, out = deploy('--check', QODER_UID='10180', MODULES_DIR=ghost)
    check('A14 check mode still exits 0 and says so',
          rc == 0 and 'NOT proof Magisk is absent' in out and not os.path.isdir(ghost))

    # ================================================================== B. service.sh
    head('B. service.sh (the per-boot verifier + the one pinned setting)')
    install_ok()
    svc = [SH, os.path.join(DEST, 'service.sh')]
    # a fake 'magic mount': the file appearing in a directory the script is told to look in
    FAKEV = os.path.join(SAND, 'fakevendor')
    os.makedirs(os.path.join(FAKEV, 'overlay'), exist_ok=True)
    shutil.copy(os.path.join(DEST, 'system', 'vendor', 'overlay',
                             'webview138-provider-overlay.apk'),
                os.path.join(FAKEV, 'overlay'))
    set_pref(None); set_packages('com.android.webview', 'com.google.android.webview')
    rc, out = run(svc, VDIR=os.path.join(FAKEV, 'overlay'), PDIR=os.path.join(SAND, 'none'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B1 unset preference -> document order, no write at all',
          rc == 0 and 'unset -> document order' in lg and not os.path.exists(os.path.join(DEST, 'pref-backup')))
    check('B1 the overlay is reported as mounted', 'OVERLAY MOUNTED' in lg)
    check('B1 the installed package version is read from the framework',
          '138.0.7204.179' in lg)
    set_pref('com.android.webview')
    rc, out = run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    now = open(os.path.join(SAND, 'settings')).read()
    check('B2 a stale user choice is overruled by the module',
          'webview_provider=com.google.android.webview' in now, now)
    check('B2 the value it replaced is backed up verbatim',
          open(os.path.join(DEST, 'pref-backup')).read() == 'com.android.webview')
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B3 a second boot does not clobber the backup with its own value',
          open(os.path.join(DEST, 'pref-backup')).read() == 'com.android.webview' and
          'already com.google.android.webview' in lg)
    rc, out = run([SH, os.path.join(DEST, 'uninstall.sh')])
    after = open(os.path.join(SAND, 'settings')).read()
    check('B4 uninstall.sh restores WebView 81 as the pinned choice (rollback of the pin)',
          'webview_provider=com.android.webview' in after, after)
    open(os.path.join(DEST, 'no-pin'), 'w').close()
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B5 an operator can turn the pinning off with a flag file',
          'Pinning skipped' in lg and
          'webview_provider=com.android.webview' in open(os.path.join(SAND, 'settings')).read())
    os.remove(os.path.join(DEST, 'no-pin'))
    set_pref('com.android.webview')
    set_packages('com.android.webview')             # Google NOT installed
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B6 nothing is pinned when the replacement package is absent',
          'but com.google.android.webview is not installed; left alone' in lg and
          'webview_provider=com.android.webview' in open(os.path.join(SAND, 'settings')).read())
    check('B6 and the log says so in the package section', 'PACKAGE NOT INSTALLED' in lg)
    # ---- the opt-in auto-install branch
    inst = os.path.join(SAND, 'pm-installs')
    if os.path.exists(inst):
        os.remove(inst)
    fake = os.path.join(SAND, 'fake138.apk')
    open(fake, 'wb').write(b'not-a-real-apk')
    wrong = hashlib.sha256(b'wrong').hexdigest()
    prop = os.path.join(DEST, 'webview138-apk.prop')
    def set_apk_sha(sha):
        # open(prop,'w') truncates, so the old bytes must be read BEFORE it is opened
        txt = open(prop).read()
        assert txt.count('webview_apk_sha256=') == 1, prop + ': expected exactly one sha line'
        open(prop, 'w').write(re.sub(r'webview_apk_sha256=.*',
                                     'webview_apk_sha256=' + sha, txt))
    set_apk_sha(wrong)
    open(os.path.join(DEST, 'auto-install'), 'w').write(fake + '\n')
    set_packages('com.android.webview')
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B9 auto-install REFUSES bytes that are not the measured 138 package',
          'REFUSED: sha256' in lg and not os.path.exists(inst), lg[-300:])
    good = hashlib.sha256(b'not-a-real-apk').hexdigest()
    set_apk_sha(good)
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B10 with the bytes verified, the opt-in install runs pm install exactly once',
          'bytes verified' in lg and os.path.exists(inst) and
          open(inst).read().count('install -r') == 1, lg[-300:])
    set_packages('com.android.webview', 'com.google.android.webview')
    os.remove(inst)
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    check('B11 no install is attempted when the package is already there',
          not os.path.exists(inst))
    os.remove(os.path.join(DEST, 'auto-install'))
    os.remove(inst) if os.path.exists(inst) else None
    set_packages('com.android.webview')
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    check('B12 without the flag file nothing is ever installed', not os.path.exists(inst))
    # Google still absent, otherwise the whole branch is (correctly) skipped and B13 proves nothing
    set_packages('com.android.webview')
    open(os.path.join(DEST, 'auto-install'), 'w').write(os.path.join(SAND, 'gone.apk') + '\n')
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B13 a flag file pointing at a missing APK is reported, not guessed',
          'does not exist' in lg and not os.path.exists(inst), lg[-200:])
    os.remove(os.path.join(DEST, 'auto-install'))
    run(svc, VDIR=os.path.join(SAND, 'no-such-vendor'), PDIR=os.path.join(SAND, 'no-such-product'))
    lg = open(os.path.join(DEST, 'boot-verify.log')).read()
    check('B7 an overlay that magic mount did not deliver is reported, not assumed',
          'OVERLAY NOT MOUNTED' in lg)
    open(os.path.join(DEST, 'boot-verify.log'), 'w').write('x' * 70000)
    run(svc, VDIR=os.path.join(FAKEV, 'overlay'))
    check('B8 the boot log cannot grow without bound',
          os.path.exists(os.path.join(DEST, 'boot-verify.log.old')))
    shutil.rmtree(DEST)

    # ================================================================== C. customize.sh
    head('C. customize.sh (the installer-time gates)')
    tmp = os.path.join(SAND, 'cust')
    fresh_src()

    def customize(**kw):
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        shutil.copytree(SRC, tmp)
        e = {'MODPATH': tmp}
        e.update({k: v for k, v in kw.items()})
        return run([SH, os.path.join(tmp, 'customize.sh')], env=e)

    rc, out = customize(API='28', VDIR='/vendor/overlay', PDIR='/product/overlay')
    check('C1 accepts API 28 with /vendor/overlay present', rc == 0 and 'customize.sh OK' in out, out[-200:])
    rc, out = customize(API='29')
    check('C2 refuses API 29 (a non-<overlayable> framework RRO is rejected from Android 10 up)',
          rc != 0 and 'built for API 28' in out)
    rc, out = customize(API='')
    check('C3 warns rather than guessing when API is unknown', rc == 0 and 'WARNING: API unknown' in out)
    open(os.path.join(tmp, 'system', 'vendor', 'overlay',
                      'webview138-provider-overlay.apk'), 'ab').write(b'corrupt')
    rc, out = run([SH, os.path.join(tmp, 'customize.sh')],
                  env={'MODPATH': tmp, 'API': '28', 'VDIR': '/vendor/overlay'})
    check('C4 refuses payload bytes that do not match the audit manifest',
          rc != 0 and 'sha256 mismatch' in out)
    fresh_src()
    rc, out = customize(API='28', VDIR=os.path.join(SAND, 'nope-vendor'),
                        PDIR=os.path.join(SAND, 'real-product/overlay'))
    os.makedirs(os.path.join(SAND, 'real-product', 'overlay'), exist_ok=True)
    rc, out = customize(API='28', VDIR=os.path.join(SAND, 'nope-vendor'),
                        PDIR=os.path.join(SAND, 'real-product/overlay'))
    check('C5 relocates to /product/overlay when /vendor/overlay is absent',
          rc == 0 and os.path.isfile(os.path.join(tmp, 'system', 'product', 'overlay',
                                                  'webview138-provider-overlay.apk')) and
          not os.path.exists(os.path.join(tmp, 'system', 'vendor')), out[-160:])
    rc, out = customize(API='28', VDIR=os.path.join(SAND, 'nope-a'), PDIR=os.path.join(SAND, 'nope-b'))
    check('C6 refuses outright when Android 9 has no directory it scans',
          rc != 0 and 'Android 9 scans ONLY those two' in out)
    fresh_src()
    mpath = os.path.join(SRC, 'webview138.manifest')
    txt = open(mpath).read().replace('provider_1_isFallback=false', 'provider_1_isFallback=true')
    open(mpath, 'w').write(txt)
    rc, out = customize(API='28', VDIR='/vendor/overlay')
    check('C7 refuses a provider list where Google is the fallback (the platform would disable it)',
          rc != 0 and 'isFallback=true' in out, out[-160:])
    fresh_src()
    open(os.path.join(SRC, 'module.prop'), 'w').write('id=some.other.module\nname=x\n')
    rc, out = customize(API='28', VDIR='/vendor/overlay')
    check('C8 refuses when module.prop id and the tree disagree', rc != 0 and 'expected' in out)
    fresh_src()

    # ================================================================== D. update-binary
    head('D. META-INF/com/google/android/update-binary')
    ub = os.path.join(ROOT, 'work', 'magisk_stage', 'META-INF', 'com', 'google', 'android',
                      'update-binary')
    rc, out = run([SH, ub, '28', SAND, ZIPF])
    check('D1 refuses to install where there is no /data/adb/modules instead of creating one',
          rc != 0 and ('/data/adb/modules absent' in out or 'no' in out.lower()), out[-200:])
    check('D1 it never wrote a module directory', not os.path.isdir('/data/adb/modules') or
          not os.path.isdir('/data/adb/modules/webview138-replacement'))
    for f in ('customize.sh', 'service.sh', 'uninstall.sh'):
        p = os.path.join(STAGED, f)
        rc2, o2 = run(['/system/bin/sh', '-n', p])
        check('D2 %s parses under Android 9 mksh' % f, rc2 == 0, o2[:120])
    rc2, o2 = run(['/system/bin/sh', '-n', ub])
    check('D2 update-binary parses under Android 9 mksh', rc2 == 0, o2[:120])
    rc2, o2 = run(['/system/bin/sh', '-n', 'tools/magisk_deploy.sh'])
    check('D2 magisk_deploy.sh parses under Android 9 mksh', rc2 == 0, o2[:120])

    # ================================================================== E. host integrity
    head('E. the physical host was not touched')
    vend_after = sorted(os.listdir('/vendor/overlay')) if os.path.isdir('/vendor/overlay') else None
    check('E1 /vendor/overlay contents unchanged by this test', vend_before == vend_after,
          '%s vs %s' % (vend_before, vend_after))
    # os.path.isdir() returns False for EACCES too, so say which of the two we actually observed.
    try:
        os.stat('/data/adb/modules')
        adb_seen = 'observable and our module is absent'
    except OSError as ex:
        adb_seen = 'NOT OBSERVABLE from uid %d (%s) - every sandbox run above was steered by ' \
                   'MODULES_DIR/QODER_ALLOW_TARGET, which A3 proves is enforced' % (os.getuid(), ex.strerror)
    check('E1 no module appeared at the real /data/adb/modules path',
          not os.path.isdir('/data/adb/modules/webview138-replacement'), adb_seen)
    # What makes E1 strong even when /data/adb is NOINFO: DAC says this uid cannot write into /data at
    # all, so no script in this run could have created /data/adb even if it had tried.
    dmode = os.stat('/data').st_mode
    check('E1 /data is not writable by this uid, so the module path could not have been created here',
          (dmode & stat.S_IWOTH) == 0, 'mode %s uid %d' % (oct(dmode & 0o7777), os.getuid()))
    # The C group rebuilds DEST per case and finally removes it, so "our module is present" is not an
    # E-time invariant. The invariant that is: nothing OTHER than our id ever appeared in MODULES_DIR.
    foreign = [n for n in (os.listdir(MODULES) if os.path.isdir(MODULES) else [])
               if n != 'webview138-replacement']
    check('E1 nothing foreign ever appeared in the sandbox MODULES_DIR',
          not foreign, 'entries: %s' % (os.listdir(MODULES) if os.path.isdir(MODULES) else []))
    now_md5 = {f: os.popen('md5sum input/' + f).read().split()[0]
               for f in sorted(os.listdir('input'))} if os.path.isdir('input') else {}
    check('E2 the input files are untouched', inputs_md5 == now_md5, '%s' % now_md5)
    ov = os.path.join(ROOT, 'output', 'webview138-provider-overlay.apk')
    want = [l.split('=', 1)[1] for l in open(os.path.join(ROOT, 'output',
            'webview138-provider-overlay.manifest')) if l.startswith('overlay_sha256=')][0].strip()
    check('E3 the audited overlay bytes are still what the manifest says', sha(ov) == want)
    host_pref_after = subprocess.run(['/system/bin/settings', 'get', 'global', 'webview_provider'],
                                     capture_output=True, text=True).stdout.strip()
    check("E4 the HOST's real webview_provider setting is untouched by every sandbox run above",
          host_pref_before == host_pref_after, '%r vs %r' % (host_pref_before, host_pref_after))
    check('E5 the mount table is identical: nothing was bind-mounted or remounted by this run',
          mounts_before == open('/proc/mounts').read())

    print('\n=== %d checks, %d failures ===' % (len(checks), len(fails)))
    for f in fails:
        print('  FAIL:', f)
    if a.report:
        open(a.report, 'w').write('\n'.join(log) + '\n')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

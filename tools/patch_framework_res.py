#!/usr/bin/env python3
"""Inspect or patch res/xml/config_webview_packages.xml inside a framework-res.apk.

Subcommands
  inspect <apk>
      Read-only. Prints the provider entries exactly as Android 9's SystemImpl will parse them,
      and every X.509 certificate in the APK Signing Block with SHA-1/SHA-256, so the result can be
      compared against the AOSP public test key. This is what decides whether a patched
      framework-res could legitimately be re-signed.

  patch <apk> <out.apk> [--cert DER]
      Writes a copy with a com.google.android.webview <webviewprovider> inserted FIRST (Android 9
      walks the list in document order, WebViewUpdater.java:261-277, so first = default). Only that
      one entry changes; every other ZIP entry is copied with its original compression. The output
      is DELIBERATELY LEFT UNSIGNED and says so. Run "inspect" on the input before believing the
      output is usable at all.

Why the re-sign step is not automatable here:
  framework-res declares android:sharedUserId="android.uid.system"
  (frameworks/base/core/res/AndroidManifest.xml:21). PackageManagerService.java:10285-10313 shows
  that a system package whose signature changed is "recovered" - but the new cert is then adopted
  for the whole shared user, and every other android.uid.system package scanned afterwards must
  match it or PMS throws INSTALL_PARSE_FAILED_INCONSISTENT_CERTIFICATES. Re-signing with a foreign
  key therefore does not yield a tweaked framework-res, it yields a system whose Settings, SystemUI
  and friends fail to register. Same key, or nothing.

  This is also why the primary plan is the static RRO under rro/, which needs neither this file nor
  this key.
"""
import sys, os, zipfile, struct, hashlib, base64

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axml import AXML, u32, RES_XML_START_ELEMENT, RES_XML_END_ELEMENT, RES_XML_CDATA

XML_PATH = 'res/xml/config_webview_packages.xml'
GOOGLE_PKG = 'com.google.android.webview'
AOSP_TEST_SHA1 = '27196E386B875E76ADF700E7EA84E4C6EEE33DFA'
AOSP_TEST_SHA256 = 'C8A2E9BCCF597C2FB6DC66BEE293FC13F2FC47EC77BC6B2B0D52C11F51192AB8'
V2, V3 = 0x7109871a, 0xf05368c0


def providers(ax):
    return [dict(a) for kind, tag, a in ax.dump() if kind == 'start' and tag == 'webviewprovider']


# ---------------------------------------------------------------- APK Signing Block
# Same primitives as work/verify_sig.py, which cryptographically verified a v2 signature over these
# exact structures on input/webview138.apk. Little-endian [u32 length][payload] sequences.
def signing_block_pairs(path):
    raw = open(path, 'rb').read()
    at = raw.rfind(b'PK\x05\x06')
    if at < 0 or len(raw) - at < 22:
        raise ValueError('no end-of-central-directory: not a plain (non-zip64) zip')
    cd = struct.unpack_from('<I', raw, at + 16)[0]
    if cd < 24 or raw[cd - 16:cd] != b'APK Sig Block 42':
        return None
    size = struct.unpack_from('<Q', raw, cd - 24)[0]
    pairs, p, end = {}, cd - 8 - size + 8, cd - 24
    while p + 8 <= end:
        ps = struct.unpack_from('<Q', raw, p)[0]
        if ps < 4:
            break
        pairs[int.from_bytes(raw[p + 8:p + 12], 'little')] = raw[p + 12:p + 8 + ps]
        p += 8 + ps
    return pairs


def node(b):
    return b[4:4 + struct.unpack_from('<I', b, 0)[0]]


def children(b):
    """Items of a length-prefixed sequence. b is either one [u32 len] record (a sequence) or a
    bare run of records (the outermost pair payload); the test is whether the leading length
    exactly describes the rest of the buffer."""
    body = node(b) if struct.unpack_from('<I', b, 0)[0] == len(b) - 4 else b
    out, o = [], 0
    while o + 4 <= len(body):
        cl = struct.unpack_from('<I', body, o)[0]
        if cl == 0 or o + 4 + cl > len(body):
            break
        out.append(body[o:o + 4 + cl])
        o += 4 + cl
    return out


def certs_in_pair(pair_bytes):
    """signers -> signer -> signedData -> certificates -> [u32 len] DER, per the v2/v3 layout."""
    out = []
    for signer in children(pair_bytes):
        parts = children(signer)
        if not parts:
            continue
        for item in children(parts[0]):
            for maybe in children(item):
                d = node(maybe)
                if d[:1] == b'\x30':
                    out.append(d)
    return out


def report_certs(path):
    try:
        pairs = signing_block_pairs(path)
    except ValueError as e:
        print('APK Signing Block: unreadable (%s)' % e)
        return
    if pairs is None:
        print('APK Signing Block: ABSENT -> v1/JAR signing only, typical of AOSP-built system APKs')
        return
    print('APK Signing Block pairs: %s' % ', '.join('0x%08x' % k for k in sorted(pairs)))
    found = 0
    for pid in (V2, V3):
        if pid not in pairs:
            continue
        scheme = 'v2' if pid == V2 else 'v3'
        for der in certs_in_pair(pairs[pid]):
            found += 1
            s1, s256 = hashlib.sha1(der).hexdigest().upper(), hashlib.sha256(der).hexdigest().upper()
            print('  %s certificate: %d B' % (scheme, len(der)))
            print('     SHA-1   %s' % s1)
            print('     SHA-256 %s' % s256)
            print('     == AOSP public test "platform" key?  %s'
                  % ('YES -> re-signing is legitimate and doable with the published AOSP key'
                     if s256 == AOSP_TEST_SHA256 or s1 == AOSP_TEST_SHA1
                     else 'no -> the ROM build key is required and is not in the ROM package'))
    if not found:
        print('  NO CERTIFICATE PARSED from the signing block: the inner layout was not the expected '
              'v2/v3 one. Nothing may be inferred about this APK signer from this line.')


def provider_texts(ax):
    """[(provider_index, base64_text)] for every <signature> child of a <webviewprovider>.

    This mirrors SystemImpl.java:168-181 - readSignatures() walks the children of the current
    provider and takes parser.nextText(), i.e. the AXML CDATA chunk (RES_XML_CDATA 0x0104) whose
    payload is a ResStringPool_ref, NOT an attribute. Depth 1 = <webviewproviders>, 2 =
    <webviewprovider>, 3 = <signature>."""
    out, cur, depth = [], -1, 0
    for typ, o, size in ax.chunks:
        if typ == RES_XML_START_ELEMENT:
            depth += 1
            if depth == 2 and ax.strings[u32(ax.b, o + 20)] == 'webviewprovider':
                cur += 1
        elif typ == RES_XML_END_ELEMENT:
            depth -= 1
        elif typ == RES_XML_CDATA and depth >= 3:
            out.append((cur, ax.strings[u32(ax.b, o + 16)]))
    return out


def cmd_inspect(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    print('%s: %d entries' % (os.path.basename(path), len(names)))
    if XML_PATH not in names:
        near = [n for n in names if 'webview' in n.lower()]
        print('  %s NOT present. Entries mentioning "webview": %s' % (XML_PATH, near or 'none'))
        print('  -> not a framework-res.apk, or it names that resource differently.')
        report_certs(path)
        return 3
    ax = AXML(z.read(XML_PATH))
    print('root element: <%s>' % ax.dump()[0][1])
    pr = providers(ax)
    print('%d provider entr%s, as SystemImpl.java will parse them:'
          % (len(pr), 'y' if len(pr) == 1 else 'ies'))
    by_idx = {}
    for idx, txt in provider_texts(ax):
        by_idx.setdefault(idx, []).append(txt)
    for i, p in enumerate(pr):
        sig = p.get('signature')
        print('   packageName=%-28s availableByDefault=%-6s isFallback=%-6s description=%r'
              % (p.get('packageName'), p.get('availableByDefault'), p.get('isFallback'),
                 p.get('description')))
        if sig:
            print('   WARNING: a signature= ATTRIBUTE is present (%d chars). Android 9 does NOT '
                  'read it: SystemImpl takes parser.nextText() from a <signature> CHILD ELEMENT.'
                  % len(sig))
        for txt in by_idx.get(i, ()):
            try:
                d = base64.b64decode(txt)
                print('   <signature> text: %d base64 chars -> %d B DER, SHA-1 %s'
                      % (len(txt), len(d), hashlib.sha1(d).hexdigest().upper()))
            except Exception as e:
                print('   <signature> text: %d chars but NOT decodable as base64 (%s) -> '
                      'WebViewProviderInfo would build a garbage Signature' % (len(txt), e))
        if not by_idx.get(i) and not sig:
            print('   signature: ABSENT (-> isSystemApp() branch, WebViewUpdater.java:512)')
    report_certs(path)
    v1 = [n for n in names if n.startswith('META-INF/') and n.endswith(('.RSA', '.DSA', '.EC'))]
    print('v1 signature files: %s' % (v1 or 'none'))
    return 0


def cmd_patch(path, out, cert_path):
    z = zipfile.ZipFile(path)
    if XML_PATH not in z.namelist():
        print('REFUSING: %s not present; this is not a framework-res.apk' % XML_PATH)
        return 3
    ax = AXML(z.read(XML_PATH))
    root = ax.dump()[0][1]
    if root != 'webviewproviders':
        print('REFUSING: root element is <%s>, expected <webviewproviders>' % root)
        return 3
    existing = [p.get('packageName') for p in providers(ax)]
    print('current providers: %s' % existing)
    if GOOGLE_PKG in existing:
        print('%s is already registered; nothing to do.' % GOOGLE_PKG)
        return 0

    b64 = der = None
    if cert_path:
        der = open(cert_path, 'rb').read()
        if der[:1] != b'\x30':
            print('REFUSING: %s does not start with a DER SEQUENCE (first byte 0x%02x); not '
                  'writing a garbage <signature> value.' % (cert_path, der[0]))
            return 3
        b64 = base64.b64encode(der).decode()
        print('embedding certificate %s: %d B DER -> %d base64 chars, SHA-1 %s'
              % (os.path.basename(cert_path), len(der), len(b64),
                 hashlib.sha1(der).hexdigest().upper()))
    else:
        print('no --cert given: the entry carries NO <signature>, so per WebViewUpdater.java:506-521 '
              'the provider APK must present as a system app (FLAG_SYSTEM) to pass that gate.')

    # Android 9 reads ONLY these four as attributes; the certificate is element TEXT
    # (SystemImpl.java:168-181 readSignatures() -> parser.nextText()). Writing signature= as an
    # attribute would be silently ignored and the provider would fail its signature gate.
    attrs = [('description', 'Google WebView'), ('packageName', GOOGLE_PKG),
             ('availableByDefault', 'true')]
    old_xml = z.read(XML_PATH)
    ax.insert_as_first_child('webviewprovider', attrs, root, text=b64)
    new_xml = ax.serialise()

    chk = AXML(new_xml)
    after = [p.get('packageName') for p in providers(chk)]
    print('patched providers: %s' % after)
    assert GOOGLE_PKG in after and len(after) == len(existing) + 1, 'self-check: not exactly +1'
    assert chk.dump()[0][1] == root, 'self-check: root element changed'
    assert len([t for k, t, a in chk.dump() if k in ('start', 'end')]) % 2 == 0, \
        'self-check: unbalanced document'
    if b64:
        txt = chk.text_values()
        assert txt and base64.b64decode(txt[0]) == der, \
            'self-check: <signature> element text did not round-trip to the input DER'

    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for info in z.infolist():
            is_target = info.filename == XML_PATH
            data = new_xml if is_target else z.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.external_attr = info.external_attr
            # AssetManager mmaps binary XML; keep the one patched entry STORED
            zi.compress_type = zipfile.ZIP_STORED if is_target else info.compress_type
            zo.writestr(zi, data)
    print('wrote %s (%d B total; %s %d -> %d B; %d other entries copied unchanged)'
          % (out, os.path.getsize(out), XML_PATH, len(old_xml), len(new_xml),
             len(z.infolist()) - 1))
    print("""
STOP. %s is NOT installable as it stands, and this script did not sign it.
  * The original signature no longer covers the changed entry, so PackageManager rejects the file
    or takes the signature-changed recovery path at PackageManagerService.java:10285 and then fails
    every other android.uid.system package against the new certificate.
  * It must be re-signed with THE SAME CERTIFICATE THAT SIGNED THE INPUT. Run "inspect" on the
    input first: only if its SHA-256 equals
      %s
    (AOSP public test "platform" key) is re-signing legitimate and doable here.
  * No key or certificate was generated by this script. Nothing was invented or substituted.
  * The preferred route needs neither this file nor this key: see rro/build.sh (static RRO, no
    framework-res edit, no platform key). Verified against Android 9 sources only - never run at
    runtime in this environment.
""" % (os.path.basename(out), AOSP_TEST_SHA256))
    return 0


def main(a):
    if len(a) < 3:
        print(__doc__)
        return 2
    if a[1] == 'inspect':
        return cmd_inspect(a[2])
    if a[1] == 'patch':
        if len(a) < 4:
            print('patch needs <out.apk>')
            return 2
        rest, cert = a[4:], None
        if '--cert' in rest:
            cert = rest[rest.index('--cert') + 1]
        return cmd_patch(a[2], a[3], cert)
    print('unknown subcommand %s' % a[1])
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))

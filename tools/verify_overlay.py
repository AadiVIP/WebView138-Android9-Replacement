#!/usr/bin/env python3
"""Independently audit the built overlay APK with a fresh parser, not the builder's own asserts.

    python3 tools/verify_overlay.py output/webview138-provider-overlay.apk \
            --cert work/V2_cert.der [--apk input/webview138_arm64_universal_138.0.7204.179.apk ...]

Why this file exists separately from build_overlay.py: build_overlay.py asserts while it writes, so
its checks share the builder's assumptions. This re-reads the finished bytes from disk and checks
them the way the platform will, using the SAME SystemImpl-faithful walk that
tools/patch_framework_res.py uses (attributes for the four known names, <signature> element TEXT for
the certificate). If the two ever disagree, that disagreement is itself the finding.

The optional --apk arguments extract the X.509 DER actually stored in each APK's APK Signing Block
(v2 0x7109871a / v3 0xf05368c0) and compare it, byte for byte, to the certificate the overlay embeds.
That is the check that matters: config_webview_packages.xml is only honoured when the installed
package's signer matches the <signature> text (WebViewUpdater.java:506-521).
"""
import sys, os, re, zipfile, struct, argparse, base64, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arsc
from axml import (AXML, RES_XML, RES_STRING_POOL, RES_XML_START_ELEMENT, RES_XML_END_ELEMENT,
                  RES_XML_CDATA, RES_XML_RESOURCE_MAP, u16, u32)

NEEDED = ['resources.arsc', 'AndroidManifest.xml', 'res/xml/config_webview_packages.xml']
XML_ENTRY = 'config_webview_packages'


# ------------------------------------------------------------------ signing block
def signing_pairs(path):
    raw = open(path, 'rb').read()
    at = raw.rfind(b'PK\x05\x06')
    if at < 0:
        return None
    cd = struct.unpack_from('<I', raw, at + 16)[0]
    if cd < 24 or raw[cd - 16:cd] != b'APK Sig Block 42':
        return None
    size = struct.unpack_from('<Q', raw, cd - 24)[0]
    p, end, out = cd - 8 - size + 8, cd - 24, {}
    while p + 8 <= end:
        ps = struct.unpack_from('<Q', raw, p)[0]
        out[int.from_bytes(raw[p + 8:p + 12], 'little')] = raw[p + 12:p + 8 + ps]
        p += 8 + ps
    return out


def der_span(b, o):
    """Total byte length of the DER element starting at b[o], or 0 if it is not a valid SEQUENCE."""
    if o + 2 > len(b) or b[o] != 0x30:
        return 0
    l0 = b[o + 1]
    if l0 < 0x80:
        return 2 + l0
    nbytes = l0 & 0x7F
    if nbytes > 4 or o + 2 + nbytes > len(b):
        return 0
    return 2 + nbytes + int.from_bytes(b[o + 2:o + 2 + nbytes], 'big')


def embedded_certs(path):
    """(blockId, DER) for every X.509 certificate inside a v2/v3 signer's signedData.

    signedData stores the content-digest sequence BEFORE the certificate sequence, so the cert is not
    at a fixed offset; locate each length-prefixed DER by its ASN.1 span rather than assuming a field
    order. (Empirically the WebView cert sits at offset 68 of the pair, i.e. 56 into signedData.)
    """
    pairs = signing_pairs(path)
    if pairs is None:
        return None
    found = []

    def seq(b):
        body = b[4:4 + u32(b, 0)]
        items, o = [], 0
        while o + 4 <= len(body):
            l = struct.unpack_from('<I', body, o)[0]
            if l == 0 or o + 4 + l > len(body):
                break
            items.append(body[o:o + 4 + l]); o += 4 + l
        return items

    def scan(body, pid):
        for o in range(4, len(body)):
            span = der_span(body, o)
            if span and span == struct.unpack_from('<I', body, o - 4)[0] \
                    and o + span <= len(body):
                found.append((pid, body[o:o + span]))

    for pid in (0x7109871a, 0xf05368c0):
        if pid not in pairs:
            continue
        for signer in seq(pairs[pid]):
            parts = seq(signer)
            if parts:
                scan(parts[0][4:], pid)          # signedData content
    return found


# ------------------------------------------------------------------ axml structure
def axml_layout(b):
    """Recompute the file's chunk tree from scratch: header, pool, then top-level chunks."""
    typ, hdr, size = u16(b, 0), u16(b, 2), u32(b, 4)
    assert typ == RES_XML, 'not a RES_XML document (0x%04x)' % typ
    pool_type, pool_hdr, pool_size = u16(b, hdr), u16(b, hdr + 2), u32(b, hdr + 4)
    assert pool_type == RES_STRING_POOL, 'no string pool after header'
    o = hdr + pool_size
    top = []
    while o + 8 <= size:
        t, h, s = u16(b, o), u16(b, o + 2), u32(b, o + 4)
        if t == 0 or s < 8:
            break
        top.append((t, o, s))
        o += s
    return dict(total=size, hdr=hdr, pool=pool_size, top=top, reach=o)


# ------------------------------------------------------------------ SystemImpl walk
def systemimpl_providers(b):
    """AXML.webview_providers is the single reader, shared with build_overlay.py: attributes for the
    four names SystemImpl reads, <signature> element TEXT for the certificate."""
    ax = AXML(b)
    return ax, ax.webview_providers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('apk')
    ap.add_argument('--cert', default='work/V2_cert.der')
    ap.add_argument('--package', default=None, help='expected overlay package name')
    ap.add_argument('--base-xml', help='the guest OWN res/xml/config_webview_packages.xml (AXML) to '
                                       'diff the overlay against, proving no provider was dropped')
    ap.add_argument('--apk', dest='guest', action='append', default=[],
                    help='APK(s) whose embedded cert must equal the overlay cert')
    ap.add_argument('--write-manifest', metavar='PATH', default=None,
                    help='emit a key=value delivery manifest for tools/install_overlay.sh. Only '
                         'written when EVERY check passed, so the manifest cannot vouch for a bad '
                         'build; the installer then checks the on-device file byte-for-byte against it')
    a = ap.parse_args()

    der = open(a.cert, 'rb').read()
    b64 = base64.b64encode(der).decode()
    checks, fails = [], []

    def check(name, ok, detail=''):
        checks.append(name)
        if not ok:
            fails.append('%s  %s' % (name, detail))
        print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name, ('  - ' + detail) if detail else ''))

    z = zipfile.ZipFile(a.apk)
    print('=== %s ===' % os.path.basename(a.apk))

    # ---- 1. entry set, compression, alignment
    names = z.namelist()
    check('all three required entries present', all(n in names for n in NEEDED), str(names))
    info = {i.filename: i for i in z.infolist()}
    ra = info['resources.arsc']
    check('resources.arsc is STORED (AssetManager must mmap it, cannot be deflated)',
          ra.compress_type == zipfile.ZIP_STORED, 'compress_type=%d' % ra.compress_type)
    # raw data offset = local-header-start + 30 + len(name) + len(extra)
    data_off = ra.header_offset + 30 + len(ra.filename.encode()) + len(ra.extra or b'')
    check('resources.arsc data 4-byte aligned for mmap', data_off % 4 == 0,
          'data_off=%d (%%4=%d)' % (data_off, data_off % 4))
    # CRC integrity (z.read verifies and raises on mismatch)
    try:
        z.read('resources.arsc'); ok = True
    except Exception as e:
        ok = False; print('     crc error:', e)
    check('resources.arsc CRC/deflate integrity', ok)

    # ---- 2. manifest structure + <overlay> rules
    mb = z.read('AndroidManifest.xml')
    lay = axml_layout(mb)
    check('AndroidManifest.xml chunk tree sums to file size',
          lay['total'] == len(mb) and lay['reach'] == lay['total'],
          'declared=%d len=%d reach=%d' % (lay['total'], len(mb), lay['reach']))
    max_ = AXML(mb)
    els = {t: dict(av) for k, t, av in max_.dump() if k == 'start'}
    ov = els.get('overlay', {})
    check('<overlay> present', 'overlay' in els)
    check('overlay targetPackage == android (matches package `android` by name)',
          ov.get('targetPackage') == 'android', repr(ov.get('targetPackage')))
    check('overlay isStatic == true (PackageParser defaults it false; must be explicit)',
          ov.get('isStatic') == 'true', repr(ov.get('isStatic')))
    pr = ov.get('priority', '0')
    check('overlay priority in 0..9999 (PackageParser.java:2077-2094)',
          str(pr).isdigit() and 0 <= int(pr) <= 9999, repr(pr))
    if a.package:
        check('manifest package == %s' % a.package, els['manifest'].get('package') == a.package,
              repr(els['manifest'].get('package')))

    # ---- 3. resources.arsc resolves the same-named framework entry
    ar = arsc.ARSC(z.read('resources.arsc'))
    hits = ar.find('xml', XML_ENTRY)
    check('arsc has an xml/%s entry' % XML_ENTRY, bool(hits))
    if hits:
        ent = hits[0][3]
        val = ent['value']
        check('arsc value points at the file we actually shipped',
              val == "STRING %r" % ('res/xml/%s.xml' % XML_ENTRY),
              '%r; must name the res/ path AND that path must be a real entry: %s'
              % (val, ('res/xml/%s.xml' % XML_ENTRY) in names))
        check('entry lives in the overlay package (0x7f), type xml',
              hits[0][2] >> 24 == 0x7f, '0x%08x' % hits[0][2])

    # ---- 4. the provider list, read the way SystemImpl will
    pb = z.read('res/xml/%s.xml' % XML_ENTRY)
    plax, provs = systemimpl_providers(pb)
    lay2 = axml_layout(pb)
    check('config_webview_packages.xml chunk tree sums to file size',
          lay2['total'] == len(pb) and lay2['reach'] == lay2['total'],
          'declared=%d len=%d reach=%d' % (lay2['total'], len(pb), lay2['reach']))
    order = [p['packageName'] for p in provs]
    check('Google WebView is FIRST in document order (WebViewUpdater picks the first '
          'availableByDefault installed provider)', order and order[0] == 'com.google.android.webview',
          str(order))
    if a.base_xml:
        check('some provider OTHER than Google is still availableByDefault (the guest is never left '
              'without a WebView if 138 disappears)',
              any(p['availableByDefault'] and p['packageName'] != 'com.google.android.webview'
                  for p in provs), str(order))
    else:
        check('factory com.android.webview still present (never leaves guest without a WebView)',
              'com.android.webview' in order, str(order))
    check('every provider has packageName AND description (SystemImpl.java:95-104 throws '
          'AndroidRuntimeException otherwise)',
          all(p['packageName'] and p['description'] for p in provs))
    check('>=1 provider availableByDefault AND NOT isFallback (SystemImpl.java:141-144 throws '
          'AndroidRuntimeException otherwise)',
          sum(1 for p in provs if p['availableByDefault'] and not p['isFallback']) >= 1)
    check('every isFallback=true provider is also availableByDefault (SystemImpl.java:113-116)',
          all(p['availableByDefault'] for p in provs if p['isFallback']))
    check('<=1 isFallback provider (SystemImpl.java:117-120)',
          sum(1 for p in provs if p['isFallback']) <= 1)
    check('no provider has a child element other than <signature> (SystemImpl.java:177-179 logs '
          '"Found an element in a webview provider that is not a signature" and skips it)',
          all(not p['bad_children'] for p in provs),
          str([p['bad_children'] for p in provs]))
    check('no provider relies on a signature= ATTRIBUTE (Android 9 never reads that attribute; '
          'see the corrected form in reports/proposed_webviewprovider_entry.xml)',
          all('signature' not in [n for n in p] for p in provs))

    g = provs[0]
    check('Google provider has <signature> element TEXT (not bare CDATA, not an attribute)',
          len(g['signatures']) == 1,
          'signatures=%d. With 0 signatures WebViewUpdater.providerHasValidSignature falls back to '
          'applicationInfo.isSystemApp() (WebViewUpdater.java:506-521), which a user-install into '
          '/data does NOT satisfy' % len(g['signatures']))
    if g['signatures']:
        text = g['signatures'][0]
        got = base64.b64decode(text)
        check('signature text base64-decodes to the real Google DER, byte for byte',
              got == der, 'decoded %d B sha1=%s, expected sha1=%s'
              % (len(got), hashlib.sha1(got).hexdigest().upper(),
                 hashlib.sha1(der).hexdigest().upper()))
        # WebViewProviderInfo.java:42 -> Base64.decode(text, Base64.DEFAULT). Single-line canonical
        # avoids any dependence on how the decoder treats embedded newlines.
        check('signature text is single-line canonical base64, no whitespace',
              not re.search(r'\s', text), 'length=%d' % len(text))

    # ---- 5. diff against the guest's own provider list, if one was supplied
    if a.base_xml:
        bax = AXML(open(a.base_xml, 'rb').read())
        base = bax.webview_providers()
        goog = 'com.google.android.webview'
        base_set = set(p['packageName'] for p in base)
        out_set = set(p['packageName'] for p in provs)
        dropped = sorted(base_set - out_set)
        added = sorted(out_set - base_set)
        # A base provider must never be dropped; the ONLY package the overlay may add is Google, and
        # only when the guest file did not already list it. (The old set-equality check assumed the
        # base always named Google, which wrongly rejected a guest whose single provider is
        # com.android.webview.)
        check('overlay keeps EVERY provider from %s (dropped: %s)'
              % (os.path.basename(a.base_xml), dropped or 'none'), not dropped, 'dropped=%s' % dropped)
        check('the only provider the overlay may add is Google (added: %s)' % (added or 'none'),
              set(added) <= {goog}, 'added=%s' % added)
        expected = len(base) + (0 if goog in base_set else 1)
        check('provider count is base + Google-if-absent (%d -> %d, expected %d)'
              % (len(base), len(provs), expected), len(provs) == expected)
        for b in base:
            if b['packageName'] == 'com.google.android.webview':
                continue
            m = next((p for p in provs if p['packageName'] == b['packageName']), None)
            if m is None:
                check('provider %s present' % b['packageName'], False)
                continue
            same = (m['description'] == b['description']
                    and m['availableByDefault'] == b['availableByDefault']
                    and m['isFallback'] == b['isFallback']
                    and m['signatures'] == b['signatures'])
            check('provider %s carried verbatim' % b['packageName'], same,
                  'base=%r overlay=%r' % (b, m) if not same else '')
        gbase = next((p for p in base if p['packageName'] == 'com.google.android.webview'), None)
        changed = ['position -> first', 'availableByDefault -> true', 'isFallback -> false',
                   '<signature> -> the Google DER']
        if gbase is None:
            check('base did not list Google, so it was ADDED (nothing removed)', True,
                  'changes: %s' % ', '.join(changed))
        else:
            diff = []
            if not gbase['availableByDefault']: diff.append('availableByDefault')
            if gbase['isFallback']: diff.append('isFallback')
            if gbase['signatures'] != [b64]: diff.append('<signature> text')
            check('Google entry keeps its own description from the base (not overwritten)',
                  gbase['description'] == provs[0]['description'],
                  'base=%r overlay=%r' % (gbase['description'], provs[0]['description']))
            check('Google was normalised only where it needed to be',
                  diff in ([], ['<signature> text'], ['isFallback', '<signature> text'],
                           ['isFallback'], ['availableByDefault', 'isFallback', '<signature> text'],
                           ['availableByDefault', '<signature> text']),
                  'normalised: %s' % (diff or 'nothing (already correct)'))
            check('Google is NOT flagged isFallback in the overlay',
                  not provs[0]['isFallback'],
                  'fallback logic is ON by default (SystemImpl.java:212-216) and the platform '
                  'DISABLES the fallback provider once a valid non-fallback one exists '
                  '(WebViewUpdateServiceImpl.java:202-220 -> SystemImpl.java:225-235)')
        others = [p['packageName'] for p in base if p['packageName'] != 'com.google.android.webview'
                  and p['isFallback']]
        print('  providers the base flags isFallback (platform may disable them once 138 is valid):'
              ' %s' % (others or 'none'))

    # ---- 6. cross-check against the actual APK signing certs
    print('\n--- certificate provenance ---')
    print('  overlay cert file : %s  %d B  sha1=%s'
          % (a.cert, len(der), hashlib.sha1(der).hexdigest().upper()))
    # Fingerprints are NOT a substitute for the certificate itself, so print the whole base64 that
    # the overlay embeds; this is the exact string that must equal the <signature> TEXT.
    print('  overlay cert base64 (%d chars, single line, as embedded):' % len(b64))
    for i in range(0, len(b64), 76):
        print('      %s' % b64[i:i + 76])
    for gpath in a.guest:
        found = embedded_certs(gpath)
        if found is None:
            print('  %-58s NO APK Signing Block' % os.path.basename(gpath)); continue
        uniq = {}
        for pid, d in found:
            uniq.setdefault(hashlib.sha1(d).hexdigest().upper(), (pid, d))
        match = any(d == der for _, d in found)
        for sh, (pid, d) in sorted(uniq.items()):
            print('  %-40s block 0x%08x  %d B  sha1=%s'
                  % (os.path.basename(gpath)[:40], pid, len(d), sh))
        check('overlay certificate == the signer embedded in %s' % os.path.basename(gpath), match,
              'config_webview_packages is honoured ONLY when the installed package signer matches '
              'the <signature> text (WebViewUpdater.java:506-521)')

    print('\n=== %d checks, %d failures ===' % (len(checks), len(fails)))
    for f in fails:
        print('  FAIL:', f)

    if a.write_manifest:
        if fails:
            print('  manifest NOT written: %d check(s) failed. A manifest must never vouch for a '
                  'build this auditor rejected.' % len(fails))
        else:
            raw = open(a.apk, 'rb').read()
            m = ['# delivery manifest - written only after every check above passed',
                 '# generated by tools/verify_overlay.py; the installer binds the on-device bytes to '
                 'this audit',
                 'overlay_file=%s' % os.path.basename(a.apk),
                 'overlay_bytes=%d' % len(raw),
                 'overlay_sha256=%s' % hashlib.sha256(raw).hexdigest(),
                 'overlay_package=%s' % els['manifest'].get('package'),
                 'overlay_targetPackage=%s' % ov.get('targetPackage'),
                 'overlay_isStatic=%s' % ov.get('isStatic'),
                 'overlay_priority=%s' % ov.get('priority', '0'),
                 'cert_bytes=%d' % len(der),
                 'cert_sha256=%s' % hashlib.sha256(der).hexdigest(),
                 'cert_base64=%s' % b64,
                 'provider_count=%d' % len(provs)]
            for i, p in enumerate(provs, 1):
                m += ['provider_%d_packageName=%s' % (i, p['packageName']),
                      'provider_%d_description=%s' % (i, p['description']),
                      'provider_%d_availableByDefault=%s' % (i, str(p['availableByDefault']).lower()),
                      'provider_%d_isFallback=%s' % (i, str(p['isFallback']).lower()),
                      'provider_%d_signature_count=%d' % (i, len(p['signatures'])),
                      'provider_%d_signature1_sha256=%s'
                      % (i, hashlib.sha256(base64.b64decode(p['signatures'][0])).hexdigest()
                         if p['signatures'] else 'none')]
            with open(a.write_manifest, 'w') as fh:
                fh.write('\n'.join(m) + '\n')
            print('  manifest written: %s (%d lines, sha256=%s)'
                  % (a.write_manifest, len(m),
                     hashlib.sha256('\n'.join(m).encode()).hexdigest()[:16]))

    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

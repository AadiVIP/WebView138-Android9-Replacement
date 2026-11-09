#!/usr/bin/env python3
"""Build the static RRO that registers Google WebView 138 as a provider on an Android 9 guest.

    python3 tools/build_overlay.py --out output/webview138-provider-overlay.apk \
            --cert work/V2_cert.der [--base-xml <extracted res/xml/config_webview_packages.xml>]

WHY THIS EXISTS. The provider list lives in framework-res.apk (package `android`), which on this
ROM is (a) inside an encrypted image and (b) signed with the ROM build key, so editing and
re-signing it is out of reach. On Android 9 a *static* resource-overlay package dropped into
/vendor/overlay supplies the same resource without touching that file, and with no key at all:

  * PMS:2609-2616 scans /vendor/overlay with PARSE_IS_SYSTEM_DIR | SCAN_AS_SYSTEM.
  * PMS:11232-11249 - the "must be signed with the platform certificate" throw - is inside the
    else-branch for NON-system overlays. It is never reached for /vendor/overlay.
  * PackageParser.java:2077-2094: <overlay> needs only targetPackage (non-null) and a priority in
    0..9999; isStatic defaults to FALSE so it must be present explicitly; a
    requiredSystemPropertyName would silently skip the overlay, so none is emitted.
  * Production proof: /vendor/overlay/FrameworksResCommon.apk (targetPackage="android") overrides
    36 NON-PUBLIC framework entries on a shipping Android 9 device, so neither <public> nor
    <overlayable> is required for config_webview_packages (0x01170007, flags=0).

Everything here is assembled with tools/axml.py and tools/arsc.py, both verified byte-for-byte
against real aapt2 output (selftest_axml.py: 164 checks; arsc.build_xml_override reproduces
CarrierConfigResCommon.apk's resources.arsc exactly). No aapt, Java, or signing key is used, and
the APK is left UNSIGNED on purpose - see the notice printed at the end.

Provider list, in the order SystemImpl/WebViewUpdater will read it:
  1. com.google.android.webview  availableByDefault="true" + <signature>GOOGLE DER</signature>
     first in document order, because WebViewUpdater.java:261-277 and :305-315 pick the first
     availableByDefault provider that is installed and valid; isFallback plays no part.
  2. com.android.webview         verbatim from AOSP 9 core/res/res/xml/config_webview_packages.xml
     (availableByDefault="true", NO isFallback), so the guest's factory WebView 81 stays selectable
     if 138 is ever missing - the list never leaves the system without a WebView.
"""
import sys, os, zipfile, argparse, base64, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arsc
from axml import AXML, AXMLDoc

GOOGLE_PKG = 'com.google.android.webview'
AOSP_PKG = 'com.android.webview'
XML_ENTRY = 'config_webview_packages'
XML_RES_PATH = 'res/xml/%s.xml' % XML_ENTRY
DEFAULT_TEMPLATE = '/vendor/overlay/FrameworksResCommon.apk'


def build_manifest(template_apk, package):
    """Take a real aapt2 static-RRO manifest and change ONLY the package name.

    The template already carries <uses-sdk minSdkVersion=28 targetSdkVersion=28> and
    <overlay targetPackage='android' isStatic='true' priority='100'>, which is exactly what a
    code-less Android 9 overlay needs (the shipping overlays have no <application> element at all).
    """
    z = zipfile.ZipFile(template_apk)
    ax = AXML(z.read('AndroidManifest.xml'))
    els = [(t, a) for k, t, a in ax.dump() if k == 'start']
    tags = [t for t, a in els]
    if 'overlay' not in tags:
        raise SystemExit('REFUSING: template manifest has no <overlay> element: %s' % template_apk)
    ov = dict(next(a for t, a in els if t == 'overlay'))
    if ov.get('targetPackage') != 'android' or ov.get('isStatic') != 'true':
        raise SystemExit('REFUSING: template <overlay> is targetPackage=%r isStatic=%r; need '
                         'android/true' % (ov.get('targetPackage'), ov.get('isStatic')))
    ax.set_attribute('manifest', 'package', package)
    out = ax.serialise()
    chk = AXML(out)
    got = dict(next(a for k, t, a in chk.dump() if t == 'manifest'))
    assert got['package'] == package, 'manifest package did not change'
    got_ov = dict(next(a for k, t, a in chk.dump() if t == 'overlay'))
    assert got_ov['targetPackage'] == 'android' and got_ov['isStatic'] == 'true', 'overlay changed'
    return out, got, got_ov, z


def provider_attrs(p):
    """The four attributes Android 9 reads (SystemImpl.java:94-106), in the order aapt2 compiles
    them (alphabetical - measured against /system/framework/framework-res.apk on this Android 9 host).

    Booleans are OMITTED when false, never written as "false": AOSP writes nothing, and SystemImpl
    compares the string to "true" anyway, so omitting is the faithful form.
    """
    out = []
    if p['availableByDefault']:
        out.append(('availableByDefault', 'true'))
    out.append(('description', p['description']))
    if p['isFallback']:
        out.append(('isFallback', 'true'))
    out.append(('packageName', p['packageName']))
    return out


def build_provider_xml(cert_der, base_xml=None):
    """The res/xml file SystemImpl will read. cert_der = the Google WebView X.509 DER.

    With base_xml (the guest's OWN compiled res/xml/config_webview_packages.xml, extracted from its
    framework-res.apk) EVERY provider in that file is carried over - attributes and all <signature>
    texts - because an RRO REPLACES the resource instead of merging into it, so any entry not repeated
    here silently disappears from the guest's candidate list. Google is then placed FIRST and given
    the real DER: if the base already lists it, that entry is normalised in place rather than
    duplicated. Without base_xml the shipped two-entry list is used (Google + factory webview).
    """
    b64 = base64.b64encode(cert_der).decode()
    base = None
    if base_xml is not None:
        ax = AXML(open(base_xml, 'rb').read())
        root = ax.dump()[0][1]
        if root != 'webviewproviders':
            raise SystemExit('REFUSING: %s root is <%s>, not <webviewproviders>' % (base_xml, root))
        base = ax.webview_providers()
        dropped = [(p['packageName'], p['bad_children']) for p in base if p['bad_children']]
        if dropped:
            print('NOTE: the guest file has child elements Android 9 does not understand; they are\n'
                  '      not carried because SystemImpl.java:177-179 skips them anyway: %s' % dropped)
        if not base:
            raise SystemExit('REFUSING: %s parses to ZERO providers - overlaying it would leave the '
                             'guest with no WebView at all (SystemImpl.java:138-141 throws).'
                             % base_xml)
    doc = AXMLDoc()
    google = {'packageName': GOOGLE_PKG, 'description': 'Google WebView',
              'availableByDefault': True, 'isFallback': False, 'signatures': [b64]}
    if base:
        existing = next((p for p in base if p['packageName'] == GOOGLE_PKG), None)
        if existing:
            google = dict(existing)
            # availableByDefault true so it is selectable; isFallback FORCED false. Not a stylistic
            # choice: fallback logic is ON by default (SystemImpl.java:212-216) and
            # WebViewUpdateServiceImpl.java:202-220 then calls uninstallAndDisablePackageForAllUsers()
            # (SystemImpl.java:225-235) on whichever provider is flagged, as soon as some other
            # valid non-fallback provider exists. Flagging the package we are trying to install would
            # let the platform disable it.
            google.update({'availableByDefault': True, 'isFallback': False, 'signatures': [b64]})
        rest = [p for p in base if p['packageName'] != GOOGLE_PKG]
        flagged = [p['packageName'] for p in rest if p['isFallback']]
        if flagged:
            print('WARNING: the guest file flags %s as isFallback="true". That flag is preserved '
                  '(nothing here invents behaviour), but once WebView 138 is installed and valid,\n'
                  '         Android 9 will DISABLE it for all users as designed\n'
                  '         (WebViewUpdateServiceImpl.java:202-220 -> '
                  'SystemImpl.java:225-235). The APK on disk is untouched and `pm enable %s`\n'
                  '         reverses it. Say the word and the overlay can drop the flag instead.'
                  % (flagged, flagged[0]))
    else:
        rest = [{'packageName': AOSP_PKG, 'description': 'Android WebView',
                 'availableByDefault': True, 'isFallback': False, 'signatures': []}]
    kids = [doc.element('webviewprovider', provider_attrs(google), text=google['signatures'])]
    for p in rest:
        kids.append(doc.element('webviewprovider', provider_attrs(p), text=p['signatures']))
    blob = doc.document('webviewproviders', kids)

    # Read it back with the same depth-aware reader the auditor uses, and prove nothing was lost.
    # (An earlier version used text_values() here, which returns every CDATA in the document
    # regardless of position - it passed a build whose certificate was NOT inside <signature>.)
    chk = AXML(blob)
    provs = chk.webview_providers()
    assert [p['packageName'] for p in provs][0] == GOOGLE_PKG, 'Google is not first'
    assert not provs[0]['isFallback'], \
        'Google must NOT be the fallback: the platform disables the fallback provider once a valid ' \
        'non-fallback one exists (WebViewUpdateServiceImpl.java:202-220)'
    assert provs[0]['signatures'] and base64.b64decode(provs[0]['signatures'][0]) == cert_der, \
        'certificate is not the TEXT of a <signature> child of the Google provider'
    assert all(not p['bad_children'] for p in provs), \
        'SystemImpl.java:177-179 would log and skip: %s' % [p['bad_children'] for p in provs]
    assert all(p['packageName'] and p['description'] for p in provs), \
        'SystemImpl.java:95-104 throws AndroidRuntimeException (would kill system_server)'
    assert sum(1 for p in provs if p['availableByDefault'] and not p['isFallback']) >= 1, \
        'SystemImpl.java:141-144 throws: needs >=1 availableByDefault and not isFallback'
    assert all(p['availableByDefault'] for p in provs if p['isFallback']), \
        'SystemImpl.java:113-116 throws: a fallback must be available by default'
    assert sum(1 for p in provs if p['isFallback']) <= 1, 'SystemImpl.java:117-120 throws'
    if base is not None:
        base_set = set(p['packageName'] for p in base)
        out_set = set(p['packageName'] for p in provs)
        # Google is the ONLY provider this builder may add (when the guest file did not list it).
        # No base provider may be dropped, and no other package may appear. (The old check asserted
        # set-equality, which only held when the base already named Google - it wrongly rejected a
        # guest whose single provider is com.android.webview.)
        assert base_set - out_set == set(), 'base providers dropped: %s' % sorted(base_set - out_set)
        assert out_set - base_set <= {GOOGLE_PKG}, 'unexpected providers added: %s' % sorted(
            out_set - base_set)
        assert GOOGLE_PKG in out_set, 'Google is missing from the output'
        expected = len(base) + (0 if GOOGLE_PKG in base_set else 1)
        assert len(provs) == expected, 'provider count changed: %d -> %d' % (len(base), len(provs))
        for b in base:
            if b['packageName'] == GOOGLE_PKG:
                continue          # this one is intentionally rewritten
            mine = next(p for p in provs if p['packageName'] == b['packageName'])
            assert provider_attrs(mine) == provider_attrs(b), \
                '%s was altered: %r -> %r' % (b['packageName'], provider_attrs(b),
                                              provider_attrs(mine))
            assert mine['signatures'] == b['signatures'], \
                '%s lost a <signature> text' % b['packageName']
    return blob, provs, base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--package', default='com.qoder.webviewprovider.overlay')
    ap.add_argument('--cert', default='work/V2_cert.der',
                    help='DER X.509 of the certificate that signs the WebView 138 APK')
    ap.add_argument('--base-xml', help='extracted guest res/xml/config_webview_packages.xml (AXML)')
    ap.add_argument('--template', default=DEFAULT_TEMPLATE)
    a = ap.parse_args()

    der = open(a.cert, 'rb').read()
    if der[:1] != b'\x30':
        raise SystemExit('REFUSING: %s is not a DER SEQUENCE (0x%02x); nothing will be invented '
                         'in its place.' % (a.cert, der[0]))
    print('certificate   %s: %d B DER, SHA-1 %s, SHA-256 %s'
          % (a.cert, len(der), hashlib.sha1(der).hexdigest().upper(),
             hashlib.sha256(der).hexdigest().upper()))

    manifest, m_attrs, ov_attrs, tz = build_manifest(a.template, a.package)
    print('manifest      from %s: package=%s overlay targetPackage=%s isStatic=%s priority=%s'
          % (a.template, m_attrs['package'], ov_attrs['targetPackage'], ov_attrs['isStatic'],
             ov_attrs.get('priority', '0 (absent)')))

    provider_xml, provs, base = build_provider_xml(der, a.base_xml)
    print('provider xml  %d B, %d entries, %d <signature> text node%s  [base: %s]'
          % (len(provider_xml), len(provs), sum(len(p['signatures']) for p in provs),
             's' if sum(len(p['signatures']) for p in provs) != 1 else '',
             '%s, %d providers preserved verbatim' % (a.base_xml, len(base)) if base is not None
             else 'NONE - shipped 2-entry list, see risk L4c'))
    for i, p in enumerate(provs):
        print('   [%d] %-30s availableByDefault=%-5s isFallback=%-5s description=%r%s'
              % (i, p['packageName'], p['availableByDefault'], p['isFallback'], p['description'],
                 '  <- %d <signature> text' % len(p['signatures']) if p['signatures'] else ''))
    if base is not None:
        g = next(p for p in base if p['packageName'] == GOOGLE_PKG) if any(
            p['packageName'] == GOOGLE_PKG for p in base) else None
        print('   base already listed Google: %s' % ('YES - that entry was normalised (moved first, '
                                                    'availableByDefault=true, certificate replaced) '
                                                    'and its original attributes were %r'
                                                    % ({k: v for k, v in g.items()
                                                       if k not in ('signatures', 'bad_children')}))
              if g else 'no - a new entry was prepended')
        print('   every other entry byte-checked against the base: True (asserted above)')

    table = arsc.build_xml_override(a.package, XML_ENTRY, XML_RES_PATH)
    back = arsc.ARSC(table)
    hits = back.find('xml', XML_ENTRY)
    assert hits and hits[0][2] == ((0x7f << 24) | (2 << 16)), 'arsc self-check failed'
    print('resources.arsc %d B: pkg id=0x7f name=%s, xml/%s -> %s'
          % (len(table), back.packages[0]['name'], XML_ENTRY, hits[0][3]['value']))

    # mirror the template's per-entry compression: aapt STORES resources.arsc (AssetManager mmaps
    # it) and DEFLATES the manifest and the res/ file.
    tcompress = {i.filename: i.compress_type for i in tz.infolist()}
    order = ['resources.arsc', 'AndroidManifest.xml', XML_RES_PATH]
    payload = {'resources.arsc': table, 'AndroidManifest.xml': manifest,
               XML_RES_PATH: provider_xml}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for name in order:
            zi = zipfile.ZipInfo(name, date_time=(2009, 1, 1, 0, 0, 0))
            zi.compress_type = tcompress.get(name, zipfile.ZIP_STORED if name == 'resources.arsc'
                                             else zipfile.ZIP_DEFLATED)
            zi.external_attr = 0o644 << 16
            zo.writestr(zi, payload[name])

    print('\n--- verifying the written file by re-reading it ---')
    z = zipfile.ZipFile(a.out)
    print('%s: %d B, entries=%s' % (a.out, os.path.getsize(a.out), z.namelist()))
    ar = arsc.ARSC(z.read('resources.arsc'))
    ent = ar.find('xml', XML_ENTRY)[0][3]
    axm = AXML(z.read('AndroidManifest.xml'))
    ov = dict(next(x for k, t, x in axm.dump() if t == 'overlay'))
    pkg = dict(next(x for k, t, x in axm.dump() if t == 'manifest'))['package']
    px = AXML(z.read(XML_RES_PATH))
    read = px.webview_providers()
    plist = [p['packageName'] for p in read]
    cert_ok = bool(read[0]['signatures']) and base64.b64decode(read[0]['signatures'][0]) == der
    ok = (ov['targetPackage'] == 'android' and ov['isStatic'] == 'true'
          and ent['value'] == "STRING %r" % XML_RES_PATH and plist[0] == GOOGLE_PKG and cert_ok)
    print('  manifest package=%s targetPackage=%s isStatic=%s' % (pkg, ov['targetPackage'],
                                                                   ov['isStatic']))
    print('  arsc  xml/%s -> %s (0x%08x)' % (XML_ENTRY, ent['value'],
                                             (0x7f << 24) | (ent['type'] << 16) | ent['id']))
    print('  xml   providers in order: %s' % plist)
    print('  cert  <signature> TEXT decodes to the input DER: %s' % cert_ok)
    print('  END-TO-END VERIFY: %s   (run tools/verify_overlay.py for the independent audit)'
          % ('PASS' if ok else 'FAIL'))
    print("""
NOT SIGNED. Deliberately:
  * Android 9 does not require a signature for a static overlay in /vendor/overlay. The
    platform-certificate check (PackageManagerService.java:11232-11249) lives in the NON-system
    branch; /vendor/overlay is scanned with SCAN_AS_SYSTEM (PMS:2609-2616).
  * No key or certificate was generated, invented, or substituted.
  * What WAS verified here is the file format and the source-level rules. What was NOT verified is
    any runtime behaviour: this environment has no Android 9 guest to boot, so nothing about boot,
    idmap execution, SELinux labelling of a copied file, or WebView selection has been observed.
  * Known way this fails silently: idmap runs as installd and needs read access. A file copied into
    /vendor/overlay keeps the label of whatever created it; if it is not readable the log shows
    "Failed to generate idmap for ..." and the overlay is ignored - not a boot loop.
""")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

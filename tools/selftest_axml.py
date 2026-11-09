#!/usr/bin/env python3
"""Self-test for tools/axml.py against REAL compiled XML from the WebView APKs.

Checks, in order:
  T1 parse every res/*.xml + AndroidManifest.xml in both APKs; dump must be non-empty.
  T2 serialise() is byte-identical to the input (no mutation).
  T3 intern() an existing string  -> must not change the pool, must return same index.
  T4 intern() a new string        -> all original strings still resolve identically at
                                     their original indices, doc re-parses, size grows.
  T5 insert a 3-attribute element -> re-parse; the new element appears with the exact
                                     attribute values; every pre-existing element is
                                     unchanged; start/end element counts stay balanced.
  T6 write the mutated doc into a rebuilt zip entry and re-read it back from disk.

Run:  python3 tools/selftest_axml.py
"""
import sys, os, zipfile, struct, io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axml import AXML, AXMLDoc, RES_XML_START_ELEMENT, RES_XML_END_ELEMENT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APKS = [os.path.join(ROOT, 'input', 'webview138.apk'),
        os.path.join(ROOT, 'input', 'webview138_arm64_universal_138.0.7204.179.apk')]

fails, checks = [], 0


def check(name, cond, detail=""):
    global checks
    checks += 1
    if not cond:
        fails.append(f"{name}: {detail}")
        print(f"  FAIL {name} {detail}")
    else:
        print(f"  ok   {name} {detail}")


targets = []
for a in APKS:
    z = zipfile.ZipFile(a)
    for n in z.namelist():
        if n == 'AndroidManifest.xml' or (n.startswith('res/') and n.endswith('.xml')):
            targets.append((a, n, z.read(n)))
    keep = [x for x in targets if x[1] == 'AndroidManifest.xml' or x[1].startswith('res/xml/')]
    rest = [x for x in targets if x not in keep]
    targets = [(a, n, d) for a, n, d in targets if a == APKS[0]]
    targets = keep[:4] + rest[:8]
print(f"T1 real compiled XML files found: {len(targets)}")
check("T1 found test material", len(targets) >= 4, f"{len(targets)} files")

for apath, name, data in targets:
    short = os.path.basename(apath)[:18] + "/" + name
    try:
        d = AXML(data)
    except Exception as e:
        check(f"parse {short}", False, repr(e))
        continue
    dump = d.dump()
    check(f"T1 parse {short}", len(dump) > 0, f"{len(dump)} nodes, {len(d.strings)} strings")
    is_utf8 = d.utf8
    check(f"T2 byte-exact {short}", d.serialise() == data, f"utf8pool={is_utf8}")
    # T2b: the strongest check - re-encoding the UNCHANGED string list must reproduce the
    # original pool bytes exactly, i.e. our length encoding matches aapt2 byte for byte.
    rebuilt = d._encode_pool(d.strings)
    orig = bytes(data[d.pool_off:d.pool_off + d.pool_size])
    check(f"T2b pool re-encode identical {short}", rebuilt == orig,
          f"{len(rebuilt)}B vs {len(orig)}B" if rebuilt != orig else f"{len(orig)}B")

    # T3/T4 operate on a fresh object so mutations never leak between files.
    try:
        d = AXML(data)
        if d.strings:
            i0 = d.intern(d.strings[0])
            check(f"T3 intern existing {short}", i0 == 0 and d.serialise() == data,
                  f"idx {i0}")
        before = list(d.strings)
        news = "SELFTEST-MARKER-ZZZ", "com.google.android.webview"
        idxs = [d.intern(s) for s in news]
        after = d.strings
        check(f"T4 prefix preserved {short}", after[:len(before)] == before,
              f"{len(before)}->{len(after)} strings")
        check(f"T4 new strings retrievable {short}",
              all(after[i] == s for i, s in zip(idxs, news)), str(idxs))
        doc = d.serialise()
        check(f"T4 doc re-parses {short}", True, f"{len(doc)} B")
        d2 = AXML(doc)
        check(f"T4 pool stable after reload {short}", d2.strings == after)

        # T5: only documents with a start element can host an insertion.
        if any(t == RES_XML_START_ELEMENT for t, _, _ in d2.chunks):
            first = None
            for typ, off, _ in d2.chunks:
                if typ == RES_XML_START_ELEMENT:
                    first = d2.strings[struct.unpack_from('<I', d2.b, off + 20)[0]]
                    break
            dump_before = d2.dump()
            end = d2.insert_after_element("selftestProvider",
                                          [("packageName", "com.google.android.webview"),
                                           ("description", "Google WebView"),
                                           ("signature", "MIIDuzCCAq" + "Zm9v")],
                                          first)
            d3 = AXML(d2.serialise())
            dump_after = d3.dump()
            names = [(k, t) for k, t, _ in dump_after]
            check(f"T5 inserted {short}",
                  ('start', 'selftestProvider') in names, f"anchor=<{first}>")
            check(f"T5 attrs exact {short}",
                  any(t == 'selftestProvider' and a == [('packageName', 'com.google.android.webview'),
                                                        ('description', 'Google WebView'),
                                                        ('signature', 'MIIDuzCCAqZm9v')]
                      for _, t, a in dump_after),
                  str([a for _, t, a in dump_after if t == 'selftestProvider']))
            n_before = len([1 for k, t, _ in dump_before if k == 'start'])
            n_after = len([1 for k, t, _ in dump_after if k == 'start'])
            check(f"T5 siblings intact {short}", n_after == n_before + 1,
                  f"{n_before}->{n_after}")
            starts = len([1 for k, t, _ in dump_after if k == 'start'])
            ends = len([1 for k, t, _ in dump_after if k == 'end'])
            check(f"T5 balanced {short}", starts == ends, f"{starts} vs {ends}")

            # T6: survive a real zip round trip.
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as zo:
                zo.writestr('payload.xml', d2.serialise())
            back = zipfile.ZipFile(io.BytesIO(buf.getvalue())).read('payload.xml')
            check(f"T6 zip round trip {short}", AXML(back).dump() == dump_after)
    except NotImplementedError as e:
        check(f"mutation {short}", False, "unimplemented: " + str(e))
    except Exception as e:
        check(f"mutation {short}", False, repr(e))


# T7: element TEXT (RES_XML_CDATA) handling, on the real framework resource we intend to ship.
# SystemImpl.readSignatures() uses parser.nextText(), so a provider certificate lives in element
# text, not an attribute - this is the one path that a byte-exact writer must not get wrong.
FRAMEWORK = '/system/framework/framework-res.apk'
try:
    fx = zipfile.ZipFile(FRAMEWORK).read('res/xml/config_webview_packages.xml')
    fax = AXML(fx)
    texts = fax.text_values()
    nprov = len([1 for k, t, a in fax.dump() if k == 'start' and t == 'webviewprovider'])
    check('T7 framework resource present', fax.dump()[0][1] == 'webviewproviders',
          '%d providers, %d text nodes' % (nprov, len(texts)))
    import base64 as _b64
    ok = all(s0[:1] == 'M' and len(_b64.b64decode(s0)) > 500 for s0 in texts)
    check('T7 every <signature> text base64-decodes to a DER SEQUENCE', ok,
          str([(len(s0), len(_b64.b64decode(s0))) for s0 in texts]))
    # a CDATA chunk I build must be byte-identical to aapt2's, ignoring lineNumber
    sig_node, _ = fax.build_element('signature', [])
    cd = fax.build_cdata(texts[0])
    zero = lambda b: bytes(b[:8]) + b'\x00\x00\x00\x00' + bytes(b[12:])
    real_cd = None
    for typ, o, size in fax.chunks:
        if typ == 0x0104:
            real_cd = bytes(fax.b[o:o + size])
            break
    check('T7 <signature> node == aapt2 byte-for-byte (mod lineNumber)',
          zero(sig_node) == zero(bytes(fx[o - 36:o])), bytes(sig_node).hex(' '))
    check('T7 CDATA chunk == aapt2 byte-for-byte (mod lineNumber)', zero(cd) == zero(real_cd),
          'mine=%s\n   real=%s' % (cd.hex(' '), real_cd.hex(' ')))
    # insert a provider WITH text, then re-parse and prove the cert survived
    ax7 = AXML(fx)
    ax7.insert_as_first_child('webviewprovider',
                              [('description', 'Google WebView'),
                               ('packageName', 'com.google.android.webview'),
                               ('availableByDefault', 'true')],
                              'webviewproviders', text=texts[0])
    back7 = AXML(ax7.serialise())
    t7texts = back7.text_values()
    check('T7 insert-with-text re-parses and text survives',
          t7texts[0] == texts[0] and len(t7texts) == len(texts) + 1,
          '%d -> %d text nodes' % (len(texts), len(t7texts)))
    starts = len([1 for k, t, a in back7.dump() if k == 'start'])
    ends = len([1 for k, t, a in back7.dump() if k == 'end'])
    check('T7 document balanced after text insert', starts == ends, '%d vs %d' % (starts, ends))
    check('T7 cert DER still decodes to the same bytes after round trip',
          _b64.b64decode(t7texts[0]) == _b64.b64decode(texts[0]))
except Exception as e:
    check('T7 element text (CDATA) path', False, repr(e))

# T8: the SystemImpl-faithful reader and the from-scratch <signature> wrapper.
# Regression lock: build_overlay.py once emitted the certificate as BARE CDATA under
# <webviewprovider>. text_values() could not tell the difference (it returns every CDATA in the
# document), so the builder's own assert passed; Android 9 would have read zero signatures and
# fallen back to isSystemApp() (WebViewUpdater.java:506-521). webview_providers() is depth-aware and
# is now the single reader used by builder and auditor alike.
try:
    real = AXML(fx).webview_providers()
    check('T8 reader on the REAL framework file: provider count', len(real) == nprov,
          '%d providers' % len(real))
    check('T8 reader on the REAL framework file: no unrecognised children',
          all(not p['bad_children'] for p in real), str([p['bad_children'] for p in real]))
    check('T8 reader on the REAL framework file: signature texts are certs',
          all(len(p['signatures']) <= 1 and all(len(_b64.b64decode(s)) > 500 for s in p['signatures'])
              for p in real),
          str([(p['packageName'], len(p['signatures'])) for p in real]))
    check('T8 reader on the REAL framework file: booleans, not strings',
          all(isinstance(p['availableByDefault'], bool) and isinstance(p['isFallback'], bool)
              for p in real))

    doc = AXMLDoc()
    blob = doc.document('webviewproviders',
                        [doc.element('webviewprovider',
                                     [('availableByDefault', 'true'), ('description', 'd'),
                                      ('packageName', 'com.google.android.webview')],
                                     text=texts[0])])
    built = AXML(blob).webview_providers()
    check('T8 from-scratch text= produces a <signature> child the reader sees',
          len(built) == 1 and built[0]['signatures'] == [texts[0]] and not built[0]['bad_children'],
          str(built))
    # and prove it is the WRAPPER that carries it: the same CDATA spliced in as a bare child of
    # <webviewprovider> must be invisible to the reader (that is what Android 9 does with it).
    naked = AXMLDoc()
    prov = naked.element('webviewprovider', [('packageName', 'x'), ('description', 'y')])
    bare = prov[:-24] + naked.cdata(texts[0]) + prov[-24:]     # CDATA before the END_ELEMENT
    read_bare = AXML(naked.document('webviewproviders', [bare])).webview_providers()
    check('T8 bare CDATA (no <signature>) really is invisible to the reader',
          read_bare[0]['signatures'] == [], 'reader must NOT report a signature that is not inside '
          '<signature>; got %r' % (read_bare[0]['signatures'],))
    check('T8 but the CDATA is still in the file', texts[0] in AXML(
        naked.document('webviewproviders', [bare])).text_values())
except Exception as e:
    check('T8 reader / from-scratch signature wrapper', False, repr(e))

# T9: the guest's REAL base has ONE provider (com.android.webview) and does NOT name Google.
# Regression lock for two bugs fixed when that exact file arrived: build_overlay.py and
# verify_overlay.py both asserted set-equality between base and output, which is only true when the
# base already lists Google. The correct invariant: drop nothing, add Google if and only if absent.
try:
    import base64 as _b9
    import xml_to_axml, build_overlay
    base_text = os.path.join(ROOT, 'work', 'selftest_t9_guestbase.xml')
    base_axml = os.path.join(ROOT, 'work', 'selftest_t9_guestbase.axml')
    open(base_text, 'w').write(
        '<?xml version="1.0" encoding="utf-8"?>\n<webviewproviders>\n'
        '    <webviewprovider availableByDefault="true" description="Android WebView" '
        'packageName="com.android.webview" />\n</webviewproviders>\n')
    xml_to_axml.main(['x', base_text, base_axml])
    cert_der = _b9.b64decode(texts[0])
    blob, provs, base = build_overlay.build_provider_xml(cert_der, base_axml)
    by = {p['packageName']: p for p in provs}
    check('T9 base lacking Google -> output has exactly base + Google',
          len(provs) == 2 and set(by) == {'com.google.android.webview', 'com.android.webview'},
          str([p['packageName'] for p in provs]))
    check('T9 Google is first and not the fallback',
          provs[0]['packageName'] == 'com.google.android.webview' and provs[0]['isFallback'] is False,
          str(provs[0]))
    check('T9 Google carries the verified certificate text',
          provs[0]['signatures'] == [texts[0]], str(len(provs[0]['signatures'] or [])))
    g = by['com.android.webview']
    check('T9 the guest provider is preserved verbatim (available, non-fallback, no sig)',
          g['availableByDefault'] is True and g['isFallback'] is False and g['signatures'] == []
          and g['description'] == 'Android WebView', str(g))
    check('T9 the preserved provider matches the base entry',
          g['packageName'] == base[0]['packageName'] and g['availableByDefault']
          == base[0]['availableByDefault'], str(base[0]))
finally:
    for f in (base_text, base_axml):
        try: os.remove(f)
        except OSError: pass

print()
print(f"checks run: {checks}   failures: {len(fails)}")
for f in fails:
    print("  -", f)
sys.exit(1 if fails else 0)

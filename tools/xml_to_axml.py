#!/usr/bin/env python3
"""Compile a *plain-text* res/xml/config_webview_packages.xml into binary AXML.

    python3 tools/xml_to_axml.py <in.xml> <out.axml>

Why this exists: `build_overlay.py --base-xml` reads the guest's config through tools/axml.py, which
parses the *compiled* AXML Android actually stores. A file decompiled/pretty-printed for a human (as
in this handoff) is plain XML and would crash that parser. This tool re-compiles the text with the
same serializer selftest_axml.py pins byte-for-byte, then re-parses the result and asserts it reads
back to exactly the providers the text declared, so nothing is invented or dropped on the way.

Only the four attributes Android 9 reads are preserved as attributes (packageName/description/
availableByDefault/isFallback; SystemImpl.java:94-106); <signature> child TEXT is preserved as a
<signature> child (SystemImpl.java:166-181). Anything else Android skips is dropped, matching what
the framework itself would do.
"""
import sys, os
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axml import AXMLDoc, AXML

KNOWN = ('packageName', 'description', 'availableByDefault', 'isFallback')


def text_providers(root):
    """Parse the plain XML the way Android 9 reads it, so we can compare against the AXML round-trip."""
    out = []
    for el in root:
        if el.tag != 'webviewprovider':
            continue
        p = {'packageName': None, 'description': None, 'availableByDefault': False,
             'isFallback': False, 'signatures': []}
        for k, v in el.attrib.items():
            if k in KNOWN:
                p[k] = (v == 'true') if k in ('availableByDefault', 'isFallback') else v
        for s in el:
            if s.tag == 'signature' and (s.text or '').strip():
                p['signatures'].append((s.text or '').strip())
        out.append(p)
    return out


def main(argv):
    if len(argv) != 3:
        sys.exit('usage: xml_to_axml.py <in.xml> <out.axml>')
    src, out = argv[1], argv[2]
    root = ET.parse(src).getroot()
    if root.tag != 'webviewproviders':
        sys.exit('REFUSING: root is <%s>, not <webviewproviders>' % root.tag)
    tp = text_providers(root)
    if not tp:
        sys.exit('REFUSING: the text XML has zero <webviewprovider> entries')

    doc = AXMLDoc()
    kids = []
    for p in tp:
        attrs = []
        if p['availableByDefault']:
            attrs.append(('availableByDefault', 'true'))
        if p['description']:
            attrs.append(('description', p['description']))
        if p['isFallback']:
            attrs.append(('isFallback', 'true'))
        attrs.append(('packageName', p['packageName']))
        kids.append(doc.element('webviewprovider', attrs, text=p['signatures']))
    blob = doc.document('webviewproviders', kids)

    # round-trip: the compiled bytes must read back to exactly what the text said
    rt = AXML(blob).webview_providers()
    if [p['packageName'] for p in rt] != [p['packageName'] for p in tp]:
        sys.exit('REFUSING: round-trip lost or reordered providers')
    for a, b in zip(rt, tp):
        if (a['description'], a['availableByDefault'], a['isFallback'], a['signatures']) != \
           (b['description'], b['availableByDefault'], b['isFallback'], b['signatures']):
            sys.exit('REFUSING: round-trip changed a provider: %s vs %s' % (a, b))
        if a['bad_children']:
            sys.exit('REFUSING: unexpected child elements in source: %s' % a['bad_children'])

    open(out, 'wb').write(blob)
    print('compiled %s -> %s  (%d provider(s): %s)'
          % (src, out, len(tp), ', '.join(p['packageName'] for p in tp)))


if __name__ == '__main__':
    main(sys.argv)

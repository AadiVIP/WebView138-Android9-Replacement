"""Android binary-XML (AXML) reader/writer that preserves bytes exactly.

Purpose: insert a <webviewprovider> element into res/xml/config_webview_packages.xml inside
framework-res.apk without aapt (unavailable here), so only the one resource file changes.

Structures are the ones published in frameworks/base/include/androidfw/ResourceTypes.h.
Verified against real files by selftest_axml.py (byte-exact round trip + mutation re-parse).

    chunk            type u16 @+0, headerSize u16 @+2, size u32 @+4
    ResStringPool    +8 stringCount, +12 styleCount, +16 flags, +20 stringsStart, +24 stylesStart
    START_ELEMENT    node header is 16 bytes (type/hdr/size/lineNumber/comment), then
                     attrExt: ns u32 @+16, name u32 @+20, attributeStart u16 @+24,
                     attributeSize u16 @+26, attributeCount u16 @+28
    attribute        ns u32, name u32, rawValue u32, Res_value{size u16, res0 u8,
                     dataType u8, data u32}                       => 20 bytes, stride attributeSize
"""
import struct

RES_NULL, RES_STRING_POOL, RES_XML = 0x0000, 0x0001, 0x0003
RES_XML_START_NS, RES_XML_END_NS = 0x0100, 0x0101
RES_XML_START_ELEMENT, RES_XML_END_ELEMENT, RES_XML_CDATA = 0x0102, 0x0103, 0x0104
RES_XML_LAST_CHUNK, RES_XML_RESOURCE_MAP = 0x0107, 0x0180

TYPE_NULL, TYPE_STRING, TYPE_INT_DEC, TYPE_INT_HEX, TYPE_BOOL = 0x00, 0x03, 0x10, 0x11, 0x12
RES_NO_NAMESPACE = 0xFFFFFFFF
RES_NULL_VALUE = 0xFFFFFFFF

u16 = lambda b, o: struct.unpack_from('<H', b, o)[0]
u32 = lambda b, o: struct.unpack_from('<I', b, o)[0]
pack = struct.pack


def encode_pool(strings, utf8=True, hdr=28):
    """ResStringPool chunk bytes. Indices are positional, so the caller's list order is kept."""
    blobs, offsets = bytearray(), []
    for s in strings:
        offsets.append(len(blobs))
        if utf8:
            e = s.encode('utf-8')
            cn, bn = len(s), len(e)
            blobs += (pack('<BB', 0x80 | (cn >> 8), cn & 0xFF)) if cn >= 0x80 else pack('<B', cn)
            blobs += (pack('<BB', 0x80 | (bn >> 8), bn & 0xFF)) if bn >= 0x80 else pack('<B', bn)
            blobs += e + b'\x00'
        else:
            e = s.encode('utf-16-le')
            cn = len(s)
            blobs += (pack('<H', (cn >> 16) | 0x8000) + pack('<H', cn & 0xFFFF)) \
                     if cn >= 0x8000 else pack('<H', cn)
            blobs += e + b'\x00\x00'
    blobs += b'\x00' * ((-len(blobs)) % 4)
    start = hdr + 4 * len(strings)
    out = pack('<HHIIIIII', RES_STRING_POOL, hdr, 0, len(strings), 0,
               0x100 if utf8 else 0, start, 0)
    out += b''.join(pack('<I', o) for o in offsets) + bytes(blobs)
    return struct.pack_into('<I', (buf := bytearray(out)), 4, len(buf)) or bytes(buf)


class AXMLDoc:
    """Build a complete AXML document from nothing, reusing the chunk builders that selftest T7
    proves are byte-equal to aapt2 output. Needed because the shipped overlay must carry an exact
    provider list (guest entry + Google entry first), which cannot be obtained by insertion alone.
    """

    def __init__(self, utf8=True):
        self.strings = []
        self.utf8 = utf8

    def intern(self, v):
        if v in self.strings:
            return self.strings.index(v)
        self.strings.append(v)
        return len(self.strings) - 1

    def element(self, tag, attrs, text=None, line=1):
        """text=... is the certificate: it becomes the TEXT of a child <signature> element.

        Pass a LIST of strings to emit several <signature> children (SystemImpl collects them into an
        array, WebViewProviderInfo.java:38-43). Bare CDATA under the provider is silently dropped by
        SystemImpl.readSignatures() (SystemImpl.java:166-181 only calls nextText() after seeing
        START_TAG <signature>), so the wrapper is mandatory - it is the shape aapt2 writes in the real
        framework-res: <signature> = START_ELEMENT(36) + CDATA(28) + END_ELEMENT(24).
        """
        node = pack('<HHI', RES_XML_START_ELEMENT, 16, 0) + pack('<II', line, RES_NULL_VALUE)
        node += pack('<II', RES_NO_NAMESPACE, self.intern(tag))
        body = b''
        for n, v in attrs:
            ni, vi = self.intern(n), self.intern(v)
            body += pack('<III', RES_NO_NAMESPACE, ni, vi) + pack('<HBB', 8, 0, TYPE_STRING) \
                   + pack('<I', vi)
        cnt = len(attrs)
        head = pack('<HHHHHH', 20, 20, cnt, 0, 0, 0)
        node += head + body
        node = node[:4] + pack('<I', 36 + 20 * cnt) + node[8:]
        mid = b''
        for t in ([text] if isinstance(text, str) else (text or [])):
            sig = self.element('signature', [], line=line)
            mid += sig[:36] + self.cdata(t, line) + sig[36:]
        end = pack('<HHI', RES_XML_END_ELEMENT, 16, 24) + pack('<II', line, RES_NULL_VALUE)
        end += pack('<II', RES_NO_NAMESPACE, self.intern(tag))
        return node + mid + end

    def cdata(self, text, line=1):
        c = pack('<HHI', RES_XML_CDATA, 16, 28) + pack('<II', line, RES_NULL_VALUE)
        return c + pack('<III', self.intern(text), 0, 0)

    def document(self, root_tag, children, line=1):
        """children must be built with element() BEFORE calling this: interning has to finish
        before the string pool can be serialised."""
        node = pack('<HHI', RES_XML_START_ELEMENT, 16, 36) + pack('<II', line, RES_NULL_VALUE)
        node += pack('<II', RES_NO_NAMESPACE, self.intern(root_tag))
        node += pack('<HHHHHH', 20, 20, 0, 0, 0, 0)
        root_end = pack('<HHI', RES_XML_END_ELEMENT, 16, 24) + pack('<II', line, RES_NULL_VALUE)
        root_end += pack('<II', RES_NO_NAMESPACE, self.intern(root_tag))
        pool = encode_pool(self.strings, self.utf8)
        body = node + b''.join(children) + root_end
        out = pack('<HHI', RES_XML, 8, 0) + pool + pack('<HHI', RES_XML_RESOURCE_MAP, 8, 8) + body
        return pack('<HHI', RES_XML, 8, len(out)) + out[8:]


class AXML:
    def __init__(self, data):
        self.b = bytearray(data)
        if u16(self.b, 0) != RES_XML:
            raise ValueError("not AXML: root type 0x%04x" % u16(self.b, 0))
        self.doc_size = u32(self.b, 4)
        self.pool_off = 8
        self._load_pool()
        self._scan()

    # ------------------------------------------------------------------ pool
    def _load_pool(self):
        b, p = self.b, self.pool_off
        self.pool_hdr = u16(b, p + 2)
        self.pool_size = u32(b, p + 4)
        count = u32(b, p + 8)
        self.pool_flags = u32(b, p + 16)
        self.pool_strings_start = u32(b, p + 20)
        self.utf8 = bool(self.pool_flags & 0x100)
        table, data = p + self.pool_hdr, p + self.pool_strings_start
        out = []
        for i in range(count):
            q = data + u32(b, table + i * 4)
            if self.utf8:
                # AOSP decodeLength8: high bit of the FIRST BYTE means a second byte follows.
                v = b[q]
                if v & 0x80:
                    n, q = ((v & 0x7F) << 8) | b[q + 1], q + 2
                else:
                    n, q = v, q + 1
                v = b[q]
                if v & 0x80:
                    m, q = ((v & 0x7F) << 8) | b[q + 1], q + 2
                else:
                    m, q = v, q + 1
                out.append(b[q:q + m].decode('utf-8', 'replace'))
            else:
                v = u16(b, q)
                if v & 0x8000:
                    n, q = ((v & 0x7FFF) << 16) | u16(b, q + 2), q + 4
                else:
                    n, q = v, q + 2
                out.append(b[q:q + n * 2].decode('utf-16-le', 'replace'))
        self.strings = out

    def _encode_pool(self, strings):
        """Delegates to the module-level encoder so exactly one implementation exists."""
        return encode_pool(strings, self.utf8, self.pool_hdr or 28)


    # ---------------------------------------------------------------- chunks
    def _scan(self):
        b, o, end = self.b, self.pool_off + self.pool_size, self.doc_size
        self.chunks = []
        while o + 8 <= end:
            typ, size = u16(b, o), u32(b, o + 4)
            if typ == RES_NULL or size < 8:
                break
            self.chunks.append((typ, o, size))
            o += size

    def serialise(self):
        return bytes(self.b[:self.doc_size])

    # ------------------------------------------------------------- elements
    def attrs(self, off):
        name = self.strings[u32(self.b, off + 20)]
        astart, asize, acount = u16(self.b, off + 24), u16(self.b, off + 26), u16(self.b, off + 28)
        astart = astart or 20
        asize = asize or 20
        res = []
        for k in range(acount):
            a = off + 16 + astart + k * asize
            res.append({'off': a, 'ns': u32(self.b, a), 'name': u32(self.b, a + 4),
                        'raw': u32(self.b, a + 8), 'vsize': u16(self.b, a + 12),
                        'type': self.b[a + 15], 'data': u32(self.b, a + 16)})
        return name, res

    def dump(self):
        """[(kind, tag, [(attrname, value_string_or_int)])] in document order."""
        out = []
        for typ, o, size in self.chunks:
            if typ == RES_XML_START_ELEMENT:
                nm, ar = self.attrs(o)
                out.append(('start', nm, [(self.strings[x['name']],
                              self.strings[x['data']] if x['type'] == TYPE_STRING else
                              ('true' if x['data'] and x['type'] == TYPE_BOOL else x['data']))
                             for x in ar]))
            elif typ == RES_XML_END_ELEMENT:
                out.append(('end', self.strings[u32(self.b, o + 20)], []))
        return out

    def webview_providers(self, root_tag='webviewproviders'):
        """Parse <root_tag> exactly the way Android 9 does, so builder and auditor share one reader.

        SystemImpl.java:88-124 - attributes packageName/description/availableByDefault/isFallback are
        read with getAttributeValue on the <webviewprovider> element (depth 2), and the certificate is
        the TEXT of a <signature> child (SystemImpl.java:166-181 -> parser.nextText()), which sits at
        depth 3 as CDATA. Anything else the framework does not understand: a signature= ATTRIBUTE is
        never read, and CDATA that is not inside <signature> is skipped without a warning.
        """
        out, depth, cur = [], 0, None
        for typ, o, size in self.chunks:
            if typ == RES_XML_START_ELEMENT:
                depth += 1
                tag = self.strings[u32(self.b, o + 20)]
                if depth == 1:
                    if tag != root_tag:
                        raise ValueError('root element is <%s>, expected <%s>' % (tag, root_tag))
                elif depth == 2 and tag == 'webviewprovider':
                    nm, ar = self.attrs(o)
                    cur = {'packageName': None, 'description': None, 'availableByDefault': False,
                           'isFallback': False, 'signatures': [], 'bad_children': []}
                    for x in ar:
                        n = self.strings[x['name']]
                        if n not in ('packageName', 'description', 'availableByDefault',
                                     'isFallback'):
                            continue          # Android reads only these four; extras are ignored
                        v = (self.strings[x['data']] if x['type'] == TYPE_STRING
                             else ('true' if x['data'] and x['type'] == TYPE_BOOL else 'false'))
                        cur[n] = (v == 'true') if n in ('availableByDefault', 'isFallback') else v
                    out.append(cur)
                elif depth == 3 and tag != 'signature' and cur is not None:
                    cur['bad_children'].append(tag)   # SystemImpl.java:177-179 logs and skips
            elif typ == RES_XML_END_ELEMENT:
                if depth == 2:
                    cur = None
                depth -= 1
            elif typ == RES_XML_CDATA and depth == 3 and cur is not None:
                cur['signatures'].append(self.strings[u32(self.b, o + 16)])
        return out

    # ------------------------------------------------------------- mutation
    def intern(self, s):
        if s in self.strings:
            return self.strings.index(s)
        new = self._encode_pool(self.strings + [s])
        self.b[self.pool_off:self.pool_off + self.pool_size] = new
        self.doc_size += len(new) - self.pool_size
        self.strings = None
        self._load_pool()
        struct.pack_into('<I', self.b, 4, self.doc_size)
        self._scan()
        return len(self.strings) - 1

    def build_element(self, tag, attrs, ns=None, line=1):
        """attrs: [(name, value_str)] -> non-namespaced TYPE_STRING attributes, which is
        exactly how stock config_webview_packages.xml writes packageName/description."""
        tagi = self.intern(tag)
        body = bytearray()
        for n, v in attrs:
            ni, vi = self.intern(n), self.intern(v)
            body += pack('<III', RES_NO_NAMESPACE, ni, vi)
            body += pack('<HBB', 8, 0, TYPE_STRING) + pack('<I', vi)
        cnt = len(attrs)
        node = bytearray(pack('<HHI', RES_XML_START_ELEMENT, 16, 0))
        node += pack('<II', line, RES_NULL_VALUE)
        node += pack('<II', RES_NO_NAMESPACE if ns is None else self.intern(ns), tagi)
        node += pack('<HHHHHH', 20, 20, cnt, 0, 0, 0)   # attributeStart/Size/Count, id/class/style
        node += body
        struct.pack_into('<I', node, 4, 36 + 20 * cnt)
        end = bytearray(pack('<HHI', RES_XML_END_ELEMENT, 16, 24))
        end += pack('<II', line, RES_NULL_VALUE)
        end += pack('<II', RES_NO_NAMESPACE if ns is None else self.intern(ns), tagi)
        return bytes(node), bytes(end)

    def insert_as_first_child(self, tag, attrs, parent_tag, text=None):
        """Insert as the FIRST child of <parent_tag>, i.e. immediately after its START_ELEMENT.

        Needed because Android 9 walks the provider list in document order with no sort
        (WebViewUpdater.java:261-277), so first place = default provider.

        text=... nests a single <signature>TEXT</signature> child, because SystemImpl reads the
        provider certificate with parser.nextText() (element text), NOT as an attribute.
        """
        node, end = self.build_element(tag, attrs)
        payload = node + end
        if text is not None:
            sig_node, sig_end = self.build_element('signature', [])
            payload = node + sig_node + self.build_cdata(text) + sig_end + end
        off = None
        for typ, o, size in self.chunks:
            if typ == RES_XML_START_ELEMENT and self.strings[u32(self.b, o + 20)] == parent_tag:
                off = o + size
                break
        if off is None:
            raise LookupError("parent <%s> not found" % parent_tag)
        self.b[off:off] = payload
        self.doc_size += len(payload)
        struct.pack_into('<I', self.b, 4, self.doc_size)
        self._scan()
        return off

    def insert_after_element(self, tag, attrs, sibling_tag):
        """Insert a <tag ...></tag> immediately after the sibling element (its start..end pair).

        build_element() may grow the string pool, which shifts every chunk, so the splice
        position MUST be resolved after the payload is built, never before.
        """
        node, end = self.build_element(tag, attrs)
        idx = None
        for i, (typ, o, size) in enumerate(self.chunks):
            if typ == RES_XML_START_ELEMENT and self.strings[u32(self.b, o + 20)] == sibling_tag:
                idx = i
                break
        if idx is None:
            raise LookupError("sibling <%s> not found" % sibling_tag)
        depth, j = 1, idx + 1
        while j < len(self.chunks):
            t, o, s = self.chunks[j]
            if t == RES_XML_START_ELEMENT:
                depth += 1
            elif t == RES_XML_END_ELEMENT:
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(self.chunks):
            raise LookupError("unbalanced document")
        ins_end = self.chunks[j][1] + self.chunks[j][2]
        self.b[ins_end:ins_end] = node + end
        self.doc_size += len(node) + len(end)
        struct.pack_into('<I', self.b, 4, self.doc_size)
        self._scan()
        return ins_end

    def set_attribute(self, tag, name, value):
        """Re-point <tag>'s non-namespaced attribute `name` at `value` (interning if new).

        Needed to retarget a template overlay's android:package. intern() can grow the pool,
        which shifts every chunk, so the attribute is located AFTER interning - the same ordering
        invariant insert_after_element() documents.
        """
        idx = self.intern(value)
        for typ, o, size in self.chunks:
            if typ != RES_XML_START_ELEMENT:
                continue
            nm, ar = self.attrs(o)
            if nm != tag:
                continue
            for a in ar:
                if a['ns'] == RES_NO_NAMESPACE and self.strings[a['name']] == name:
                    struct.pack_into('<I', self.b, a['off'] + 8, idx)      # rawValue
                    self.b[a['off'] + 15] = TYPE_STRING                    # Res_value.dataType
                    struct.pack_into('<I', self.b, a['off'] + 16, idx)     # Res_value.data
                    return idx
        raise LookupError("no non-namespaced attribute %s on <%s>" % (name, tag))

    def build_cdata(self, text, line=1):
        """RES_XML_CDATA chunk, 28 B: node header(16) + ResStringPool_ref index u32 +
        padding u32 + trailing u32. Byte-identical in shape to what aapt2 writes for the
        <signature> text in framework-res res/xml/config_webview_packages.xml (verified)."""
        idx = self.intern(text)
        c = pack('<HHI', RES_XML_CDATA, 16, 28)
        c += pack('<II', line, RES_NULL_VALUE)
        c += pack('<III', idx, 0, 0)
        return c

    def text_values(self):
        """Every element-text (CDATA) string, in document order."""
        return [self.strings[u32(self.b, o + 16)] for typ, o, size in self.chunks
                if typ == RES_XML_CDATA]

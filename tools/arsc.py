#!/usr/bin/env python3
"""resources.arsc (ResTable) reader, verified against real Android 9 aapt2 output.

Why this exists: the WebView-provider fix is a static RRO, and a static RRO is an APK whose
resources.arsc names the *target* package's resource IDs. To build one here without aapt2 I need to
know, byte for byte, how a working Android 9 overlay encodes an `res/xml/...` override. This reads
that back out of files aapt2 actually produced (/vendor/overlay/*.apk on an Android 9 host) instead
of reconstructing it from documentation.

Structures per frameworks/native/libs/binder/include/binder/ResourceTypes.h as implemented in
tools/axml.py's style: every chunk starts with {u16 type, u16 headerSize, u32 size}.

Chunk types used here:
  0x0001 ResStringPool_header      0x0002 ResTable_header
  0x0200 ResTable_package          0x0201 ResTable_type
  0x0202 ResTable_spec             0x0203 ResTable_library
"""
import struct, sys

RES_STRING_POOL, RES_TABLE = 0x0001, 0x0002
RES_PACKAGE, RES_TYPE, RES_SPEC, RES_LIBRARY = 0x0200, 0x0201, 0x0202, 0x0203

TYPE_NULL, TYPE_REFERENCE, TYPE_ATTRIBUTE = 0x00, 0x01, 0x02
TYPE_STRING, TYPE_INLINE_BINARY, TYPE_COMPOUND_BINARY = 0x03, 0x0a, 0x0b
TYPE_INT_DEC, TYPE_INT_HEX, TYPE_INT_BOOLEAN = 16, 17, 18
VALUE_NAMES = {0: 'NULL', 1: 'REFERENCE', 2: 'ATTRIBUTE', 3: 'STRING', 4: 'FLOAT', 5: 'DIMENSION',
               6: 'FRACTION', 10: 'INLINE_BINARY', 11: 'COMPOUND_BINARY', 16: 'INT_DEC',
               17: 'INT_HEX', 18: 'INT_BOOLEAN', 7: 'SYSINT', 8: 'SYSINT64'}


def u16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def decode_strings(b, p, verbose=False):
    """ResStringPool at absolute offset p -> (list_of_strings, pool_size)."""
    hdr, size = u16(b, p + 2), u32(b, p + 4)
    count = u32(b, p + 8)
    flags = u32(b, p + 16)
    start = u32(b, p + 20)
    utf8 = bool(flags & 0x100)
    table, data = p + hdr, p + start
    out = []
    for i in range(count):
        q = data + u32(b, table + i * 4)
        if utf8:
            v = b[q]
            n, q = ((((v & 0x7F) << 8) | b[q + 1]), q + 2) if v & 0x80 else (v, q + 1)
            v = b[q]
            m, q = ((((v & 0x7F) << 8) | b[q + 1]), q + 2) if v & 0x80 else (v, q + 1)
            out.append(b[q:q + m].decode('utf-8', 'replace'))
        else:
            v = u16(b, q)
            if v & 0x8000:
                v = ((v & 0x7FFF) << 16) | u16(b, q + 2)
                q += 4
            else:
                q += 2
            out.append(b[q:q + v * 2].decode('utf-16-le', 'replace'))
    return out, size


def value(b, o, global_pool):
    """Res_value at absolute offset o -> printable form."""
    sz = u16(b, o)
    dt = b[o + 3]
    data = u32(b, o + 4)
    name = VALUE_NAMES.get(dt, str(dt))
    if dt == TYPE_STRING and global_pool is not None and data < len(global_pool):
        return 'STRING %r' % global_pool[data], data
    if dt == TYPE_REFERENCE:
        return 'REF 0x%08x' % data, data
    if dt == TYPE_INT_BOOLEAN:
        return 'BOOL %s' % (data != 0), data
    return '%s %d (0x%x)' % (name, data, data), data


class ARSC(object):
    def __init__(self, data):
        self.b = bytearray(data)
        if u16(self.b, 0) != RES_TABLE:
            raise ValueError('not a ResTable: root type 0x%04x' % u16(self.b, 0))
        self.pool_off = u32(self.b, 12) if False else 12
        # ResTable_header {chunk, u32 packageCount} then the global string pool
        self.package_count = u32(self.b, 8)
        self.hdr_size = u16(self.b, 2)
        self.global_strings, _ = decode_strings(self.b, self.hdr_size)
        self.packages = []          # [(pkg_id, name, offset, type_off, key_off)]
        o = self.hdr_size + u32(self.b, self.hdr_size + 4)
        while o + 8 <= len(self.b):
            t, h, s = u16(self.b, o), u16(self.b, o + 2), u32(self.b, o + 4)
            if s == 0:
                break
            if t == RES_PACKAGE:
                self._package(o)
            elif t in (RES_LIBRARY,):
                pass
            o += s

    def _package(self, o):
        # ResTable_package: chunk(8) id(u32) name(u16[128]) typeStrings(u32) lastPublicType(u32)
        #                   keyStrings(u32) lastPublicKey(u32) typeIdOffset(u32)  -> headerSize 288
        pkg_id = u32(self.b, o + 8)
        raw = self.b[o + 12:o + 12 + 256]
        end = raw.find(b'\x00\x00')
        name = raw[:end if end >= 0 else len(raw)].decode('utf-16-le', 'replace')
        type_off = u32(self.b, o + 268)
        key_off = u32(self.b, o + 276)
        keys, _ = decode_strings(self.b, o + key_off)
        types, _ = decode_strings(self.b, o + type_off)
        pkg = {'off': o, 'id': pkg_id, 'name': name, 'keys': keys, 'type_names': types,
               'size': u32(self.b, o + 4), 'entries': [], 'specs': []}
        self.packages.append(pkg)
        # walk inner chunks of the package
        p = o + u16(self.b, o + 2)
        end = o + pkg['size']
        while p + 8 <= end:
            t, h, s = u16(self.b, p), u16(self.b, p + 2), u32(self.b, p + 4)
            if s == 0 or p + s > end:
                break
            if t == RES_SPEC:
                self._spec(pkg, p)
            elif t == RES_TYPE:
                self._type(pkg, p)
            p += s

    def _spec(self, pkg, p):
        # ResTable_spec: chunk(8) id(1) flags(1) reserved(2) entryCount(4) then u32 flags array
        tid = self.b[p + 8]
        count = u32(self.b, p + 12)
        flags = [u32(self.b, p + 16 + i * 4) for i in range(count)]
        pkg['specs'].append({'type': tid, 'count': count, 'flags': flags})

    def _type(self, pkg, p):
        # ResTable_type: chunk(8) id(u8) flags(u8) reserved(u16) entryCount(u32)
        #                entriesStart(u32) ResTable_config  -> offsets at headerSize
        hdr = u16(self.b, p + 2)
        tid = self.b[p + 8]
        tflags = self.b[p + 9]
        count = u32(self.b, p + 12)
        estart = u32(self.b, p + 16)
        cfg_size = u32(self.b, p + 20)
        type_name = pkg['type_names'][tid - 1] if 0 < tid <= len(pkg['type_names']) else '?%d' % tid
        offs = [u32(self.b, p + hdr + i * 4) for i in range(count)]
        base = p + estart
        for i, off in enumerate(offs):
            e = base + off
            if off == 0xFFFFFFFF or e + 8 > len(self.b):
                pkg['entries'].append(None)
                continue
            esz = u16(self.b, e)
            eflags = u16(self.b, e + 2)
            key_idx = u32(self.b, e + 4)
            name = pkg['keys'][key_idx] if key_idx < len(pkg['keys']) else '?%d' % key_idx
            if esz != 8:               # ResTable_map_entry (style/public) has a wider header
                pkg['entries'].append({'type': tid, 'type_name': type_name, 'id': i, 'name': name,
                                       'flags': eflags, 'tflags': tflags, 'map': True,
                                       'esz': esz,
                                       'parent': u32(self.b, e + 8),
                                       'ncount': u32(self.b, e + 12) if esz >= 16 else 0})
                continue
            v, vdata = value(self.b, e + esz, self.global_strings)
            pkg['entries'].append({'type': tid, 'type_name': type_name, 'id': i, 'name': name,
                                   'flags': eflags, 'tflags': tflags, 'value': v, 'vdata': vdata,
                                   'vsz': esz, 'offset': e})

    def find(self, type_name, entry_name, pkg_id=None):
        out = []
        for pkg in self.packages:
            if pkg_id is not None and pkg['id'] != pkg_id:
                continue
            for ent in pkg['entries']:
                if ent and ent['type_name'] == type_name and ent['name'] == entry_name:
                    out.append((pkg['id'], pkg['name'], 0x01000000 * pkg['id'] + (ent['type'] << 16)
                                + ent['id'], ent))
        return out

    def dump(self, show_values=True):
        lines = []
        lines.append('ResTable %d B  packageCount=%d  global strings=%d'
                     % (len(self.b), self.package_count, len(self.global_strings)))
        for pkg in self.packages:
            lines.append(' package id=%d (0x%02x) name=%r  size=%d  keys=%d  types=%s'
                         % (pkg['id'], pkg['id'], pkg['name'], pkg['size'], len(pkg['keys']),
                            pkg['type_names']))
            bytype = {}
            for ent in pkg['entries']:
                if ent:
                    bytype.setdefault(ent['type_name'], []).append(ent)
            for tn in sorted(bytype):
                lines.append('   type %-22s %d entries' % (tn, len(bytype[tn])))
                if show_values:
                    for ent in bytype[tn][:200]:
                        rid = (pkg['id'] << 24) | (ent['type'] << 16) | ent['id']
                        val = ('MAP parent=0x%08x count=%d' % (ent['parent'], ent['ncount'])
                               if ent.get('map') else ent['value'])
                        lines.append('      [%3d] 0x%08x %-34s %s'
                                     % (ent['id'], rid, ent['name'], val))
                    if len(bytype[tn]) > 200:
                        lines.append('      ... %d more' % (len(bytype[tn]) - 200))
        return '\n'.join(lines)


def main(a):
    if len(a) < 2:
        print(__doc__)
        return 2
    import zipfile
    src = a[1]
    if src.endswith('.arsc'):
        data = open(src, 'rb').read()
    else:
        z = zipfile.ZipFile(src)
        data = z.read('resources.arsc')
    ar = ARSC(data)
    if len(a) > 2 and a[2] == 'find':
        for r in ar.find(a[3], a[4]):
            print('pkg=0x%02x %-18s id=0x%08x  %s' % (r[0], r[1], r[2], r[3]))
        return 0
    print(ar.dump(show_values=('values' in a)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))


# --------------------------------------------------------------------------- builder
# The shape below is not invented: it is a field-for-field copy of what aapt2 emits for a
# working Android 9 static RRO that overrides one res/xml file
# (/vendor/overlay/CarrierConfigResCommon.apk, resources.arsc = 592 B):
#   header(12) | global utf8 pool [<file path>] | package(288) { id=0x7f,
#   name=u16[128], typeStrings=288, lastPublicType=<ntypes>, keyStrings=288+sizeof(typePool),
#   lastPublicKey=<nkeys>, typeIdOffset=0 } | typeStrings pool ['attr','xml'] |
#   keyStrings pool [<entry>] | spec(id=1,entryCount=0) | spec(id=2,entryCount=1,[0]) |
#   type(id=2,hdr=84,config 64 B all-zero,entriesStart=88,offsets=[0],
#        entry{esz=8,flags=0,key=0}, ResValue{size=8,res0=0,type=TYPE_STRING,data=0})
def build_xml_override(overlay_package, entry_name, file_path,
                       type_name='xml', package_id=0x7f):
    from struct import pack as _p

    def chunk(typ, head, payload):
        """head = the chunk's own fields AFTER the 8-byte ResChunk_header; the result is
        headerSize = 8+len(head), and size = headerSize + len(payload)."""
        hdr = 8 + len(head)
        return _p('<HHI', typ, hdr, hdr + len(payload)) + head + payload

    def pool8(strings):
        blobs, offs = bytearray(), []
        for s in strings:
            offs.append(len(blobs))
            enc = s.encode('utf-8')
            cn, bn = len(s), len(enc)
            blobs += (_p('<BB', 0x80 | (cn >> 8), cn & 0xFF)) if cn >= 0x80 else _p('<B', cn)
            blobs += (_p('<BB', 0x80 | (bn >> 8), bn & 0xFF)) if bn >= 0x80 else _p('<B', bn)
            blobs += enc + b'\x00'
        blobs += b'\x00' * ((-len(blobs)) % 4)
        start = 28 + 4 * len(strings)
        head = _p('<IIII', len(strings), 0, 0x100, start) + _p('<I', 0)
        return chunk(0x0001, head, b''.join(_p('<I', o) for o in offs) + bytes(blobs))

    global_pool = pool8([file_path])
    type_names = ['attr', type_name]
    types_pool, keys_pool = pool8(type_names), pool8([entry_name])

    # spec header = chunk(8) + id/flags/reserved/entryCount(8) = 16; the u32 array is payload
    spec_attr = chunk(0x0202, _p('<BBHI', 1, 0, 0, 0), b'')
    spec_xml = chunk(0x0202, _p('<BBHI', 2, 0, 0, 1), _p('<I', 0))

    # type header = chunk(8) + id/flags/reserved/entryCount(8) + entriesStart(4)
    #               + ResTable_config(64, size=64, all-default) = 84
    # entriesStart is measured from the chunk start and lies PAST the offset array: 84 + 4*count.
    entry = _p('<HHI', 8, 0, 0) + _p('<HBB', 8, 0, TYPE_STRING) + _p('<I', 0)
    type_chunk = chunk(0x0201,
                       _p('<BBHI', 2, 0, 0, 1) + _p('<I', 88) + _p('<I', 64) + b'\x00' * 60,
                       _p('<I', 0) + entry)

    name = overlay_package.encode('utf-16-le')
    assert len(name) <= 254, 'overlay package name must be under 128 UTF-16 units'
    # package header = chunk(8) + id(4) + name u16[128](256) + 5 offsets(20) = 288
    ts_off, ks_off = 288, 288 + len(types_pool)
    package = chunk(0x0200,
                    _p('<I', package_id) + name + b'\x00' * (256 - len(name)) +
                    _p('<I', ts_off) + _p('<I', len(type_names)) + _p('<I', ks_off) +
                    _p('<I', 1) + _p('<I', 0),
                    types_pool + keys_pool + spec_attr + spec_xml + type_chunk)
    return chunk(0x0002, _p('<I', 1), global_pool + package)

#!/usr/bin/env python3
"""Inspect a PSMF (.pmf): header fields, every 2048-byte pack, the H.264 NAL
mix, and the stamped PES.  Writes the elementary stream to <file>.264.

    python tools/logo/pmf_inspect.py FILE.pmf [-v]

How tools/logo/make_icon1.py was matched to a Sony-authored PSMF, and how
its output is checked: the header bytes 0x50..0x92, the pack structure
(system header + 0xBF access-unit table at each GOP, one PES per pack,
padding at a GOP's end) and the NAL sequence (AUD, SEI, slice) should read
the same as the reference's.
"""
import sys, struct, collections
d = open(sys.argv[1], 'rb').read()
verbose = len(sys.argv) > 2
print('header', d[:8], 'off', hex(struct.unpack('>I', d[8:12])[0]), 'size', struct.unpack('>I', d[12:16])[0], 'file', len(d))
print('hdr 0x50..0xA0', d[0x50:0xA0].hex(' '))
p = 0x800
packs = 0
streams = collections.Counter()
es = bytearray()
pes_list = []
def ts(b):
    return ((b[0] >> 1) & 7) << 30 | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)
while p < len(d):
    assert d[p:p+4] == b'\x00\x00\x01\xba', (hex(p), d[p:p+4])
    pk = d[p:p+2048]
    scr = pk[4:10]; mux = (pk[10] << 14 | pk[11] << 6 | pk[12] >> 2)
    stuff = pk[13] & 7
    q = 14 + stuff
    items = []
    while q < 2048:
        if pk[q:q+3] != b'\x00\x00\x01':
            items.append(('GARBAGE@%d' % q,)); break
        sid = pk[q+3]; ln = struct.unpack('>H', pk[q+4:q+6])[0]
        body = pk[q+6:q+6+ln]
        streams[hex(sid)] += 1
        info = [hex(sid), ln]
        if sid == 0xE0:
            f1, f2, hl = body[0], body[1], body[2]
            hdr = body[3:3+hl]
            pts = dts = None
            if f2 & 0x80: pts = ts(hdr[0:5])
            if f2 & 0x40: dts = ts(hdr[5:10])
            info += ['f1=%02x f2=%02x hl=%d' % (f1, f2, hl), 'pts', pts, 'dts', dts, 'ext', hdr.hex()]
            es += body[3+hl:]
            pes_list.append((p, pts, dts, ln))
        elif sid == 0xBF:
            info += [body[:40].hex(' ')]
        items.append(info)
        q += 6 + ln
    if verbose or packs < 3 or any(i[0] in ('0xbf', '0xbb') for i in items):
        print('pack', packs, hex(p), 'mux', mux, 'stuff', stuff, items)
    packs += 1
    p += 2048
print('packs', packs, streams)
# NAL types
i = 0; nals = []
while True:
    j = es.find(b'\x00\x00\x01', i)
    if j < 0: break
    nals.append(es[j+3] & 0x1f); i = j + 3
c = collections.Counter(nals)
print('nal types', c)
print('first 30 nal seq', nals[:30])
print('pes with pts', sum(1 for x in pes_list if x[1] is not None), 'first ptss', [(x[1], x[2]) for x in pes_list if x[1] is not None][:6])
open(sys.argv[1] + '.264', 'wb').write(es)

#!/usr/bin/env python3
"""Minimal PNG decoder (8-bit RGB/RGBA/gray/palette, non-interlaced) returning exact stored bytes (no gamma/ICC)."""
import zlib, struct
def read_png(path):
    b = open(path, "rb").read()
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8; idat = b""; plte = None; w = h = 0; ct = 0
    while pos < len(b):
        ln, typ = struct.unpack(">I4s", b[pos:pos + 8]); data = b[pos + 8:pos + 8 + ln]; pos += 12 + ln
        if typ == b"IHDR":
            w, h, bd, ct, _, _, il = struct.unpack(">IIBBBBB", data); assert bd == 8 and il == 0, (bd, il)
        elif typ == b"PLTE": plte = data
        elif typ == b"IDAT": idat += data
        elif typ == b"IEND": break
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(idat); stride = w * ch; out = bytearray(); prev = bytearray(stride); i = 0
    for _ in range(h):
        f = raw[i]; i += 1; line = bytearray(raw[i:i + stride]); i += stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0; bb = prev[x]; c = prev[x - ch] if x >= ch else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + bb) & 255
            elif f == 3: line[x] = (line[x] + ((a + bb) >> 1)) & 255
            elif f == 4:
                p = a + bb - c; pa, pb, pc = abs(p - a), abs(p - bb), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else bb if pb <= pc else c)) & 255
        out += line; prev = line
    def px(x, y):
        o = (y * w + x) * ch
        if ct == 3: r, g, bl = plte[out[o] * 3:out[o] * 3 + 3]; return (r, g, bl, 255)
        if ct == 0: return (out[o], out[o], out[o], 255)
        if ct == 4: return (out[o], out[o], out[o], out[o + 1])
        if ct == 2: return (out[o], out[o + 1], out[o + 2], 255)
        return (out[o], out[o + 1], out[o + 2], out[o + 3])
    return w, h, px

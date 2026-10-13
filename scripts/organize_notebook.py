"""Verified nested nTop chunk codec. Use ntop_container for top-level I/O."""
import struct
MAGIC=b"MAGIC@@9"
HEADER=128

class Chunk:
    def __init__(self, typ, name, payload, children=None, prefix=b""):
        self.typ, self.name, self.payload, self.children, self.prefix = typ, name, payload, children, prefix

    def serialize(self) -> bytes:
        if self.children is not None:
            body = self.prefix + b"".join(c.serialize() for c in self.children)
        else:
            body = self.payload
        head = MAGIC + self.typ.encode().ljust(16, b"\0") + self.name.encode().ljust(16, b"\0") + struct.pack("<Q", len(body))
        return head.ljust(HEADER, b"\0") + body

    def find(self, name, typ=None):
        if self.name == name and (typ is None or self.typ == typ):
            return self
        for c in self.children or []:
            r = c.find(name, typ)
            if r is not None:
                return r
        return None

def parse_chunks(buf: bytes, start: int, end: int) -> list[Chunk]:
    out = []
    pos = start
    while pos < end:
        assert buf[pos:pos + 8] == MAGIC, "no chunk marker at %d" % pos
        typ = buf[pos + 8:pos + 24].rstrip(b"\0").decode()
        name = buf[pos + 24:pos + 40].rstrip(b"\0").decode()
        size = struct.unpack("<Q", buf[pos + 40:pos + 48])[0]
        p0, p1 = pos + HEADER, pos + HEADER + size
        if typ == "ntopfn":
            out.append(Chunk(typ, name, None, parse_chunks(buf, p0, p1)))
        elif typ == "obj_container":
            prefix = buf[p0:p0 + 8]
            out.append(Chunk(typ, name, None, parse_chunks(buf, p0 + 8, p1), prefix))
        else:
            out.append(Chunk(typ, name, buf[p0:p1]))
        pos = p1
    return out

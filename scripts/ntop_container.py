"""Read and write measured nTop containers with a dynamic top-level table.

The table starts at byte 24. Each of N entries contains a 16-byte name and
an 8-byte payload-relative end offset. An opaque 80-byte trailer follows
the table. Preserve the trailer and prefix; change the count at bytes 8:16
only when the number of chunks changes. Nested chunks use the retained
project vendor implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

_VENDOR = Path(__file__).resolve().parent
sys.path.insert(0, str(_VENDOR))
from organize_notebook import Chunk, parse_chunks  # noqa: E402

MAGIC = b"MAGIC%$1"
CHUNK_MAGIC = b"MAGIC@@9"
PREFIX_SIZE = 24
ENTRY_SIZE = 24
TRAILER_SIZE = 80


def _header_parts(header: bytes | bytearray) -> tuple[int, bytes, bytes]:
    if len(header) < PREFIX_SIZE + TRAILER_SIZE or header[:8] != MAGIC:
        raise ValueError("Not a supported nTop container header")
    count = struct.unpack_from("<Q", header, 8)[0]
    expected_size = PREFIX_SIZE + ENTRY_SIZE * count + TRAILER_SIZE
    if count == 0 or expected_size != len(header):
        raise ValueError("Unsupported top-level count or header length")
    return count, bytes(header[:PREFIX_SIZE]), bytes(header[-TRAILER_SIZE:])


def _name_bytes(name: str) -> bytes:
    encoded = name.encode("utf-8")
    if not encoded or len(encoded) > 16 or b"\0" in encoded:
        raise ValueError(f"Unsupported top-level chunk name: {name!r}")
    return encoded.ljust(16, b"\0")


def _read_bytes(raw: bytes) -> tuple[bytearray, list[Chunk]]:
    if len(raw) < PREFIX_SIZE + TRAILER_SIZE or raw[:8] != MAGIC:
        raise ValueError("Not a supported nTop container")
    count = struct.unpack_from("<Q", raw, 8)[0]
    first = PREFIX_SIZE + ENTRY_SIZE * count + TRAILER_SIZE
    if first >= len(raw) or raw.find(CHUNK_MAGIC) != first:
        raise ValueError("Unknown table/trailer layout or missing first chunk")
    header = bytearray(raw[:first])
    _header_parts(header)
    try:
        chunks = parse_chunks(raw, first, len(raw))
    except (AssertionError, UnicodeDecodeError, struct.error) as exc:
        raise ValueError("Malformed nTop chunk structure") from exc
    if len(chunks) != count or len({c.name for c in chunks}) != count:
        raise ValueError("Top-level chunk count mismatch or duplicate name")
    end = 0
    for index, chunk in enumerate(chunks):
        serialized = chunk.serialize()
        if raw[first + end:first + end + len(serialized)] != serialized:
            raise ValueError("Chunk has an unsupported non-exact vendor encoding")
        end += len(serialized)
        at = PREFIX_SIZE + ENTRY_SIZE * index
        expected = _name_bytes(chunk.name) + struct.pack("<Q", end)
        if bytes(header[at:at + ENTRY_SIZE]) != expected:
            raise ValueError("Chunk table names, order, or offsets do not match payload")
    if first + end != len(raw):
        raise ValueError("Unparsed trailing bytes")
    return header, chunks


def read(path: str | Path) -> tuple[bytearray, list[Chunk]]:
    """Read a supported file; reject schemas that cannot round-trip exactly."""
    return _read_bytes(Path(path).read_bytes())


def write(header: bytes | bytearray, chunks: list[Chunk]) -> bytes:
    """Rebuild the dynamic table without mutating the caller's header/chunks."""
    _, prefix, trailer = _header_parts(header)
    if not chunks or len({c.name for c in chunks}) != len(chunks):
        raise ValueError("Top-level chunks must have distinct nonempty names")
    new_prefix = bytearray(prefix)
    struct.pack_into("<Q", new_prefix, 8, len(chunks))
    table, payloads, end = [], [], 0
    for chunk in chunks:
        data = chunk.serialize()
        end += len(data)
        table.append(_name_bytes(chunk.name) + struct.pack("<Q", end))
        payloads.append(data)
    return b"".join([bytes(new_prefix), *table, trailer, *payloads])


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = []
    for path in args.paths:
        raw = path.read_bytes()
        header, chunks = _read_bytes(raw)
        output = write(header, chunks)
        if raw != output:
            raise AssertionError(f"Byte-exact round trip failed: {path}")
        count, prefix, trailer = _header_parts(header)
        rows.append({
            "path": str(path.resolve()), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "chunk_count": count,
            "first_chunk": len(header),
            "formula": f"24 + 24 * {count} + 80 = {len(header)}",
            "prefix_hex": prefix.hex(), "trailer_hex": trailer.hex(),
            "chunk_names": [c.name for c in chunks], "byte_exact_roundtrip": True,
        })

    # Exercise adding an imported definition without changing the input file.
    header, chunks = read(args.paths[0])
    prefix_before, trailer_before = bytes(header[:24]), bytes(header[-80:])
    test_name = "roundtrip_probe"
    if any(c.name == test_name for c in chunks):
        raise ValueError("Probe name conflicts with a source chunk")
    enlarged = write(header, [*chunks, Chunk("json", test_name, b"{}")])
    new_header, new_chunks = _read_bytes(enlarged)
    assert len(new_chunks) == len(chunks) + 1
    assert new_header[:8] == prefix_before[:8]
    assert new_header[16:24] == prefix_before[16:24]
    assert new_header[-80:] == trailer_before
    assert write(new_header, new_chunks[:-1]) == args.paths[0].read_bytes()

    rejected = []
    for label, position in (("wrong_count", 8), ("wrong_table_offset", 40)):
        bad = bytearray(args.paths[0].read_bytes())
        bad[position] ^= 1
        try:
            _read_bytes(bytes(bad))
        except ValueError:
            rejected.append(label)
        else:
            raise AssertionError(f"Malformed container accepted: {label}")

    report = {
        "passed": True, "files": rows,
        "add_remove_chunk_roundtrip": True,
        "prefix_preserved_except_count_when_resized": True,
        "opaque_80_byte_trailer_preserved": True,
        "malformed_containers_rejected": rejected,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

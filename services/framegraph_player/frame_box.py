#!/usr/bin/env python3
"""The `.frame` payload inside a .frame.mp4 -- read and write.

The graph rides in a top-level ISO-BMFF `uuid` box appended after `mdat`. That
is the container's own extension point: every conforming parser reads the box
header, does not recognise the UUID, and skips it. QuickTime plays the file,
ffprobe ignores the box, and we get it back byte-for-byte.

The alternative was an iTunes `----` freeform atom, which needs mutagen and is
not installed. This needs nothing but the standard library.

A re-encode still drops it -- ffmpeg rewrites the box list -- so a .frame.mp4 is
a transport artifact, never the source of truth.
"""
import gzip, json, struct

# Any 16 bytes work; readable ones make a hex dump self-explaining.
FRAME_UUID = b"framegraphstate1"          # exactly 16 bytes
MAGIC = b"FRM1"


def write(path, manifest):
    """Append the manifest to an existing mp4. Idempotent: strips a prior box."""
    with open(path, "rb") as f:
        data = strip(f.read())
    body = MAGIC + gzip.compress(json.dumps(manifest, separators=(",", ":")).encode(), 9)
    payload = FRAME_UUID + body
    size = 8 + len(payload)
    if size >= 2 ** 32:                    # 64-bit box form, for absurd manifests
        box = struct.pack(">I4sQ", 1, b"uuid", size + 8) + payload
    else:
        box = struct.pack(">I4s", size, b"uuid") + payload
    with open(path, "wb") as f:
        f.write(data + box)
    return len(box)


def read(path):
    """Return the manifest, or None if this is an ordinary mp4."""
    with open(path, "rb") as f:
        data = f.read()
    box = _find(data)
    if box is None:
        return None
    body = data[box[0] + box[1]:box[0] + box[2]]
    if not body.startswith(MAGIC):
        return None
    return json.loads(gzip.decompress(body[len(MAGIC):]))


def strip(data):
    box = _find(data)
    if box is None:
        return data
    start, _, size = box
    return data[:start] + data[start + size:]


def _find(data):
    """Walk top-level boxes. Returns (offset, header_len, size) of ours."""
    off = 0
    n = len(data)
    while off + 8 <= n:
        size = struct.unpack(">I", data[off:off + 4])[0]
        typ = data[off + 4:off + 8]
        head = 8
        if size == 1:                      # 64-bit largesize
            if off + 16 > n:
                break
            size = struct.unpack(">Q", data[off + 8:off + 16])[0]
            head = 16
        elif size == 0:                    # extends to EOF
            size = n - off
        if size < head or off + size > n:
            break
        if typ == b"uuid" and data[off + head:off + head + 16] == FRAME_UUID:
            return off, head + 16, size
        off += size
    return None


if __name__ == "__main__":
    import sys
    m = read(sys.argv[1])
    print(json.dumps(m, indent=2)[:2000] if m else "no .frame payload")

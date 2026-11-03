#!/usr/bin/env python3
"""Rebuild a patched pipensx NRO from the pristine 1.4.1 release.

Usage: build.py SOURCE.nro [OUTPUT.nro]

Every patch site is checked against its expected bytes before writing, the
output size must stay identical to the input, and no byte outside the declared
windows may change. The script refuses to run on an unexpected source build.
"""
import hashlib
import struct
import sys
from pathlib import Path

SOURCE_SHA256 = "b491f423576f214e7912fbefe26071ec7217a4c540a629a7e1a272db7b56b144"
VERSION = b"1.6.3"


def branch(src: int, dst: int) -> int:
    return 0x14000000 | (((dst - src) // 4) & 0x03FFFFFF)


def blade(src: int, dst: int) -> int:
    return 0x94000000 | (((dst - src) // 4) & 0x03FFFFFF)


def expect(buf: bytes, offset: int, want: bytes, label: str) -> None:
    got = buf[offset:offset + len(want)]
    if got != want:
        sys.exit(f"{label} at 0x{offset:x}: expected {want.hex()}, found {got.hex()}")


def patch(raw: bytes) -> bytes:
    b = bytearray(raw)

    # 1. Install journal: drop the target before rename. The Switch FAT32
    #    driver returns EEXIST instead of replacing an existing file.
    expect(b, 0x70E18, bytes.fromhex("811a40f9e06b40f9d8dc0b94"), "journal callsite")
    expect(b, 0x386E70, b"\x00" * 24, "journal cave")
    tramp = [
        0xF9401A80,                    # ldr  x0, [x20, #0x30]
        blade(0x386E74, 0x35F940),     # bl   remove
        0xF9401A81,                    # ldr  x1, [x20, #0x30]
        0xF9406BE0,                    # ldr  x0, [sp, #0xd0]
        blade(0x386E80, 0x368180),     # bl   rename
        branch(0x386E84, 0x070E24),    # b    0x70e24
    ]
    b[0x386E70:0x386E88] = b"".join(struct.pack("<I", i) for i in tramp)
    b[0x70E18:0x70E24] = struct.pack("<3I", branch(0x70E18, 0x386E70), 0xD503201F, 0xD503201F)

    # 2. Accept any magnet link, not only RuTracker trackers.
    expect(b, 0x0DBE9C, bytes.fromhex("e01900b4"), "tracker gate")
    b[0x0DBE9C:0x0DBEA0] = struct.pack("<I", 0xD503201F)

    # 3. Request the receive buffer the console actually grants.
    expect(b, 0x03438C, bytes.fromhex("8100a052"), "rcvbuf")
    b[0x03438C:0x034390] = struct.pack("<I", 0x52A00041)

    # 4. Never call the removed upstream repository.
    expect(b, 0x3AD130, b"h", "release url")
    b[0x3AD130] = 0
    expect(b, 0x5A7A8, bytes.fromhex("e0df40f9"), "url load")
    b[0x5A7A8:0x5A7AC] = struct.pack("<I", 0xD503201F)  # x0 = xzr -> ""

    # 5. Report one version everywhere it is visible.
    expect(b, 0x3ACB30, b"pipensx/1.4.1", "user agent")
    b[0x3ACB30:0x3ACB3D] = b"pipensx/" + VERSION
    nro_size = struct.unpack_from("<I", raw, 0x18)[0]
    nacp = nro_size + struct.unpack_from("<Q", raw, nro_size + 24)[0]
    expect(b, nacp + 0x3060, b"1.4.1", "nacp version")
    b[nacp + 0x3060:nacp + 0x3060 + len(VERSION)] = VERSION

    if len(b) != len(raw):
        sys.exit(f"size changed: {len(b)} != {len(raw)}")
    allowed = [(0x03438C, 0x034390), (0x070E18, 0x070E24), (0x0DBE9C, 0x0DBEA0),
               (0x386E70, 0x386E88), (0x3ACB30, 0x3ACB3D), (0x3AD130, 0x3AD131),
               (0x5A7A8, 0x5A7AC),
               (nacp + 0x3060, nacp + 0x3060 + len(VERSION))]
    for i in range(len(raw)):
        if raw[i] != b[i] and not any(lo <= i < hi for lo, hi in allowed):
            sys.exit(f"unexpected change at 0x{i:x}")
    return bytes(b)


def self_check() -> None:
    """Trampoline encoding must survive a decode/encode round trip."""
    for src, dst in ((0x386E74, 0x35F940), (0x386E80, 0x368180)):
        ins = blade(src, dst)
        assert (ins & 0xFC000000) == 0x94000000, hex(ins)
        off = ins & 0x03FFFFFF
        if off & 0x02000000:
            off -= 0x04000000
        assert src + (off << 2) == dst, hex(ins)
    assert struct.pack("<I", 0x52A00041).hex() == "4100a052"  # mov w1, #0x20000


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit(__doc__)
    source, output = Path(argv[1]), Path(argv[2] if len(argv) > 2 else argv[1].replace(".nro", "-patched.nro"))
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        sys.exit(f"source hash mismatch: {digest}")
    self_check()
    patched = patch(raw)
    output.write_bytes(patched)
    print(f"{output} {len(patched)} bytes")
    print(f"sha256 {hashlib.sha256(patched).hexdigest()}")


if __name__ == "__main__":
    main(sys.argv)

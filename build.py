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
MOUNT_LOG_CAVE = 0x386E40   # logging trampoline, 68 bytes
JOURNAL_TRAMPOLINE = 0x386E90


def branch(src: int, dst: int) -> int:
    return 0x14000000 | (((dst - src) // 4) & 0x03FFFFFF)


def blade(src: int, dst: int) -> int:
    return 0x94000000 | (((dst - src) // 4) & 0x03FFFFFF)


def cbz_w(rt: int, src: int, dst: int) -> int:
    return 0x34000000 | ((((dst - src) // 4) & 0x7FFFF) << 5) | rt


NOP = 0xD503201F


MOUNT_CAVE = bytes.fromhex(
    "fd7bbea9"   # stp x29, x30, [sp, #-0x20]!
    "fd030091"   # mov x29, sp
    "f603002a"   # mov w22, w0
    "36010034"   # cbz w22, +4 (to success path)
    "bc66ff97"   # bl 0x360940            errno()
    "010040b9"   # ldr w1, [x0]
    "1a66ff97"   # bl 0x3606c0            strerror-ish -> x0
    "e30300aa"   # mov x3, x0
    "e2430191"   # add x2, sp, #0x50      helper's path buffer
    "21010090"   # adrp x1, 0x3aa000
    "21600991"   # add x1, x1, #0x258     "[storage] cannot open '%s': %s\n"
    "26aef297"   # bl 0x32704             log
    "e003162a"   # mov w0, w22
    "35343a9f"   # ldp x19, x20, [sp, #0x30]
    "fdfb42a9"   # ldp x29, x30, [sp, #0x20]
    "ff430991"   # add sp, sp, #0x250
    "c0035fd6"   # ret
)


def expect(buf: bytes, offset: int, want: bytes, label: str) -> None:
    got = buf[offset:offset + len(want)]
    if got != want:
        sys.exit(f"{label} at 0x{offset:x}: expected {want.hex()}, found {got.hex()}")


def patch(raw: bytes) -> bytes:
    b = bytearray(raw)

    # 1a. Install journal: the Switch FAT32 devoptab returns EEXIST instead of
    #     replacing, so rename first and only fall back to remove+retry on error.
    expect(b, 0x70E18, bytes.fromhex("811a40f9e06b40f9d8dc0b94"), "journal callsite")
    expect(b, MOUNT_LOG_CAVE, b"\x00" * 68, "mkdir log cave")
    expect(b, JOURNAL_TRAMPOLINE, b"\x00" * 41, "journal cave")
    b[MOUNT_LOG_CAVE:MOUNT_LOG_CAVE + len(MOUNT_CAVE)] = MOUNT_CAVE
    for site in (0x031298,):
        expect(b, site, bytes.fromhex("f35341a9"), "mkdir restore")
        b[site:site + 4] = struct.pack("<I", blade(site, MOUNT_LOG_CAVE))
    prog = struct.pack(
        "<10I",
        0xF9401A81,                                        # ldr x1, [x20, #0x30]
        0xF9406BE0,                                        # ldr x0, [sp, #0xd0]
        blade(JOURNAL_TRAMPOLINE + 8, 0x368180),           # bl rename
        cbz_w(0, JOURNAL_TRAMPOLINE + 12, JOURNAL_TRAMPOLINE + 40),
        0xF9401A80,                                        # ldr x0, [x20, #0x30]
        blade(JOURNAL_TRAMPOLINE + 20, 0x35F940),          # bl remove
        0xF9401A81,                                        # ldr x1, [x20, #0x30]
        0xF9406BE0,                                        # ldr x0, [sp, #0xd0]
        blade(JOURNAL_TRAMPOLINE + 32, 0x368180),          # bl rename
        branch(JOURNAL_TRAMPOLINE + 36, 0x070E24),
    )
    b[0x70E18:0x70E24] = struct.pack("<3I", branch(0x70E18, JOURNAL_TRAMPOLINE), NOP, NOP)
    b[JOURNAL_TRAMPOLINE:JOURNAL_TRAMPOLINE + len(prog)] = prog

    # 2. Accept any magnet link, not only RuTracker trackers.
    expect(b, 0x0DBE9C, bytes.fromhex("e01900b4"), "tracker gate")
    b[0x0DBE9C:0x0DBEA0] = struct.pack("<I", 0xD503201F)

    # 3. Request the receive buffer the console actually grants.
    expect(b, 0x03438C, bytes.fromhex("8100a052"), "rcvbuf")
    b[0x03438C:0x034390] = struct.pack("<I", 0x52A00041)

    # 4. Never call the removed upstream repository.
    expect(b, 0x3AD130, b"h", "release url")
    b[0x3AD130] = 0

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
               (0x031298, 0x03129C), (0x031798, 0x03179C),
               (MOUNT_LOG_CAVE, MOUNT_LOG_CAVE + len(MOUNT_CAVE)),
               (JOURNAL_TRAMPOLINE, JOURNAL_TRAMPOLINE + 40),
               (0x3ACB30, 0x3ACB3D), (0x3AD130, 0x3AD131),
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

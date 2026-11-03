# pipensx-patch

Byte patches for the pipensx homebrew app store on Nintendo Switch (NRO 1.4.1,
AArch64/libnx). Five changes, verified by disassembly of the shipped binary.

## What it changes

| # | Site | Change | Why |
|---|------|--------|-----|
| 1 | `0x070e18` + cave `0x386e70` | `remove(target)` before `rename(tmp, target)` | The Switch FAT32 devoptab returns `EEXIST` when the destination exists, so every second journal checkpoint failed with `cannot rename install journal: File exists` |
| 2 | `0x0dbe9c` | `nop` instead of the tracker gate | The magnet parser rejected any link without a RuTracker tracker |
| 3 | `0x03438c` | ask for 128 KiB receive buffer instead of 256 KiB | The console refuses the larger request with `ENOBUFS` and falls back anyway |
| 4 | `0x55080`, `0x5a7a8`, `0x3ad130` | update check returns before the worker starts | `i3sey/pipensx` is gone; the check only produced `HTTP 404` and DNS timeouts |
| 5 | `0x3acb30`, NACP `+0x3060` | `pipensx/1.6.3` and `1.6.3` | User-Agent and the displayed version disagreed |

Total: 54 bytes in 10 regions. Icon, NACP body and RomFS are untouched.

## Build

```sh
python3 build.py pipensx.nro pipensx-patched.nro
```

The script verifies the SHA-256 of the source release, the expected bytes at
every site, that the output keeps the original size, and that no byte outside
the declared windows changed. Running it twice produces the same file.

## Not patched, on purpose

- **JSON guard before `nlohmann::json::parse` (`0xf6ec0`).** An earlier attempt
  jumped to a cave and clobbered `x1`, which the parser dereferences as
  `[x1, #0x10]` at `0x44b54`, so valid responses crashed. The failure path also
  skipped construction of the result object at `[sp, #0xc0]`, leaving the
  destructor at `0x4e780` to free garbage. The cause of the recorded
  `std::terminate` is still unknown — it needs a real backtrace, not a
  heuristic in front of the parser. The update worker is disabled instead.
- **Remap on `ENOENT` (`0x038eb0`).** It redirected any failed open into a flat
  `_files/` layout, and nothing in the binary restores the original paths. The
  paths in the log are 224 bytes with a 72-byte component, well inside the
  limits. The real reason `mkdir` fails is not established: the helper at
  `0x31220` discards every `mkdir` result.
- **512 MiB NAND reserve.** Unrelated to the reported symptoms.

## Caveats

Static verification only — nothing here was executed on a console. The build
has two runs in a 25 000-line log file (sessions 26–27): no crashes, no
`journal write failed`, no `ENOBUFS`, clean exits. Two open issues remain from
those logs: a `[storage] cannot open` fallback for Zelda port staging (2 lines),
and NCA hash mismatch warnings on one release that still installed. The journal
fix is not atomic: it deletes the target before renaming, so a crash in that
window costs one checkpoint (a re-verification), not installed content.

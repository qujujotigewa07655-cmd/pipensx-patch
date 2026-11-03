# pipensx-patch

Byte patches for the pipensx homebrew app store on Nintendo Switch (NRO 1.4.1,
AArch64/libnx). Five changes, verified by disassembly of the shipped binary.

## What it changes

| # | Site | Change | Why |
|---|------|--------|-----|
| 1 | `0x070e18` + cave `0x386e90` | `rename(tmp, target)`, on failure `remove(target)` and retry | The Switch FAT32 devoptab returns `EEXIST` when the destination exists, so every second journal checkpoint failed with `cannot rename install journal: File exists`. Retrying keeps the rename atomic when it succeeds |
| 1b | `0x031298` + cave `0x386e40` | log a failed `mkdir` with `errno` | The helper at `0x31220` discarded every `mkdir` result, so the download worker only reported a downstream `No such file or directory` |
| 2 | `0x0dbe9c` | `nop` instead of the tracker gate | The magnet parser rejected any link without a RuTracker tracker |
| 3 | `0x03438c` | ask for 128 KiB receive buffer instead of 256 KiB | The console refuses the larger request with `ENOBUFS` and falls back anyway |
| 4 | `0x3ad130` | first byte of the releases URL cleared | `i3sey/pipensx` is gone; the check only produced `HTTP 404` and DNS timeouts |
| 5 | `0x3acb30`, NACP `+0x3060` | `pipensx/1.6.3` and `1.6.3` | User-Agent and the displayed version disagreed |

Total: 126 bytes in 19 regions. Icon, NACP body and RomFS are untouched.

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
  heuristic in front of the parser.
- **Remap on `ENOENT` (`0x038eb0`).** It redirects any failed open into a flat
  `_files/` layout, and nothing in the binary restores the original paths. The
  paths in the log are 224 bytes with a 72-byte component, well inside the
  limits. The actual reason each directory was missing is now recoverable:
  the build logs a failed `mkdir` with `errno` (patch 1b), so the console
  log names the failing level instead of guessing.
- **512 MiB NAND reserve.** Unrelated to the reported symptoms.

## Caveats

Static verification only — nothing here was executed on a console. The previous
release has two runs in a 25 000-line log file (sessions 26–27): no crashes, no
`journal write failed`, no `ENOBUFS`, clean exits. Still open from those logs:
`[storage] cannot open` on Zelda port staging (2 lines) and `NCA hash mismatch`
warnings on one release that still installed. The journal retry keeps the
rename atomic on the common path; the fallback costs one checkpoint, not
installed content.

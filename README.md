# Moose Life – Resolution List Fix

Fixes the Moose Life (PC, Steam) launcher not offering high resolutions — 1440p, 4K — on modern GPUs
and displays. No EDID editing with CRU, no driver tricks, no second monitor.

**Before:** the resolution list stops well short of your display's native mode and the best you can pick
is a stretched low-res mode.
**After:** every resolution and refresh rate your display supports is listed (≥ 50 Hz, near-duplicate
refresh rates collapsed — that filtering is the game's own and unchanged). 3840×2160 @ 60 / 120 / 144 Hz
all appear and work.

It is the same bug as in Tempest 4000 (see the sibling project *Tempest4000-ResolutionFix*), in the
x64 OpenGL build of Moose Life. The fix is applied to **your own** `MooselifeGL.exe` (1 byte; a backup
is kept). No game files are redistributed here.

## Quick start (Windows)

1. Download the latest release zip and extract it anywhere.
2. Exit Steam.
3. Double-click **`ML-ResolutionFix.bat`**. It finds your Steam library, patches `MooselifeGL.exe`, and
   keeps a `MooselifeGL.exe.orig` backup.
4. Launch the game → pick your mode in the launcher list → **Start**. The choice is saved.

If the folder is not writable you will be told to run it as Administrator. If you get a Windows
SmartScreen prompt on a freshly downloaded `.bat`, choose *More info → Run anyway* — or run the `.ps1`
from a PowerShell window instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\ML-ResolutionFix.ps1
```

### Other ways to run it

| | |
|---|---|
| Report state, change nothing | `ML-ResolutionFix.bat -Check` |
| Undo (restore the backup) | `ML-ResolutionFix.bat -Restore` — or Steam → *Verify integrity of game files* |
| Explicit exe path | `ML-ResolutionFix.bat "F:\SteamLibrary\steamapps\common\Moose Life\MooselifeGL.exe"` |
| Also apply the optional width filter (see below) | `ML-ResolutionFix.bat -Filter` |
| Linux / Steam Deck / macOS | `python3 ml_resfix.py` (same options, lower-case: `--check`, `--restore`, `--filter`) |

The Python patcher needs `pip install pefile`. It locates the patch sites by code signature, so it can
also handle a build it has never seen (a future re-link?) — if it does, please open an issue with the
file's SHA-256 so it can be added to the known list. The Windows script only touches the known Steam
build (SHA-256 plus the exact bytes at every patch site) and refuses anything else.

**Steam Deck / Proton:** run the Python patcher from Desktop mode against
`~/.steam/steam/steamapps/common/Moose Life/MooselifeGL.exe` (it looks there by itself).

Note that *Verify integrity of game files* (and any future game update) restores the original exe —
just run the patcher again.

## What the bug is

The launcher dialog asks GLFW for the display's mode list (`glfwGetVideoModes`) and walks the returned
array to fill its listbox. The walk stops after the first **256 entries of the source array**:

```
0x14009dfe6  41 3b f6            cmp esi, r14d        ; esi = source index, r14d = 256
0x14009dfe9  0f 83 3b 01 00 00   jae <done>
```

That limit exists to protect a 256-entry string buffer on the stack (256 × 256 bytes of UTF-16, one
per listbox line) — but it is applied to the *input* index rather than to the number of *accepted*
entries. GLFW returns modes sorted ascending by size, so as soon as a display + GPU report more than
256 modes (a 4K TV over HDMI 2.1 on a current NVIDIA/AMD card easily does: every legacy resolution at
every refresh rate), the high-resolution end of the list is simply never looked at. Everything after
the launcher — prefs storage, the GLFW window/mode switch — handles any mode fine.

## What the patch does

**Part A — 1 byte (default).** `cmp esi, r14d` → `cmp ebp, r14d`: the cap now applies to the
accepted-entry count (`ebp`), which is what the buffer size actually constrains. Nothing can overflow
that was not already bounded; the `LB_ADDSTRING` loop after the walk was already clamped to 256.
This alone fixes the problem on real hardware (tested: RTX 5090 + LG G3, 3840×2160 @ 144 Hz).

**Part B — 6-byte hook + 32-byte code cave (optional, `-Filter` / `--filter`).** For systems that would
still produce more than 256 *accepted* modes (more than 256 modes at ≥ 50 Hz — very unusual): the
launcher's own `refresh ≥ 50 Hz` test is extended with `width ≥ target_width / 2`, where the target is
the mode the launcher itself is aiming for (your saved choice, otherwise the desktop mode), so the 256
slots are spent on the useful end of the list. The target mode always passes, so the list can never be
empty. The cave lives in the zero padding at the end of
`.text` and is position-independent (the exe is ASLR-enabled). Only use it if Part A alone still leaves
4K out of the list; the emulation results below show when it matters.

Full disassembly and how the patch was verified by emulating the game's own loop code:
[docs/TECHNICAL.md](docs/TECHNICAL.md).

## Supported build

| File | Link date | SHA-256 of original `MooselifeGL.exe` | after Part A | after A + B |
|---|---|---|---|---|
| `Moose Life\MooselifeGL.exe` (GL/OpenVR 1.06) | 2020-08-14 | `d78570b9 7a576117 3d297598 739b6201 a9d2449c 32ebb67d 12586a98 e570bd8c` | `e820fc53…dbff4a` | `854b8349…c858b6` |

This is the current Steam depot file. The Windows patcher refuses any other file; the Python patcher
will try to locate the patch sites by signature and refuses if they are not found exactly once.

## Verification

`tools/emu_test.py` runs the real x64 code of the launcher's mode loop under
[unicorn](https://www.unicorn-engine.org/) against synthetic GLFW mode lists, for original and patched
executables, and checks the outcome against what each build is supposed to do:

```
$ python3 tools/emu_test.py MooselifeGL.exe                       [original]
  small list: 18 res x 7 Hz (126 modes)          accepted= 90  4K@60 listed: True   ok
  real-world: 39 res x 12 Hz (468 modes)         accepted=105  4K@60 listed: False  ok (bug reproduced)
  stress: 1080 modes, more pass the filter ...   accepted=102  4K@60 listed: False  ok (bug reproduced)
$ python3 tools/emu_test.py MooselifeGL.exe                       [part A]
  small list: 18 res x 7 Hz (126 modes)          accepted= 90  4K@60 listed: True   ok
  real-world: 39 res x 12 Hz (468 modes)         accepted=195  4K@60 listed: True   ok
  stress: 1080 modes, more pass the filter ...   accepted=256  4K@60 listed: False  info (--filter fixes this)
$ python3 tools/emu_test.py MooselifeGL.exe                       [parts A+B]
  small list: 18 res x 7 Hz (126 modes)          accepted= 20  4K@60 listed: True   ok
  real-world: 39 res x 12 Hz (468 modes)         accepted= 80  4K@60 listed: True   ok
  stress: 1080 modes, more pass the filter ...   accepted=204  4K@60 listed: True   ok
```

Confirmed on real hardware (Part A): RTX 5090 + LG G3 (HDMI 2.1), 3840×2160 listed and running.

## FAQ

**Is this safe / a "crack"?** No DRM is involved — the Steam build is not wrapped — and the patch
does not touch anything except the launcher's mode-list loop. Steam still runs the game normally.

**The list shows 50 Hz, 60 Hz, 100 Hz … but not 59.94 Hz.** That is the game's own de-duplication
(refresh rates within 5 Hz of the previous entry for the same resolution are merged, keeping the
higher one). Unchanged by this patch.

**HDR?** Moose Life renders with OpenGL through GLFW; there is no HDR swap chain to enable, so this
patch does nothing about HDR one way or the other. Windows Auto HDR / NVIDIA RTX HDR behave as they do
for any other OpenGL game.

**Can this be fixed upstream?** Yes, trivially — Part A is a one-register change in the launcher's
loop. Llamasoft is welcome to it.

## Credits

* DrFluffyCatz — testing and publication of this fix.
* Reverse engineering, patch design and emulation testing done with Claude (Anthropic).

## License

MIT — see [LICENSE](LICENSE). Moose Life is © Llamasoft; this project contains no game files or code.

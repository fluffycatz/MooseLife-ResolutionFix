# Moose Life launcher resolution list — technical notes

Target: `MooselifeGL.exe`, Steam depot (app 1342740), 64-bit PE, MSVC 14.16 (VS2017 toolset), linked
2020-08-14, PDB path `F:\Llamasoft-Projects\games-PC\MooseLife-GL-Nuget\x64\Release\MooselifeGL.pdb`.
Window title `Llamasoft - Moose Life - GL/OpenVR 1.06`. No Steam DRM wrapper (no `.bind` section),
six plain sections, ASLR (`DYNAMIC_BASE` + `HIGH_ENTROPY_VA`) with a `.reloc` table, no CFG.

Rendering is OpenGL (`OPENGL32.dll`, `wglGetProcAddress`) through a statically linked GLFW 3
(`GLFW30` window class, `GLFW message window`), with optional OpenVR (`openvr_api.dll`). Display modes
come from GLFW's `glfwGetVideoModes`, which on Windows is `EnumDisplaySettingsExW` under the hood.

## The launcher dialog

Resource `RT_DIALOG` 130 is the launcher window (`SetWindowTextW(L"Llamasoft - Moose Life - GL/OpenVR
1.06")`): a `LISTBOX` (control id 2004 = `0x7d4`), a GDI+ bitmap, and a label with the desktop mode
(`L" %d X %d @%2.2f "`). Its `WM_INITDIALOG` handler starts around `0x14009ddc0`; the frame holds
`0x190` bytes of locals plus **256 × 0x100 bytes of UTF-16 strings** at `[rsp+0x190]`, one per listbox
line — that buffer is the reason for the 256 limit.

### WM_INITDIALOG — building the list

```
0x14009de99  call glfwGetPrimaryMonitor                 ; -> rsi
0x14009dea4  call glfwGetVideoMode(monitor)             ; desktop GLFWvidmode -> rbx
0x14009dea9  mov  r14d, 0x100                           ; the 256 limit
0x14009dee1  call swprintf_s(label, 0x100, L" %d X %d @%2.2f ", w, h, hz)
0x14009deeb  malloc(0x30) -> g_desired [0x1401b6f90]    ; GLFWvidmode desired @+0, copy of desktop @+0x18
0x14009df22  if prefs.w | prefs.h: desired = prefs mode (prefs+0x818 w, +0x81c h, +0x820 hz)
0x14009df52  call glfwGetVideoModes(monitor, &count)    ; -> r15 (GLFWvidmode[count], 24 bytes each)
0x14009df77  g_out [0x1401b6f98] = malloc(count * 24)   ; accepted modes
```

`GLFWvidmode` is `{ int width, height, redBits, greenBits, blueBits, refreshRate; }` — 24 bytes; the
refresh rate is an integer, so the loop below converts it to float for its comparisons.

### The loop (0x14009dfe6 – 0x14009e124)

Registers: `esi` = source index, `r14d` = 256, `ebp` = accepted count, `r12` = byte offset into `g_out`
(24 per entry), `r15` = source array, `r8d`/`r9d` = previous accepted width/height, `xmm6` = previous
accepted refresh rate, `edi` = best distance so far, `[rsp+0x70]`/`r13d` = best index, `xmm8` = 50.0,
`xmm9` = 5.0, `xmm10` = −1000.0, `xmm7` = the `fabs` mask.

```
0x14009dfe6  41 3b f6            cmp  esi, r14d              ; source index vs 256          <-- bug
0x14009dfe9  0f 83 3b 01 00 00   jae  0x14009e12a            ; -> done
0x14009dff5  mov  edx, [r15 + r14*8 + 0x14]                  ; refreshRate (r14 = idx*3 here)
0x14009e001  41 0f 2f d8         comiss xmm3, xmm8           ; refresh < 50.0 ?
0x14009e005  0f 82 0f 01 00 00   jb   0x14009e11a            ; -> skip
             ; de-dup: |refresh - prev| < 5.0 and refresh >= prev and same w/h
             ; -> back up one slot (dec ebp; r12 -= 24) and overwrite it
0x14009e073  call swprintf_s(str[ebp], 0x100, L"%u x %u @%-d Hz", w, h, hz)
0x14009e086  copy GLFWvidmode to g_out[r12]
0x14009e0a5  distance = |dw| + |dh| + 1000·|d refresh| against *desired; track best index (r13d)
0x14009e101  inc  ebp ; add r12, 24
0x14009e11a  skip: inc esi ; mov r14d, 0x100 ; cmp esi, count ; jb loop
0x14009e132  41 3b ee            cmp  ebp, r14d              ; ebp = min(accepted, 256)
0x14009e147  cmovg ebp, r14d
```

After the loop: `LB_ADDSTRING` (`0x180`) for each of the `ebp` strings, `LB_SETCURSEL` (`0x186`) to
the best match (`r13d`, also stored at `[0x140158c24]`), and if nothing matched the desktop mode is
copied into `g_out[0]`. The selected `GLFWvidmode` later goes into the prefs (`+0x818` w, `+0x81c` h,
`+0x820` hz) and is what the game opens its GLFW window with.

### Why the cap is wrong

The 256 limit protects the string buffer (and the `LB_ADDSTRING` loop already clamps to 256). But the
number of strings written is `ebp`, the *accepted* count, not `esi`. Applying the limit to the source
index means the walk quits after examining 256 raw modes — and because GLFW sorts modes ascending
(`compareVideoModes`: bit depth, then area, then width, then refresh rate), the entries it never reaches
are precisely the high resolutions. On a 4K TV + modern GPU (40 resolutions × 12 refresh rates is not
unusual) the 256th source entry is around the 21st-smallest resolution.

## The patch

### Part A (default) — 1 byte at file offset 0x9d3e6

```
41 3b f6   cmp esi, r14d      ->     41 3b ee   cmp ebp, r14d
```

Same opcode, different ModRM: the comparison is now against the accepted count, which is what the
string buffer size constrains. The clamp after the loop is unchanged, so `LB_ADDSTRING` still never
sees more than 256, and no store in the loop can go past slot 255 (the walk stops as soon as `ebp`
reaches 256). Note that `r14d` is reused as the index multiplier inside the loop body and reloaded
with 256 at `0x14009e11c` before the compare, so the operand is correct on every iteration.

### Part B (optional, `--filter`) — 6-byte hook at 0x9d405 + 32-byte cave at 0xed8f0

The `jb skip` after the 50 Hz `comiss` is replaced by `jmp cave; nop`. The cave (in the zero padding
at the end of `.text`, VA `0x1400ee4f0`, position-independent) is:

```
cave:  0f 82 <rel32>            jb   skip                    ; the original condition (refresh < 50)
       48 8b 05 <rel32>         mov  rax, [rip + g_desired]  ; GLFWvidmode* (desktop copy at +0x18, desired at +0)
       8b 00                    mov  eax, [rax]              ; desired width
       d1 e8                    shr  eax, 1                  ; / 2
       43 39 04 f7              cmp  [r15 + r14*8], eax      ; mode width < desired width / 2 ?
       0f 82 <rel32>            jb   skip
       e9 <rel32>               jmp  back                    ; 0x14009e00b, the instruction after the hook
```

`rax` is free at that point (it is rewritten before its next use at `0x14009e059`); flags are consumed
immediately by each `jb`. The desired mode is the prefs mode if one is stored, else the desktop mode —
in both cases a mode the user wants, so it always passes its own filter and the list can never end up
empty (e.g. a 1366×768 laptop panel keeps 683 px and up).

Part B only matters when more than 256 modes pass the 50 Hz filter, which real hardware seen so far
does not do; that is why it is off by default. The patchers apply it only with `-Filter` / `--filter`.

### Patch sites by signature

`ml_resfix.py` does not rely on fixed offsets: it finds `41 3b [f6|ee] 0f 83` (Part A, original or
already patched) and `41 0f 2f d8..df (0f 82 | e9)` (the Part B hook) in `.text`, each of which must
match exactly once, and computes the cave address from the section's virtual size. The desired-mode
pointer (`0x1401b6f90`) is the one hard-coded address; on any other build the signature search is
expected to fail loudly rather than patch the wrong place. The PowerShell/batch patcher is table-driven
on SHA-256 + exact bytes at every site and knows only the build above.

## Verification

`tools/emu_test.py` maps the executable at its preferred base with `pefile`, seeds the registers and
stack slots the loop expects (source array, count, `g_desired`, `g_out`, prefs override), stubs
`swprintf_s` at `0x14007d510`, and runs `0x14009df7c → 0x14009e15f` under unicorn. It then reads
back `ebp` and the 256 UTF-16 strings and checks what the launcher would list, for three synthetic mode
lists (small, "real-world" 4K TV, and a stress list where more than 256 modes pass the 50 Hz filter).
The expected outcome depends on the detected patch state (see the table in the script's docstring):
the original must reproduce the bug, Part A must fix the real-world case, and A+B must also fix the
stress case.

Confirmed on real hardware (Part A): RTX 5090 + LG G3 over HDMI 2.1, 3840×2160 listed and selectable.

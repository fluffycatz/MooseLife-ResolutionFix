# Changelog

## 1.0.0 — 2026-09-25

First release.

* Part A (default): cap the launcher's mode walk on accepted entries instead of source entries — the
  actual bug, a 1-byte change.
* Part B (`-Filter` / `--filter`, optional): position-independent code cave adding a
  `width >= target_width / 2` filter for the unusual case of more than 256 modes at >= 50 Hz.
* Windows patcher (`ML-ResolutionFix.bat` / `.ps1`, no dependencies, known build only) and
  cross-platform Python patcher (`ml_resfix.py`, signature-based) with `--check`, `--restore`, `--filter`.
* Supports the Steam build `MooselifeGL.exe` GL/OpenVR 1.06 (2020-08-14).
* Emulation test harness (`tools/emu_test.py`).

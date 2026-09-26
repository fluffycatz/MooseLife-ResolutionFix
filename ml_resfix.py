#!/usr/bin/env python3
"""
Moose Life (PC, Steam) launcher resolution-list fix.

The launcher walks the array returned by glfwGetVideoModes() to fill its resolution list, but
its early-exit compares the *source* index against 256 instead of the number of entries it has
*accepted*. GLFW lists modes ascending by size, so on a display/GPU that reports more than 256
modes the high resolutions are never reached. Same bug as in Tempest 4000, in the x64 OpenGL build.

Part A (1 byte, default):  cmp esi,r14d  ->  cmp ebp,r14d   (compare the accepted count, not the
                           source index; the 256-slot string buffer stays protected).
Part B (--filter, optional): a small code cave adds "width >= desktop width / 2" to the existing
                           "refresh >= 50 Hz" filter, so that even a pathological list of more
                           than 256 accepted modes spends its slots on the useful end.

Usage
  python3 ml_resfix.py                       # find the Steam install and patch it
  python3 ml_resfix.py --check               # report state only
  python3 ml_resfix.py --restore             # put MooselifeGL.exe.orig back
  python3 ml_resfix.py --filter              # apply part B as well
  python3 ml_resfix.py "C:\\...\\Moose Life\\MooselifeGL.exe"

Requires: pip install pefile
"""
import sys, os, re, struct, hashlib, shutil, glob

KNOWN = {
    "d78570b97a5761173d297598739b6201a9d2449c32ebb67d12586a98e570bd8c": "Steam MooselifeGL.exe (GL/OpenVR 1.06, 2020-08-14) - original",
    "e820fc53e0886588b025e2ed4c505d7902e012a0326ff5c6eb356ea185dbff4a": "Steam MooselifeGL.exe - part A applied",
    "854b8349f78a8337c5a76a6a40121cb672f4f2319a16f76f7785b956f0c858b6": "Steam MooselifeGL.exe - parts A+B applied",
}

def sha256(data): return hashlib.sha256(data).hexdigest()

def locate(path):
    """Find the patch sites by code signature (works on the known build and should on close relatives)."""
    import pefile
    pe = pefile.PE(path); base = pe.OPTIONAL_HEADER.ImageBase; img = bytes(pe.get_memory_mapped_image())
    t = [s for s in pe.sections if s.Name.startswith(b'.text')][0]; t0 = t.VirtualAddress
    off = lambda va: pe.get_offset_from_rva(va - base)
    code = img[t0:t0 + t.Misc_VirtualSize]
    R = {'base': base}
    # Part A: cmp esi,r14d ; jae rel32  (41 3b f6 0f 83) -- or the patched form cmp ebp,r14d
    ma = [m.start() for m in re.finditer(rb'\x41\x3b[\xf6\xee]\x0f\x83', code)]
    if len(ma) != 1: raise LookupError("part A site not uniquely found (%d matches)" % len(ma))
    R['A'] = base + t0 + ma[0]; R['A_off'] = off(R['A'])
    # Part B hook: comiss xmm3,xmm8 ; jb rel32 (the 'refresh >= 50 Hz' test), or the patched jmp
    mb = [m.start() for m in re.finditer(rb'\x41\x0f\x2f[\xd8-\xdf](?:\x0f\x82|\xe9)', code)]
    if len(mb) != 1: raise LookupError("part B hook site not uniquely found (%d matches)" % len(mb))
    comiss = base + t0 + mb[0]; jb = comiss + 4
    R['B_jb'] = jb; R['B_jb_off'] = off(jb); R['B_back'] = jb + 6
    if code[mb[0] + 4] == 0x0f: R['B_skip'] = jb + 6 + struct.unpack_from('<i', code, mb[0] + 6)[0]
    else:                        # already patched: read the skip target back out of the cave's first jb
        cave = jb + 5 + struct.unpack_from('<i', code, mb[0] + 5)[0]
        R['B_skip'] = cave + 6 + struct.unpack_from('<i', img, cave - base + 2)[0]
    # pointer to the desired/desktop mode (GLFWvidmode*): the loop reads its width for the filter.
    # Found via the instruction 'mov rax,[rip+disp]' that precedes 'cmp [r15+r14*8],eax'-style tests in
    # the original loop; on the known build it is the qword at RVA 0x1b6f90.
    R['G_desired'] = base + 0x1b6f90
    pad = t.VirtualAddress + t.Misc_VirtualSize
    R['cave'] = base + ((pad + 15) & ~15); R['cave_off'] = off(R['cave'])
    R['cave_room'] = (t.VirtualAddress + t.SizeOfRawData) - (R['cave'] - base)
    return R

def _rel(frm_end, to): return struct.pack('<i', to - frm_end)

def build(R, part_b):
    rows = [(R['A_off'], bytes.fromhex('413bf6'), bytes.fromhex('413bee'))]
    if part_b:
        old = b'\x0f\x82' + _rel(R['B_jb'] + 6, R['B_skip'])
        new = b'\xe9' + _rel(R['B_jb'] + 5, R['cave']) + b'\x90'
        rows.append((R['B_jb_off'], old, new))
        c = b''; a = R['cave']
        c += b'\x0f\x82' + _rel(a + len(c) + 6, R['B_skip'])                     # jb skip   (refresh < 50 Hz)
        c += b'\x48\x8b\x05' + struct.pack('<i', R['G_desired'] - (a + len(c) + 7))  # mov rax,[rip+disp] (desired mode ptr)
        c += b'\x8b\x00'                                                         # mov eax,[rax]      (desktop width)
        c += b'\xd1\xe8'                                                         # shr eax,1
        c += b'\x43\x39\x04\xf7'                                                 # cmp [r15+r14*8],eax (mode width)
        c += b'\x0f\x82' + _rel(a + len(c) + 6, R['B_skip'])                     # jb skip   (width < desktop/2)
        c += b'\xe9' + _rel(a + len(c) + 5, R['B_back'])                         # jmp back into the loop
        if len(c) > R['cave_room']: raise LookupError("no room for the code cave")
        rows.append((R['cave_off'], b'\x00' * len(c), c))
    return rows

def row_state(data, o, old, new):
    cur = bytes(data[o:o + len(old)])
    return 'orig' if cur == old else 'patched' if cur == new else 'unknown'

def steam_libraries():
    roots = []
    if sys.platform == 'win32':
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for v in ("SteamPath", "InstallPath"):
                            try: roots.append(winreg.QueryValueEx(k, v)[0].replace('/', '\\'))
                            except OSError: pass
                except OSError: pass
        except ImportError: pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        roots += [os.path.expanduser(p) for p in ("~/.steam/steam", "~/.local/share/Steam")]
    libs = []
    for r in roots:
        if not os.path.isdir(r): continue
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        if os.path.exists(vdf):
            libs += [m.group(1).replace('\\\\', '\\') for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, errors='ignore').read())]
    seen, out = set(), []
    for l in libs:
        if os.path.isdir(l) and l not in seen: seen.add(l); out.append(l)
    return out

def find_game_exes():
    found = []
    for lib in steam_libraries():
        for pat in ("steamapps/common/Moose Life*/MooselifeGL.exe", "steamapps/common/Moose Life*/*/MooselifeGL.exe"):
            found += glob.glob(os.path.join(lib, pat))
    return sorted(set(found))

def main(argv):
    flags = {a for a in argv if a.startswith('--')}
    paths = [a for a in argv if not a.startswith('--')]
    if '--help' in flags or '-h' in argv: print(__doc__); return 0
    if not paths:
        paths = find_game_exes()
        if not paths: print("MooselifeGL.exe not found in your Steam libraries - pass its path on the command line."); return 1
    rc = 0
    for path in paths:
        print("==", path)
        bak = path + ".orig"
        if '--restore' in flags:
            if os.path.exists(bak): shutil.copy2(bak, path); print("   restored from", bak)
            else: print("   no backup found; use Steam > Verify integrity of game files"); rc = 1
            continue
        data = bytearray(open(path, 'rb').read())
        print("   %s" % KNOWN.get(sha256(data), "unknown build (sha256 %s) - locating patch sites by signature" % sha256(data)[:16]))
        try:
            R = locate(path); rows = build(R, '--filter' in flags)
        except Exception as e:
            print("   cannot locate the patch sites:", e); rc = 1; continue
        states = [row_state(data, *r) for r in rows]
        print("   part A: %s%s" % (states[0], ("   part B (filter): %s" % ('patched' if states[1:] == ['patched', 'patched'] else 'orig' if states[1:] == ['orig', 'orig'] else 'unknown')) if len(rows) > 1 else ""))
        if '--check' in flags: continue
        if 'unknown' in states: print("   unexpected bytes at a patch site - refusing to touch this file"); rc = 1; continue
        if 'orig' not in states: print("   already patched - nothing to do"); continue
        if not os.path.exists(bak): shutil.copy2(path, bak); print("   backup:", bak)
        n = 0
        for (o, old, new), st in zip(rows, states):
            if st == 'orig': data[o:o + len(new)] = new; n += len(new)
        open(path, 'wb').write(data)
        print("   patched (%d bytes changed). sha256: %s" % (n, sha256(data)))
    return rc

if __name__ == "__main__": sys.exit(main(sys.argv[1:]))

"""
Emulation test for the Moose Life launcher mode loop (x64).

Runs the game's *real* code for the glfwGetVideoModes() walk under unicorn against synthetic mode
lists and reports what would appear in the launcher's resolution list. Works on the original exe
and on patched ones; the patch state is detected with ml_resfix.locate() and the expectations are
set accordingly:

  scenario                          original    part A       parts A+B
  small list (126 modes)            4K listed   4K listed    4K listed
  real-world (~470 source modes)    4K MISSING  4K listed    4K listed      <- the bug, and the fix
  stress (1080 source modes)        4K MISSING  4K MISSING*  4K listed      <- what --filter is for

  * informational: part A walks the whole list but the launcher's 256-slot buffer fills up with the
    small modes first; part B spends the slots on modes at least half the desktop width.

    pip install pefile unicorn
    python3 tools/emu_test.py path/to/MooselifeGL.exe

Exit status is non-zero when a build does not behave as the table says.
Addresses below are for the known Steam build (GL/OpenVR 1.06).
"""
import os, struct, sys
import pefile
from unicorn import *
from unicorn.x86_const import *

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ml_resfix

BASE = 0x140000000
START = 0x14009df7c      # mov ecx,[rsp+0x74]  (just before the walk-loop setup)
END   = 0x14009e15f      # after the ebp clamp, at GetDlgItem
SWPRINTF = 0x14007d510   # (buf, count, fmt, w, h, hz)  -> our stub
G_PREFS = 0x1401b6e90    # ptr to prefs struct (+0x818 w/h/hz override)
G_DESIRED = 0x1401b6f90  # ptr to desired GLFWvidmode
G_OUT = 0x1401b6f98      # ptr to output array

def vidmode(w,h,hz,r=8,g=8,b=8): return struct.pack('<6i', w,h,r,g,b,hz)  # GLFWvidmode = 24 bytes

def run(exe, modes, desktop=(3840,2160,60), prefs=None):
    pe = pefile.PE(exe); img = bytes(pe.get_memory_mapped_image())
    uc = Uc(UC_ARCH_X86, UC_MODE_64)
    size=(len(img)+0xfff)&~0xfff
    uc.mem_map(BASE, size+0x1000)
    uc.mem_write(BASE, img)
    STACK=0x10000000; uc.mem_map(STACK, 0x400000); RSP=STACK+0x200000
    HEAP=0x20000000; uc.mem_map(HEAP, 0x400000)
    src=HEAP; out=HEAP+0x100000; desired=HEAP+0x200000; prefsbuf=HEAP+0x300000
    n=len(modes)
    uc.mem_write(src, b''.join(modes))
    uc.mem_write(out, b'\0'*(n*24))
    uc.mem_write(desired, vidmode(*desktop))
    # prefs struct: zero, with optional +0x818 override
    pb=bytearray(0x900)
    if prefs: struct.pack_into('<3i', pb, 0x818, prefs[0], prefs[1], prefs[2])
    uc.mem_write(prefsbuf, bytes(pb))
    uc.mem_write(G_PREFS, struct.pack('<Q', prefsbuf))
    uc.mem_write(G_DESIRED, struct.pack('<Q', desired))
    uc.mem_write(G_OUT, struct.pack('<Q', out))
    uc.reg_write(UC_X86_REG_RSP, RSP)
    uc.reg_write(UC_X86_REG_RAX, out)     # stored to G_OUT at df83
    uc.reg_write(UC_X86_REG_R12, 0)
    uc.reg_write(UC_X86_REG_R13, 0)
    uc.reg_write(UC_X86_REG_R15, src)
    uc.reg_write(UC_X86_REG_R14, 0x100)
    uc.reg_write(UC_X86_REG_RSI, 0x1234)  # monitor handle (unused after our start)
    uc.mem_write(RSP+0x74, struct.pack('<I', n))    # source count
    uc.mem_write(RSP+0x70, struct.pack('<I', 0))    # best index
    uc.mem_write(RSP+0x80, struct.pack('<Q', 0))    # rdi save slot used at e12a
    def hook(uc,addr,sz,ud):
        if addr==SWPRINTF:
            buf=uc.reg_read(UC_X86_REG_RCX)
            w=uc.reg_read(UC_X86_REG_R9D)
            h=struct.unpack('<I',uc.mem_read(uc.reg_read(UC_X86_REG_RSP)+0x28,4))[0]
            hz=struct.unpack('<I',uc.mem_read(uc.reg_read(UC_X86_REG_RSP)+0x30,4))[0]
            s="%u x %u @%-d Hz"%(w,h,hz)
            uc.mem_write(buf, s.encode('utf-16-le')+b'\0\0')
            uc.reg_write(UC_X86_REG_RAX, len(s))
            # emulate 'ret'
            rsp=uc.reg_read(UC_X86_REG_RSP); ret=struct.unpack('<Q',uc.mem_read(rsp,8))[0]
            uc.reg_write(UC_X86_REG_RSP, rsp+8); uc.reg_write(UC_X86_REG_RIP, ret)
    uc.hook_add(UC_HOOK_CODE, hook, begin=SWPRINTF, end=SWPRINTF)
    uc.emu_start(START, END, count=20_000_000)
    ebp=uc.reg_read(UC_X86_REG_EBP)     # accepted (post-clamp)
    strings=[]
    for i in range(min(ebp,256)):
        raw=uc.mem_read(RSP+0x190+i*0x100,0x100)
        strings.append(raw.decode('utf-16-le','replace').split('\0')[0])
    return ebp, strings

def gl_modes(res, refreshes):
    """GLFW sorts modes ascending (area, then refresh); a small (w,h)-major sort is close enough here."""
    out=[]
    for (w,h) in sorted(res, key=lambda r: (r[0]*r[1], r[0])):
        for hz in sorted(refreshes):
            out.append(vidmode(w,h,hz))
    return out

RES=[(640,480),(720,480),(800,600),(1024,768),(1152,864),(1280,720),(1280,768),(1280,800),(1280,1024),
     (1360,768),(1366,768),(1440,900),(1600,900),(1680,1050),(1920,1080),(1920,1200),(2560,1440),(3840,2160)]
HZ=[24,30,50,60,100,120,144]

# "real-world": a 4K/144 panel on a modern GPU driver that enumerates a long list of scaled modes and
# every refresh rate for each of them: ~40 resolutions x 12 rates = ~470 source modes, of which the
# ones that pass the launcher's own filter fit in its 256-slot buffer. The original walks only the
# first 256 *source* entries (the 21 smallest resolutions) and never reaches 4K.
RES_RW = sorted(set(RES) | {(w, w * 9 // 16 // 8 * 8) for w in range(320, 3840, 160)} | {(2560, 1600), (3200, 1800), (3440, 1440)},
                key=lambda r: (r[0]*r[1], r[0]))[:40]
if (3840, 2160) not in RES_RW: RES_RW[-1] = (3840, 2160)
HZ_RW = [23, 24, 25, 29, 30, 48, 50, 59, 60, 100, 120, 144]

# "stress": more modes pass the 50 Hz filter than the launcher has slots for.
RES_BIG = sorted(set(RES) | {(320 + 8 * i, (320 + 8 * i) * 9 // 16 // 8 * 8) for i in range(0, 440, 8)} | {(5120, 2880), (7680, 4320)})
HZ_BIG = [23, 24, 25, 29, 30, 48, 50, 59, 60, 75, 100, 119, 120, 143, 144]

def patch_state(exe):
    R = ml_resfix.locate(exe)
    rows = ml_resfix.build(R, True)
    data = open(exe, 'rb').read()
    st = [ml_resfix.row_state(data, *r) for r in rows]
    a = st[0]; b = 'patched' if st[1:] == ['patched', 'patched'] else 'orig' if st[1:] == ['orig', 'orig'] else 'unknown'
    return a, b

if __name__ == "__main__":
    exe = sys.argv[1]
    a, b = patch_state(exe)
    label = {('orig', 'orig'): 'original', ('patched', 'orig'): 'part A', ('patched', 'patched'): 'parts A+B'}.get((a, b), 'unknown (A=%s, B=%s)' % (a, b))
    print("exe: %s  [%s]" % (exe, label))
    scenarios = [
        ("small list: %d res x %d Hz (%%d modes)" % (len(RES), len(HZ)), gl_modes(RES, HZ), {'original': True, 'part A': True, 'parts A+B': True}),
        ("real-world: %d res x %d Hz (%%d modes)" % (len(RES_RW), len(HZ_RW)), gl_modes(RES_RW, HZ_RW), {'original': False, 'part A': True, 'parts A+B': True}),
        ("stress: %d modes, more pass the filter than the 256 slots", gl_modes(RES_BIG, HZ_BIG), {'original': False, 'part A': None, 'parts A+B': True}),
    ]
    ok = True
    for name, modes, expect in scenarios:
        ebp, strings = run(exe, modes, desktop=(3840, 2160, 60), prefs=(3840, 2160, 60))
        has4k = any(s.startswith("3840 x 2160 @60") for s in strings)
        want = expect.get(label)
        if want is None: verdict = "info (A alone: buffer fills with small modes; --filter fixes this)"
        elif want == has4k: verdict = "ok" + (" (bug reproduced)" if not want else "")
        else: verdict = "UNEXPECTED"; ok = False
        if ebp == 0: verdict = "UNEXPECTED (nothing listed)"; ok = False
        print("  %-62s accepted=%3d  4K@60 listed: %-5s  %s" % (name % len(modes), ebp, has4k, verdict))
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)

#!/usr/bin/env python3
"""XLAT_FAULT_NOTE + GPSP_RUNTIME_LOG: the emulation-fault reset and the lazy
fourth translation try, in log/runtime.log (issue #10).

1. The core (cpu_threaded.c), production text: block_lookup_address_arm /
   _thumb (unchanged from the release), vram_or_badjump_* and badjump_recover
   with the XLAT_FAULT_NOTE block, linked against a scripted
   block_lookup_translate_* that begins each "translation" the way
   translate_block_* does (XFN_LAZY_ENTRY).  A lookup that works on the
   first tries stores nothing; the lazy fourth try is counted once, with its
   pc, ARM/Thumb and the translation caches' fill; a reset records why (no
   code can be at the pc, four failed tries, VRAM), the tries, the mode, the
   fills and the ROM cache's page loads, and counts a lazy try that did not
   save it; a reset no lookup described says mode "?".
2. The frontend (main_psp.c), production text: rtw_fault_note writes the
   reset's line with all of that; rtw_xlat_poll writes nothing in steady
   play, a line when the lazy try was used, and at most RTW_XFN_FREE lines
   before one a minute, the counts carried in the next line.
3. Where the calls stand: the lazy hook at the top of both translate_block_*,
   the reset's line where the game is reset (the "Emulation fault" toast),
   the poll once a frame beside it, all empty without the switches, and the
   pinned hot-order functions (block_lookup_*) untouched.
Then mutants against those production sites: each must fail a check.
No PSP SDK, device or firmware is involved.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CORE = (ROOT / "cpu_threaded.c").read_text(encoding="utf-8")
MAIN = (ROOT / "psp/main_psp.c").read_text(encoding="utf-8")
TOKENS = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'
                    r"'(?:\\.|[^'\\])*'|[{}]", re.S)


def braced(source, start):
    depth = 0
    for token in TOKENS.finditer(source, start):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return source[start:token.end()]
    raise AssertionError("unclosed block")


def between(source, head, tail):
    i = source.find(head)
    assert i >= 0, head + " not found"
    j = source.find(tail, i)
    assert j > i, tail + " not found"
    return source[i:j + len(tail)]


def func(source, signature):
    i = source.find(signature)
    assert i >= 0, signature + " not found"
    return braced(source, i)


CHECK = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
static int checks, failures;
#define CHECK(c) do { checks++; if (!(c)) { failures++; \
   fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
#define DONE(what) do { printf("%s: %d checks, %d failures\n", what, checks, \
   failures); return failures ? 1 : 0; } while (0)
'''

# ---------------------------------------------------------------- 1 ------
CORE_HARNESS = CHECK + r'''
typedef uint32_t u32; typedef uint16_t u16; typedef uint8_t u8;
#define function_cc
#define BLOCK_LOOKUP_UNMAPPABLE ((u8 *)(~0))
#define GBA_PC(x) ((x) & 0x0FFFFFFFu)
static u8 caches[2][4096];
static u8 *ram_translation_cache = caches[0], *rom_translation_cache = caches[1];
static u8 *ram_translation_ptr, *rom_translation_ptr;
static u32 gamepak_page_loads;
static u32 xlat_lazy_links;
#define XLAT_LAZY_LINKS_SET(v) (xlat_lazy_links = (v))
@XFN@
/* the lookup's world, as cpu_threaded.c has it with BADJUMP_SAFE + VRAM_EXEC */
#define DRPH_SCOPE(x)
#define STALE_SCAN(x)
#define BADJUMP_NOTE_PC(p)
#define JIT_CODE_CHECK_ENTRY(r)
#define DC_FILL_OK(pc) 0
#define DC_PUT(t, k, p) do { } while (0)
static void translate_icache_sync(void) {}
static void translate_icache_sync_ranged(void) {}
u32 reg[64];
#define REG_PC 15
#define REG_CPSR 16
static u8 bios_swi_entrypoint[4], good[4];
u32 badjump_recoveries, badjump_last_pc;
volatile u32 badjump_reset_pending;
/* scripted tries: 'g' good, 'n' failed, 'u' unmappable; 'N' failed after a
 * nested translation (a lazy try that translates twice inside) */
static const char *script;
static int calls;
static u8 *answer(u32 pc, u32 thumb)
{
   char c = script[calls++];
   XFN_LAZY_ENTRY(pc, thumb);                 /* translate_block_* begins */
   if (c == 'N') XFN_LAZY_ENTRY(pc, thumb);   /* ...and again, nested */
   return c == 'g' ? good : c == 'u' ? BLOCK_LOOKUP_UNMAPPABLE : NULL;
}
u8 *block_lookup_translate_arm(u32 pc) { return pc == 0 ? good : answer(pc, 0); }
u8 *block_lookup_translate_thumb(u32 pc) { return answer(pc, 1); }
static int vram_tries;
static u8 *vram_lookup_translate_arm(u32 pc, int t) { (void)pc; (void)t; vram_tries++; return NULL; }
static u8 *vram_lookup_translate_thumb(u32 pc, int t) { (void)pc; (void)t; vram_tries++; return NULL; }
@RECOVER@
@VRAM@
@LOOKUPS@
static xlat_fault_note *n = &xlat_fault_notes;
static u8 *run(int thumb, u32 pc, const char *s)
{
   script = s; calls = 0;
   return thumb ? block_lookup_address_thumb(pc) : block_lookup_address_arm(pc);
}
int main(void)
{
   ram_translation_ptr = ram_translation_cache + 100;
   rom_translation_ptr = rom_translation_cache + 3000;
   gamepak_page_loads = 77;

   /* first, or third, try works: nothing stored */
   CHECK(run(0, 0x08000100, "g") == good);
   CHECK(run(0, 0x08000200, "nng") == good);
   CHECK(n->lazy == 0 && n->resets == 0 && n->arm_thumb == 2);

   /* three failures, the lazy fourth works (Thumb): counted once */
   CHECK(run(1, 0x03006dd0, "nnng") == good);
   CHECK(n->lazy == 1 && n->lazy_failed == 0 && n->resets == 0);
   CHECK(n->lazy_pc == 0x03006dd0 && n->lazy_thumb == 1);
   CHECK(n->lazy_ram_fill == 100 && n->lazy_rom_fill == 3000);
   CHECK(xlat_lazy_links == 0);

   /* four failures, the lazy one translating twice inside: one lazy try,
    * then BADJUMP_SAFE resets and says why */
   ram_translation_ptr = ram_translation_cache + 4000;
   run(1, 0x03006dd0, "nnnN");
   CHECK(n->lazy == 2 && badjump_recoveries == 1 && badjump_reset_pending == 1);
   CHECK(n->resets == 1 && n->reset_pc == 0x03006dd0 && n->reset_thumb == 1);
   CHECK(n->reset_why == XFN_WHY_EXHAUSTED && n->reset_tries == 4);
   CHECK(n->reset_ram_fill == 4000 && n->reset_rom_fill == 3000);
   CHECK(n->reset_page_loads == 77 && n->lazy_failed == 1);
   CHECK(n->arm_why == XFN_WHY_OTHER && n->arm_thumb == 2);   /* taken */

   /* a pc no code can be at (BIOS_BOUND_FIX: above the BIOS), ARM: the
    * sentinel on the first try, no lazy try */
   run(0, 0x00004010, "u");
   CHECK(n->resets == 2 && n->reset_why == XFN_WHY_UNMAPPABLE);
   CHECK(n->reset_tries == 1 && n->reset_thumb == 0 && n->reset_pc == 0x00004010);
   CHECK(n->lazy == 2 && n->lazy_failed == 1);
   /* ...an unhandled region, Thumb */
   run(1, 0x01000000, "u");
   CHECK(n->resets == 3 && n->reset_why == XFN_WHY_UNMAPPABLE && n->reset_thumb == 1);
   /* the BIOS itself is code: four failures there are "exhausted" */
   run(0, 0x00000400, "nnnn");
   CHECK(n->resets == 4 && n->reset_why == XFN_WHY_EXHAUSTED && n->lazy_failed == 2);

   /* VRAM: the sentinel sends it to its own four tries */
   vram_tries = 0;
   run(0, 0x06001000, "u");
   CHECK(vram_tries == 4 && n->resets == 5 && n->reset_why == XFN_WHY_VRAM);
   CHECK(n->reset_tries == 4 && n->reset_thumb == 0 && n->lazy_failed == 2);

   /* a reset no lookup described */
   badjump_recover(0x08000000);
   CHECK(n->resets == 6 && n->reset_thumb == 2);
   DONE("xlat fault note: core (production)");
}
'''


def core_production(src):
    xfn = between(src, "#ifdef XLAT_FAULT_NOTE\n#include \"xlat_fault_note.h\"",
                  "#define XFN_TAKE(pc)                 ((void)0)\n#endif\n")
    rec = func(src, "static u8 *badjump_recover(u32 pc)\n{")
    vram = between(src, "#define vram_or_badjump_builder(type, thumb)",
                   "#define BADJUMP_EXHAUSTED_X(pc, type)  return vram_or_badjump_##type(pc)\n")
    look = "\n\n".join([func(src, "u8 function_cc *block_lookup_address_arm(u32 pc)\n{"),
                        func(src, "u8 function_cc *block_lookup_address_thumb(u32 pc)\n{")])
    return (CORE_HARNESS.replace("@XFN@", xfn).replace("@RECOVER@", rec)
            .replace("@VRAM@", vram).replace("@LOOKUPS@", look))


# ---------------------------------------------------------------- 2 ------
FE_HARNESS = CHECK + r'''
#include <stdarg.h>
typedef uint32_t u32;
static unsigned clk = 1000;
static unsigned sceKernelGetSystemTimeLow(void) { return clk; }
static unsigned frame;
static unsigned fe_host_frame_count(void) { return frame; }
u32 ram_translation_cache_size = 200, rom_translation_cache_size = 8000;
u32 gamepak_buffer_count = 9, gamepak_resident_got = 0;
u32 gamepak_size = 16u << 20, gamepak_page_loads = 1234;
static int lines;
static char last[1024];
static void rt_note(const char *fmt, ...)
{ va_list ap; va_start(ap, fmt); vsnprintf(last, sizeof(last), fmt, ap); va_end(ap); lines++; }
@FE@
xlat_fault_note xlat_fault_notes;
u32 badjump_last_pc;
int main(void)
{
   xlat_fault_note *x = &xlat_fault_notes;
   int i;

   /* the reset's line */
   x->reset_pc = 0x03006dd0; x->reset_thumb = 1; x->reset_why = XFN_WHY_EXHAUSTED;
   x->reset_tries = 4; x->lazy = 2; x->lazy_failed = 1;
   x->resets = 1; x->reset_ram_fill = 190; x->reset_rom_fill = 7000;
   x->reset_page_loads = 77; frame = 4242;
   RTW_FAULT_NOTE(2);
   CHECK(lines == 1);
   CHECK(strstr(last, "guest_fault n=2 pc=03006DD0 mode=thumb why=exhausted tries=4 action=reset") != NULL);
   CHECK(strstr(last, "lazy=2 lazy_failed=1 resets=1") != NULL);
   CHECK(strstr(last, "ram_fill=190/200 rom_fill=7000/8000") != NULL);
   CHECK(strstr(last, "rom_cache blocks=9 resident=0 rom_kb=16384 page_loads=77 frame=4242") != NULL);
   /* a reset nothing described */
   x->reset_thumb = 2; x->reset_why = XFN_WHY_OTHER;
   RTW_FAULT_NOTE(3);
   CHECK(lines == 2 && strstr(last, "mode=? why=other") != NULL);

   /* the poll: the lazy tries the reset came with are told once ... */
   x->lazy_pc = 0x03006dd0; x->lazy_thumb = 1;
   RTW_XLAT_POLL();
   CHECK(lines == 3 && strstr(last, "xlat_lazy n=2 (+2) failed=1 (+1) last pc=03006DD0 mode=thumb") != NULL);
   /* ... and steady play writes nothing: ten minutes of frames */
   for (i = 0; i < 36000; i++) { clk += 16667; RTW_XLAT_POLL(); }
   CHECK(lines == 3);
   /* one lazy try that worked is a line, with its own facts */
   x->lazy++; x->lazy_pc = 0x08001234; x->lazy_thumb = 0;
   x->lazy_ram_fill = 10; x->lazy_rom_fill = 20;
   clk += 16667; RTW_XLAT_POLL();
   CHECK(lines == 4 && strstr(last, "xlat_lazy n=3 (+1) failed=1 (+0)") != NULL);
   CHECK(strstr(last, "last pc=08001234 mode=arm ram_fill=10/200 rom_fill=20/8000 page_loads=1234") != NULL);
   /* a game that takes it every frame: RTW_XFN_FREE lines, then one a
    * minute, and that one carries what was not told */
   for (i = 0; i < 600; i++) { x->lazy++; clk += 16667; RTW_XLAT_POLL(); }
   CHECK(lines == 2 + (int)RTW_XFN_FREE);        /* the resets' lines + the poll's */
   clk += RTW_XFN_GAP_US;
   x->lazy++; RTW_XLAT_POLL();
   CHECK(lines == 2 + (int)RTW_XFN_FREE + 1);
   CHECK(strstr(last, "xlat_lazy n=604 (+") != NULL);
   DONE("xlat fault note: runtime.log lines (production)");
}
'''


def fe_production(src):
    return FE_HARNESS.replace("@FE@", between(src, "/* ---- RTW XLAT FAULTS",
                                                "/* ---- end RTW XLAT FAULTS */"))


def structure(src, core):
    out = []
    toast = re.search(r"if \(faults != faults_seen\)\n\s*\{\n(.*?)\n\s*\}", src, re.S)
    out.append(("the reset's line where the game is reset",
                bool(toast) and "RTW_FAULT_NOTE(faults);" in toast.group(1) and
                toast.group(1).find("RTW_FAULT_NOTE(faults);") <
                toast.group(1).find('osd_toast("Emulation fault')))
    out.append(("the poll once a frame beside it",
                re.search(r'osd_toast\("Emulation fault - game was reset"\);\n\s*\}\n'
                          r'\s*RTW_XLAT_POLL\(\);', src) is not None))
    out.append(("off is off: both empty without GPSP_RUNTIME_LOG",
                "#define RTW_FAULT_NOTE(n)  ((void)0)\n#define RTW_XLAT_POLL()    ((void)0)\n#endif"
                in src))
    for ty, th in (("arm", 0), ("thumb", 1)):
        body = func(core, "bool translate_block_%s(u32 pc, bool ram_region)\n{" % ty)
        out.append(("the lazy hook at the top of translate_block_%s" % ty,
                    "  %s_fix_pc();\n  XFN_LAZY_ENTRY(pc, %d);" % (ty, th) in body))
    out.append(("off is off in the core: the hooks are empty without the switch",
                "#define XFN_LAZY_ENTRY(pc, thumb)    do { } while (0)\n"
                "#define XFN_MODE(thumb)              ((void)0)" in core and
                "#define XFN_TAKE(pc)                 ((void)0)" in core))
    hot = "\n".join(func(core, s) for s in (
        "u8 function_cc *block_lookup_address_arm(u32 pc)\n{",
        "u8 function_cc *block_lookup_address_thumb(u32 pc)\n{",
        "u8 function_cc *block_lookup_address_dual(u32 pc)\n{"))
    hot += between(core, "#define block_lookup_translate_builder(type)",
                   "block_lookup_translate_builder(thumb);")
    out.append(("nothing in the pinned hot order", "XFN" not in hot))
    return out


def build_run(c_text, name):
    with tempfile.TemporaryDirectory(prefix="gbadhoc-xfn-") as d:
        cfile = Path(d) / (name + ".c")
        binary = Path(d) / name
        cfile.write_text(c_text)
        cc = subprocess.run(["cc", "-std=gnu99", "-O1", "-g", "-Wall", "-Wextra",
                             "-Werror", "-Wno-unused-function", "-Wno-unused-parameter",
                             "-DXLAT_FAULT_NOTE", "-DXLAT_LAST_TRY_LAZY",
                             "-DBADJUMP_SAFE", "-DBIOS_BOUND_FIX", "-DVRAM_EXEC",
                             "-DGPSP_RUNTIME_LOG",
                             "-I" + str(ROOT), "-I" + str(ROOT / "psp"),
                             str(cfile), "-o", str(binary)],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            return False, cc.stderr.strip().splitlines()[:6] or ["compile failed"]
        r = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
        return r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()


def run_all(main_src, core_src, expect):
    failed = []
    for name, text in (("core", core_production(core_src)),
                       ("frontend", fe_production(main_src))):
        ok, out = build_run(text, name)
        if expect:
            assert ok, name + ":\n" + "\n".join(out)
            print(out[-1])
        elif not ok:
            failed.append(name)
            print("   (%s: %s)" % (name, (out or ["?"])[0]))
    bad = [n for n, good in structure(main_src, core_src) if not good]
    if expect:
        assert not bad, "structure: " + ", ".join(bad)
    elif bad:
        failed.append("structure")
        print("   (structure: %s)" % ", ".join(bad))
    return failed


def main():
    run_all(MAIN, CORE, True)
    print("structure: %d checks pass" % len(structure(MAIN, CORE)))
    mutants = [
        ("core", "the lazy hook gone from translate_block_arm",
         "  arm_fix_pc();\n  XFN_LAZY_ENTRY(pc, 0);             /* XLAT_FAULT_NOTE only */\n",
         "  arm_fix_pc();\n"),
        ("core", "the lazy hook gone from translate_block_thumb",
         "  thumb_fix_pc();\n  XFN_LAZY_ENTRY(pc, 1);             /* XLAT_FAULT_NOTE only */\n",
         "  thumb_fix_pc();\n"),
        ("core", "a lazy try counted at each nested translation",
         "  xlat_lazy_links = 2;              /* once per try; still lazy */\n", ""),
        ("core", "the lookup's mode not given",
         "  XFN_MODE(thumb);                   /* XLAT_FAULT_NOTE only */               \\\n", ""),
        ("core", "the VRAM path not told apart",
         "  XFN_VRAM();                        /* XLAT_FAULT_NOTE only */               \\\n", ""),
        ("core", "BIOS_BOUND's pcs read as exhausted",
         "           (region == 0 && pc >= 0x4000) ||\n", ""),
        ("core", "the lazy failure never counted",
         "    n->lazy_failed++;               /* the lazy try did not save it */\n", ""),
        ("core", "the mode kept for the next reset",
         "  n->arm_thumb = 2;                 /* unknown until a lookup says */\n", ""),
        ("core", "badjump_recover takes nothing",
         "  XFN_TAKE(pc);                      /* XLAT_FAULT_NOTE only */\n", ""),
        ("core", "a hook in the pinned hot order",
         "    XLAT_LAZY_LINKS_SET(i == 3);\n    ret = block_lookup_translate_arm(pc);\n",
         "    XLAT_LAZY_LINKS_SET(i == 3);\n    XFN_MODE(0);\n    ret = block_lookup_translate_arm(pc);\n"),
        ("main", "the reset's line not written",
         "            RTW_FAULT_NOTE(faults);   /* GPSP_RUNTIME_LOG: why, and how full */\n", ""),
        ("main", "the poll not called",
         "         RTW_XLAT_POLL();             /* GPSP_RUNTIME_LOG: a compare a frame */\n", ""),
        ("main", "the poll writes every frame",
         "   if (!x || x->lazy == seen_lazy)\n      return;\n",
         "   if (!x)\n      return;\n"),
        ("main", "the poll's lines unbounded",
         "   if (lines >= RTW_XFN_FREE && now - last_us < RTW_XFN_GAP_US)\n",
         "   if (0 && lines >= RTW_XFN_FREE && now - last_us < RTW_XFN_GAP_US)\n"),
        ("main", "the reset's line without its mode",
         "n, (unsigned)x->reset_pc, rtw_xfn_mode(x->reset_thumb),",
         "n, (unsigned)x->reset_pc, rtw_xfn_mode(0),"),
    ]
    killed = 0
    for where, label, old, new in mutants:
        src = CORE if where == "core" else MAIN
        assert src.count(old) == 1, label + ": production text not found"
        bad = src.replace(old, new, 1)
        failed = run_all(bad if where == "main" else MAIN,
                         bad if where == "core" else CORE, False)
        if not failed:
            raise AssertionError("mutant survived: " + label)
        killed += 1
        print("mutant (%s): failed as it must" % label)
    print("%d mutants, all killed" % killed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""The 6 s stall recorder in the runtimelog build (MAGI f-005).

MAGI's proof (gbadhoc-sleep-refs/magi/wt-diag-runtime-log/proofs/
stall_overlay.py) ran the production stall_thread with g_loop_iter frozen
under the wake overlay / SELECT+TRIANGLE pause screen -- modal inside one
loop iteration -- and g_stall_s forced to 6 by GPSP_STALL_RECORDER: it wrote
a stall.txt record after 6 s, and after 8 such records the recorder is dead
for the session.

The runtimelog build needs the recorder's WORDS (g_loop_iter, g_loop_phase)
and its stall_line, not its thread: the runtime watchdog, which reads the
wake and sleep words, subsumes it.  So this runs the same scenario through
the PRODUCTION start path -- main()'s stall-watch setup block, then
stall_watch_start, then (if it starts one) the thread -- for each build:

  runtimelog (PLAYABLE + STALL_RECORDER + RUNTIME_LOG)   no thread, no record
  sleepdiag  (PLAYABLE)                                   no thread (compiled out)

and mutants: the runtimelog build forcing the 6 s recorder again must fail.
The bare GPSP_STALL_RECORDER bisect arm (without RUNTIME_LOG) is not a
profile this branch builds and is left as it was.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "psp/main_psp.c").read_text(encoding="utf-8")


def stall_block(src):
    """The stall watch's compile-time block (globals .. stall_watch_stop)."""
    i = src.find("/* ---- STALL WATCH (harness `stall_watch_s`; 0 = off, the default) ---")
    assert i >= 0, "stall watch block not found"
    j = src.find("static void stall_watch_stop(void)", i)
    assert j > i, "stall_watch_stop not found"
    head = src.rfind("#if ", 0, i)
    return src[head:j]


def setup_block(src):
    """main()'s stall-watch setup, as compiled into main."""
    head = ("#if !defined(GPSP_PLAYABLE) || defined(GPSP_KEEP_TELEMETRY) || \\\n"
            "    defined(GPSP_STALL_RECORDER)\n"
            "   g_stall_s = (int)fe_ini_get_int(HARNESS_INI, \"stall_watch_s\", 0);")
    i = src.find(head)
    assert i >= 0, "main()'s stall-watch setup not found"
    j = src.find("#endif\n#endif\n", i)
    assert j > i
    return src[i:j + len("#endif\n#endif\n")]


def only(src, name):
    """One function out of the stall block, by name."""
    m = re.search(r"^static (?:int|void) " + name + r"\(.*?\n\}\n", src, re.S | re.M)
    assert m, name + " not found"
    return m.group(0)


HARNESS = r'''
#include <stdio.h>
#include <string.h>
typedef unsigned SceSize;
typedef unsigned SceUInt;
typedef int SceUID;
#define THREAD_ATTR_USER 0x80000000u
#define HARNESS_INI "x/.playable-no-harness/x"
#define LOG_DIR "x/log"
#define fe_evt(...) ((void)0)
static volatile unsigned g_loop_iter = 1234;   /* frozen: the overlay is modal */
static volatile int g_wake_menu = 1;           /* pause screen / wake overlay up */
static int ticks, records, created;
static long fe_ini_get_int(const char *f, const char *k, long d) { (void)f; (void)k; return d; }
static int sceIoMkdir(const char *p, int m) { (void)p; (void)m; return 0; }
static void stall_record(unsigned it) { (void)it; records++; }
static volatile int *run_flag;
static void sceKernelDelayThread(unsigned us) { (void)us; if (++ticks > 10) *run_flag = 0; }
static int (*entry)(SceSize, void *);
static SceUID sceKernelCreateThread(const char *n, int (*f)(SceSize, void *), int p,
                                    int s, unsigned a, void *o)
{ (void)n; (void)p; (void)s; (void)a; (void)o; entry = f; created++; return 0x77; }
static int sceKernelStartThread(SceUID id, SceSize n, void *a)
{ (void)id; (void)n; (void)a; entry(0, NULL); return 0; }
static int sceKernelDeleteThread(SceUID id) { (void)id; return 0; }
@GLOBALS@
@THREAD@
@START@
int main(void)
{
#if !defined(GPSP_PLAYABLE) || defined(GPSP_KEEP_TELEMETRY) || defined(GPSP_STALL_RECORDER)
   run_flag = &g_stall_run;
#endif
   (void)g_wake_menu;
@SETUP@
   stall_watch_start();
   printf("threads=%d records=%d over %d s on the overlay\n", created, records,
          ticks ? ticks - 1 : 0);
   return records || created;
}
'''


def build(src, defines):
    blk = stall_block(src)
    # the globals: everything in the block before the first function
    first = re.search(r"^static int stall_refer\(", blk, re.M)
    assert first, "stall_refer not found"
    globals_ = blk[:first.start()]
    start = re.search(r"^static void stall_watch_start\(void\)\n\{.*?\n\}\n", blk,
                      re.S | re.M)
    assert start, "stall_watch_start not found"
    text = (HARNESS.replace("@GLOBALS@", globals_ + "\n#endif\n")
                   .replace("@THREAD@", "#if !defined(GPSP_PLAYABLE) || "
                            "defined(GPSP_KEEP_TELEMETRY) || defined(GPSP_STALL_RECORDER)\n"
                            + only(blk, "stall_thread") + start.group(0) +
                            "#else\n#define stall_watch_start() do { } while (0)\n#endif\n")
                   .replace("@START@", "")
                   .replace("@SETUP@", setup_block(src)))
    with tempfile.TemporaryDirectory(prefix="gbadhoc-stallrec-") as d:
        c = Path(d) / "h.c"
        b = Path(d) / "h"
        c.write_text(text)
        subprocess.run(["cc", "-std=gnu99", "-w", "-o", str(b), str(c)] + defines,
                       check=True)
        r = subprocess.run([str(b)], capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout.strip()


RUNTIMELOG = ["-DGPSP_PLAYABLE", "-DGPSP_STALL_RECORDER", "-DGPSP_RUNTIME_LOG"]
SLEEPDIAG = ["-DGPSP_PLAYABLE"]


def main():
    rc, out = build(MAIN, RUNTIMELOG)
    print("runtimelog: " + out)
    assert rc == 0, "runtimelog: the 6 s recorder ran on the overlay"
    rc, out = build(MAIN, SLEEPDIAG)
    print("sleepdiag: " + out)
    assert rc == 0, "sleepdiag: a recorder ran"
    # MUTANT: the runtimelog build forces the 6 s recorder again
    old = "#if defined(GPSP_STALL_RECORDER) && !defined(GPSP_RUNTIME_LOG)\n"
    assert MAIN.count(old) == 1, "the runtimelog gate on the 6 s recorder not found"
    bad = MAIN.replace(old, "#ifdef GPSP_STALL_RECORDER\n", 1)
    rc, out = build(bad, RUNTIMELOG)
    assert rc != 0, "mutant survived: 6 s recorder forced in runtimelog"
    print("mutant (runtimelog forces the 6 s recorder): %s -- failed as it must" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

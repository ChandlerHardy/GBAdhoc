#!/usr/bin/env python3
"""GPSP_RUNTIME_LOG: the runtime watchdog's decision and its production wiring.

1. psp/rt_watch.c, linked as shipped: when a counter that is expected to move
   has been still for more than 2 s an episode begins (once), slots join it
   (once each) and it ends (once), by a real move or by no longer being
   expected; a slot that is not expected never stalls; a late tick is capped.
2. main_psp.c's own rtw_expect / rtw_sample / rtw_tick, extracted verbatim
   and linked with the real rt_watch.c: the suppression comes from the REAL
   sleep handshake words (g_pwr_sleep_pending, park_req / ack / parked, the
   quiesce, the wake overlay), and while a sleep is in force the watchdog
   writes NOTHING.
3. The call sites: the production audio worker and writer loops bump their
   counters, the writer's .sav pass is counted and fenced by the sceIo marks,
   the exit callback stamps and wakes the watchdog, the power callback's
   stamp records the wake, LOOP_TOP is the main loop's first statement, the
   build refuses GPSP_RUNTIME_LOG without the stall recorder, every teardown
   step has its begin and end, and every process exit stops the watchdog.
Then mutants against those production call sites: each must fail a check.
No PSP SDK, device or firmware is involved.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rtlog_paths  # noqa: E402  (the MAGI-review harnesses)

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "psp/main_psp.c").read_text(encoding="utf-8")
WATCH_C = ROOT / "psp/rt_watch.c"
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


def fn(source, name):
    m = re.search(r"^static (?:inline )?[A-Za-z_ ]+?\b" + name +
                  r"\([^;]*?\)\s*\{", source, re.M)
    assert m, "production function not found: " + name
    return braced(source, m.start())


def line(source, pattern):
    m = re.search(pattern, source, re.M)
    assert m, pattern + " not found"
    return m.group(0)


def between(source, head, tail):
    i = source.find(head)
    assert i >= 0, head + " not found"
    j = source.find(tail, i)
    assert j > i, tail + " not found"
    return source[i:j + len(tail)]


def build_run(c_text, name, expect_pass=True, extra=(), defines=()):
    with tempfile.TemporaryDirectory(prefix="gbadhoc-rtlog-") as d:
        cfile = Path(d) / (name + ".c")
        binary = Path(d) / name
        cfile.write_text(c_text)
        cc = subprocess.run(["cc", "-std=gnu99", "-O1", "-g", "-Wall", "-Wextra",
                             "-Werror", "-Wno-unused-function",
                             "-I" + str(ROOT / "psp")] + list(defines) +
                            [str(cfile)] + [str(x) for x in extra] +
                            ["-o", str(binary)], capture_output=True, text=True)
        if cc.returncode != 0:
            if expect_pass:
                raise AssertionError(name + ": compile failed\n" + cc.stderr)
            return cc
        r = subprocess.run([str(binary)], capture_output=True, text=True,
                           timeout=60)
        if (r.returncode == 0) != expect_pass:
            raise AssertionError("%s: expected %s\n%s%s" % (
                name, "pass" if expect_pass else "failure", r.stdout, r.stderr))
        return r


CHECK = r'''
#include <stdio.h>
#include <string.h>
static int checks, failures;
#define CHECK(c) do { checks++; if (!(c)) { failures++; \
   fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
#define DONE(what) do { printf("%s: %d checks, %d failures\n", what, checks, \
   failures); return failures ? 1 : 0; } while (0)
'''

# ---------------------------------------------------------------- 1 ------
DECISION = CHECK + r'''
#include "rt_watch.h"
static unsigned c[RTW_SLOTS];
static rtw_state s;
static unsigned step(unsigned expect, unsigned dt) { return rtw_step(&s, c, expect, dt); }
static void bump(unsigned mask)
{
   int i;
   for (i = 0; i < RTW_SLOTS; i++)
      if (mask & RTW_BIT(i))
         c[i]++;
}
int main(void)
{
   const unsigned M = RTW_BIT(RTW_MAIN), A = RTW_BIT(RTW_AUDIO);
   const unsigned ALL = RTW_ALL, REST = ALL & ~(M | A);
   char names[64];
   int i;

   rtw_reset(&s);
   CHECK(step(ALL, 1000) == 0 && s.primed);          /* priming only samples */
   /* Exactly 2.0 s still is not yet a stall ("> 2 s"); 3 s is. */
   bump(ALL & ~M);
   CHECK(step(ALL, 1000) == 0);
   bump(ALL & ~M);
   CHECK(step(ALL, 1000) == 0 && s.age_ms[RTW_MAIN] == 2000 && s.stalled == 0);
   bump(ALL & ~M);
   CHECK(step(ALL, 1000) == RTW_EV_STALL);
   CHECK(s.fresh == M && s.stalled == M && s.reported == M);
   CHECK(s.episodes == 1 && s.episode_ms == 3000);
   CHECK(s.age_ms[RTW_AUDIO] == 0);                    /* moving: age 0 */
   /* ONCE per episode: still stuck, nothing more to say. */
   bump(ALL & ~M);
   CHECK(step(ALL, 1000) == 0);
   /* audio joins: one GROW naming only the newcomer. */
   bump(REST);
   CHECK(step(ALL, 1000) == 0);                         /* audio 1 s */
   bump(REST);
   CHECK(step(ALL, 1000) == 0);                         /* audio 2 s */
   bump(REST);
   CHECK(step(ALL, 1000) == RTW_EV_GROW && s.fresh == A && s.stalled == (M | A));
   bump(REST);
   CHECK(step(ALL, 1000) == 0);                         /* told once */
   /* audio moves again: the episode goes on (main is still stuck). */
   bump(REST | A);
   CHECK(step(ALL, 1000) == 0 && s.stalled == M);
   /* main moves: the episode ends, by a move. */
   bump(ALL);
   CHECK(step(ALL, 1000) == RTW_EV_CLEAR);
   CHECK(s.moved & M && s.dropped == 0 && s.stalled == 0);
   CHECK(s.episode_ms == 3000 + 7000);
   /* A second episode is a new one, reported again. */
   for (i = 0; i < 3; i++)
   {
      c[RTW_AUDIO]++; c[RTW_IO]++; c[RTW_ME]++; c[RTW_HOME]++;
      if (i < 2) CHECK(step(ALL, 1000) == 0);
      else       CHECK(step(ALL, 1000) == RTW_EV_STALL && s.episodes == 2);
   }
   /* No longer expected (a sleep, the menu's overlay): dropped, not moved. */
   CHECK(step(ALL & ~M, 1000) == RTW_EV_CLEAR);
   CHECK(s.dropped == M && (s.moved & M) == 0 && s.stalled == 0);
   /* A slot that is not expected never stalls, however long. */
   rtw_reset(&s);
   CHECK(step(0, 1000) == 0);
   for (i = 0; i < 20; i++)
      CHECK(step(0, 1000) == 0);
   CHECK(s.stalled == 0 && s.episodes == 0);
   /* Not-expected time does not count once it is expected again. */
   CHECK(step(M, 1000) == 0 && s.age_ms[RTW_MAIN] == 1000);
   /* A late tick (the watchdog itself held off) is capped. */
   rtw_reset(&s);
   CHECK(step(M, 0) == 0);
   CHECK(step(M, 10000) == 0 && s.age_ms[RTW_MAIN] == RTW_DT_CAP_MS);
   CHECK(step(M, 1000) == RTW_EV_STALL);
   /* A counter that wraps still moved. */
   rtw_reset(&s);
   c[RTW_MAIN] = 0xFFFFFFFFu;
   CHECK(step(M, 1000) == 0);
   for (i = 0; i < 6; i++)
   {
      c[RTW_MAIN]++;
      CHECK(step(M, 1000) == 0);
   }
   CHECK(s.stalled == 0);
   /* Names. */
   rtw_mask_names(names, sizeof(names), M | A | RTW_BIT(RTW_HOME));
   CHECK(strcmp(names, "main+audio+home") == 0);
   rtw_mask_names(names, sizeof(names), 0);
   CHECK(strcmp(names, "-") == 0);
   rtw_mask_names(names, 6, ALL);
   CHECK(strlen(names) == 5);
   CHECK(strcmp(rtw_slot_name(RTW_ME), "me") == 0);
   CHECK(strcmp(rtw_slot_name(99), "?") == 0);
   DONE("rt_watch decision");
}
'''

# ---------------------------------------------------------------- 2 ------
def watchdog_production(src):
    parts = [line(src, r"^enum \{ RTW_MODE_BOOT.*\n.*\};$"),
             between(src, "static const char *const k_rtw_mode[]", "};"),
             line(src, r"^#define RTW_LATE_MS .*$"),
             line(src, r"^#define RTW_QUIET .*$"),
             line(src, r"^#define g_wake_hold .*$"),
             fn(src, "rtw_busy_now"),
             fn(src, "rtw_expect"), fn(src, "rtw_sample"), fn(src, "rtw_ago"),
             fn(src, "rtw_tick")]
    return "\n\n".join(parts)


TICK = CHECK + r'''
#include <stdarg.h>
#include "rt_watch.h"
typedef int SceUID;
#define PSP_POWER_CB_POWER_SWITCH 0x80000000u
#define PSP_POWER_CB_SUSPENDING 0x00010000u
#define PSP_POWER_CB_RESUMING 0x00020000u
#define PSP_POWER_CB_RESUME_COMPLETE 0x00040000u
/* the real words, as main_psp.c declares them */
static volatile int g_pwr_sleep_pending, g_pwr_park_req, g_pwr_park_ack;
static volatile int g_pwr_parked, g_pwr_slept, g_pwr_rebuild, g_wake_menu;
static struct { int down; } g_sq;
static volatile int g_running = 1;
static volatile unsigned g_loop_iter;
static volatile int g_loop_phase;
static SceUID audio_thid = -1, g_io_thid = -1;
static volatile int audio_running, g_io_run;
static volatile unsigned g_rtw_beat_audio, g_rtw_beat_io;
static volatile unsigned g_rtw_sav_blocks, g_rtw_sav_runs;
static volatile unsigned g_rtw_exit_in, g_rtw_exit_out, g_rtw_exit_us;
static volatile unsigned g_rtw_exit_iter;
static volatile int g_rtw_exit_phase;
static volatile unsigned g_rtw_pwr_flags, g_rtw_pwr_us, g_rtw_pwr_n;
static volatile unsigned g_rtw_wake_us;
static volatile int g_rtw_mode;
static const char *volatile g_rtw_step = "-";
static rtw_state g_rtw;
static unsigned long long g_rtw_t;
static int g_rtw_quiet;
static const char *volatile g_rtw_busy_why;   /* a busy span (pwr_hold) */
static volatile unsigned g_rtw_busy_us, g_rtw_busy_ms;
static int g_rtw_rec_aborted;
static int me_up, home_up;
static unsigned me_beat, home_kbeat;
static int me_host_up(void) { return me_up; }
static int home_host_loaded(void) { return home_up; }
static void me_host_diag(unsigned *a, unsigned *b, unsigned *c, unsigned *hb)
{ (void)a; (void)b; (void)c; *hb = me_beat; }
static void home_host_diag(unsigned *k, unsigned *b, unsigned *p, unsigned *f)
{ (void)b; (void)p; (void)f; *k = home_kbeat; }
/* the clock and the outputs */
static unsigned long long clk_us;
static unsigned long long sceKernelGetSystemTimeWide(void) { return clk_us; }
static unsigned sceKernelGetSystemTimeLow(void) { return (unsigned)clk_us; }
static int writes, records, last_record_fresh;
static char last[2048];
static void rt_note(const char *fmt, ...)
{ va_list ap; va_start(ap, fmt); vsnprintf(last, sizeof(last), fmt, ap); va_end(ap); writes++; }
static int rt_line(char *d, size_t n, const char *fmt, ...)
{ va_list ap; int k; va_start(ap, fmt); k = vsnprintf(d, n, fmt, ap); va_end(ap);
  return k < 0 ? 0 : (size_t)k < n ? k : (int)n - 1; }
static void rt_write(const char *t, int n) { (void)n; snprintf(last, sizeof(last), "%s", t); writes++; }
static int rtw_threads(char *d, size_t n, const char *tag, unsigned *a, unsigned *b)
{ (void)a; (void)b; return rt_line(d, n, " [%s threads]", tag); }
static void rtw_record(unsigned ev) { (void)ev; records++; writes++; last_record_fresh = (int)g_rtw.fresh; }
@PRODUCTION@
static void tick(void) { clk_us += 1000000ull; rtw_tick(); }
static void play(int moving_main)
{
   if (moving_main) g_loop_iter++;
   g_rtw_beat_audio += 40; g_rtw_beat_io += 4; me_beat += 1000; home_kbeat += 60;
}
static void fresh(void)
{
   rtw_reset(&g_rtw);
   g_rtw_quiet = 0;
   g_pwr_sleep_pending = g_pwr_park_req = g_pwr_park_ack = g_pwr_parked = 0;
   g_pwr_slept = g_pwr_rebuild = g_wake_menu = 0;
   g_sq.down = 0;
   g_rtw_mode = RTW_MODE_GAME;
   audio_thid = 0x100; audio_running = 1; g_io_thid = 0x200; g_io_run = 1;
   me_up = 1; home_up = 1;
   writes = records = 0;
   clk_us += 5000000ull;
   g_rtw_t = clk_us;
   tick();                                   /* primes */
}
int main(void)
{
   int i;
   unsigned m;

   /* rtw_expect, from the real words */
   fresh();
   m = rtw_expect();
   CHECK(m == RTW_ALL);
   g_rtw_mode = RTW_MODE_BROWSER; CHECK(!(rtw_expect() & RTW_BIT(RTW_MAIN)));
   g_rtw_mode = RTW_MODE_EXIT;    CHECK(rtw_expect() & RTW_BIT(RTW_MAIN));
   g_rtw_mode = RTW_MODE_GAME;
   g_wake_menu = 1;   CHECK(!(rtw_expect() & RTW_BIT(RTW_MAIN))); g_wake_menu = 0;
   g_pwr_rebuild = 1; CHECK(!(rtw_expect() & RTW_BIT(RTW_MAIN))); g_pwr_rebuild = 0;
   g_pwr_slept = 1;
   CHECK(!(rtw_expect() & (RTW_BIT(RTW_MAIN) | RTW_BIT(RTW_ME))));
   g_pwr_slept = 0;
   audio_running = 0; CHECK(!(rtw_expect() & RTW_BIT(RTW_AUDIO))); audio_running = 1;
   audio_thid = -1;   CHECK(!(rtw_expect() & RTW_BIT(RTW_AUDIO))); audio_thid = 0x100;
   g_io_run = 0;      CHECK(!(rtw_expect() & RTW_BIT(RTW_IO)));    g_io_run = 1;
   me_up = 0;         CHECK(!(rtw_expect() & RTW_BIT(RTW_ME)));    me_up = 1;
   home_up = 0;       CHECK(!(rtw_expect() & RTW_BIT(RTW_HOME)));  home_up = 1;
   g_pwr_sleep_pending = 1; CHECK(rtw_expect() == RTW_QUIET); g_pwr_sleep_pending = 0;
   g_pwr_park_req = 1;      CHECK(rtw_expect() == RTW_QUIET); g_pwr_park_req = 0;
   g_pwr_park_ack = 1;      CHECK(rtw_expect() == RTW_QUIET); g_pwr_park_ack = 0;
   g_pwr_parked = 1;        CHECK(rtw_expect() == RTW_QUIET); g_pwr_parked = 0;
   g_sq.down = 1;           CHECK(rtw_expect() == RTW_QUIET); g_sq.down = 0;

   /* a. play, then the main loop stops: one record at > 2 s, then quiet,
    *    then one clear line when it moves again. */
   fresh();
   for (i = 0; i < 5; i++) { play(1); tick(); }
   CHECK(records == 0 && writes == 0);
   play(0); tick(); play(0); tick();
   CHECK(records == 0);                       /* 2 s: not yet */
   play(0); tick();
   CHECK(records == 1 && last_record_fresh == (int)RTW_BIT(RTW_MAIN));
   for (i = 0; i < 10; i++) { play(0); tick(); }
   CHECK(records == 1 && writes == 1);        /* once per episode */
   play(1); tick();
   CHECK(writes == 2 && strstr(last, "stall_clear#1 moved=main") != NULL);

   /* b. the same stop while a sleep is in force: NOTHING is written, at
    *    all, and coming back is not read as a stall. */
   fresh();
   g_pwr_sleep_pending = 1;
   for (i = 0; i < 20; i++) { play(0); tick(); }
   CHECK(records == 0 && writes == 0);
   g_pwr_sleep_pending = 0;
   g_pwr_parked = 1;
   for (i = 0; i < 5; i++) { play(0); tick(); }
   g_pwr_parked = 0;
   g_sq.down = 1;
   for (i = 0; i < 5; i++) { play(0); tick(); }
   g_sq.down = 0;
   CHECK(records == 0 && writes == 0);
   play(1); tick(); play(1); tick(); play(1); tick();
   CHECK(records == 0);

   /* c. under the wake overlay the loop is nested: main not expected. */
   fresh();
   g_wake_menu = 1;
   for (i = 0; i < 10; i++) { play(0); tick(); }
   CHECK(records == 0);
   g_wake_menu = 0;

   /* d. the audio worker stops while the game runs. */
   fresh();
   for (i = 0; i < 4; i++) { g_loop_iter++; g_rtw_beat_io++; me_beat++; home_kbeat++; tick(); }
   CHECK(records == 1 && last_record_fresh == (int)RTW_BIT(RTW_AUDIO));

   /* e. the exit callback: a line on the next tick, from this thread. */
   fresh();
   g_rtw_exit_in = 1; g_rtw_exit_out = 1; g_rtw_exit_us = (unsigned)clk_us | 1u;
   g_rtw_exit_iter = 1234; g_running = 0;
   play(1); tick();
   CHECK(strstr(last, "exit_cb in=1 out=1") != NULL);
   CHECK(strstr(last, "iter_at=1234") != NULL);
   g_running = 1;   /* (the counts stay: the watchdog has seen them) */

   /* f. a stall that a sleep interrupts ends as "reason=sleep", no record
    *    for the gap. */
   fresh();
   for (i = 0; i < 3; i++) { play(0); tick(); }
   CHECK(records == 1);
   g_pwr_park_req = 1;
   for (i = 0; i < 5; i++) { play(0); tick(); }
   CHECK(writes == 1);
   g_pwr_park_req = 0;
   play(1); tick();
   CHECK(strstr(last, "stall_end#1 reason=sleep slots=main") != NULL);
   CHECK(records == 1);

   /* h. STEADY STATE: ten minutes of play with the .sav writer busy every
    *    second and the battery callback chattering -- not one file write.
    *    A wake, by contrast, is a line. */
   fresh();
   for (i = 0; i < 600; i++)
   {
      play(1);
      g_rtw_sav_runs++; g_rtw_sav_blocks += 7;
      if (i % 30 == 0) { g_rtw_pwr_flags = 0x000010E4u; g_rtw_pwr_n++; }
      tick();
   }
   CHECK(writes == 0 && records == 0);
   g_rtw_pwr_flags = PSP_POWER_CB_RESUME_COMPLETE; g_rtw_pwr_n++;
   play(1); tick();
   CHECK(writes == 1 && strstr(last, "pwr n=") != NULL);
   /* the .sav counts ride on the lines that are written anyway */
   for (i = 0; i < 3; i++) { play(0); tick(); }
   CHECK(records == 1);
   play(1); tick();
   CHECK(strstr(last, "stall_clear#1") != NULL && strstr(last, "sav_runs=600 sav_blocks=4200") != NULL);

   /* i. A BUSY SPAN (Host/Join's bring-up, pwr_hold "net"): a main loop
    *    inside one long iteration is not a stall -- until the span's own
    *    bound, after which the watch resumes. */
   fresh();
   g_rtw_busy_why = "net"; g_rtw_busy_us = (unsigned)clk_us;
   g_rtw_busy_ms = 30000;
   CHECK(!(rtw_expect() & RTW_BIT(RTW_MAIN)) && (rtw_expect() & RTW_BIT(RTW_AUDIO)));
   for (i = 0; i < 20; i++) { play(0); tick(); }
   CHECK(records == 0 && writes == 0);
   for (i = 0; i < 14; i++) { play(0); tick(); }
   CHECK(records == 1);                       /* 30 s bound + 3 s */
   g_rtw_busy_why = NULL;
   /*    ...and the other threads are still watched inside it. */
   fresh();
   g_rtw_busy_why = "state_save"; g_rtw_busy_us = (unsigned)clk_us;
   g_rtw_busy_ms = 15000;
   for (i = 0; i < 4; i++) { g_loop_iter++; g_rtw_beat_io++; me_beat++; home_kbeat++; tick(); }
   CHECK(records == 1 && last_record_fresh == (int)RTW_BIT(RTW_AUDIO));
   g_rtw_busy_why = NULL;

   /* j. a record a sleep cut short ends as such once the sleep is over. */
   fresh();
   for (i = 0; i < 3; i++) { play(0); tick(); }
   CHECK(records == 1);
   g_rtw_rec_aborted = 1;                     /* as rtw_record leaves it */
   g_pwr_sleep_pending = 1; play(0); tick(); g_pwr_sleep_pending = 0;
   play(1); tick();
   CHECK(strstr(last, "stall_end#1 reason=sleep slots=main record=aborted") != NULL);
   CHECK(g_rtw_rec_aborted == 0);

   /* g. a late watchdog says so, and the gap is capped. */
   fresh();
   play(1); clk_us += 9000000ull; tick();
   CHECK(strstr(last, "wd late ms=10000") != NULL && records == 0);
   DONE("rtw_expect/rtw_tick (production)");
}
'''

# ------------------------------------------------------------- 2b ------
def record_production(src):
    return "\n\n".join([
        line(src, r"^enum \{ RTW_MODE_BOOT.*\n.*\};$"),
        between(src, "static const char *const k_rtw_mode[]", "};"),
        line(src, r"^#define RTW_QUIET .*$"),
        line(src, r"^#define g_wake_hold .*$"),
        fn(src, "rtw_busy_now"), fn(src, "rtw_expect"), fn(src, "rtw_ago"),
        fn(src, "stall_main_drop"), fn(src, "stall_main_restore"),
        fn(src, "rtw_record")])


BUSY_HEAD = "/* ---- RTW BUSY SPANS"
BUSY_TAIL = "/* ---- end RTW BUSY SPANS */"


def busy_production(src):
    blk = between(src, BUSY_HEAD, BUSY_TAIL)
    ph = re.search(r"^void pwr_hold\(const char \*why\)\n\{.*?\n\}\n", src, re.S | re.M)
    pr = re.search(r"^void pwr_release\(void\)\n\{.*?\n\}\n", src, re.S | re.M)
    assert ph and pr, "pwr_hold / pwr_release not found"
    return "\n\n".join([blk, ph.group(0), pr.group(0), fn(src, "pwr_release_all")])


# ---------------------------------------------------------------- 3 ------
EARLY_HEAD = "/* ---- GPSP_RUNTIME_LOG: the words the runtime watchdog reads"
EARLY_TAIL = "#define RTW_PWR(f)     ((void)0)\n#endif\n"


def early_block(src):
    return between(src, EARLY_HEAD, EARLY_TAIL)


def loop_macros(src):
    return between(src, "#if !defined(GPSP_PLAYABLE) || defined(GPSP_KEEP_TELEMETRY) || \\\n"
                        "    defined(GPSP_STALL_RECORDER)\nstatic volatile unsigned g_loop_iter;",
                   "#define LOOP_PHASE(p)   do { } while (0)\n#endif\n")


SITES = CHECK + r'''
#include <stdint.h>
typedef unsigned SceSize;
typedef unsigned SceUInt;
typedef int SceUID;
#define PSP_POWER_CB_RESUME_COMPLETE 0x00040000u
#define OUT_CHUNK 16
#define RING_FRAMES 256
#define RING_MASK (RING_FRAMES - 1)
#define AUDIO_FADE_STEP (65536 / 64)
#define PSP_AUDIO_NEXT_CHANNEL (-1)
#define PSP_AUDIO_FORMAT_STEREO 0
#define PSP_AUDIO_VOLUME_MAX 0x8000
#define IO_WAIT_US 250000
static unsigned clk;
static unsigned sceKernelGetSystemTimeLow(void) { return clk += 1000; }
static SceUID self_id = 0x300;
static SceUID sceKernelGetThreadId(void) { return self_id; }
@LOOP@
static int kicks;
@EARLY@
static void rtw_kick(void) { kicks++; }
/* audio_thread's world */
static int16_t audio_ring[RING_FRAMES * 2];
static volatile unsigned ring_w, ring_r, g_audio_step;
static volatile unsigned g_audio_starved, g_audio_underruns;
static volatile int audio_running, g_audio_soft, audio_output_error;
static volatile int audio_ch = -1;
static int chunks, chunk_limit;
static int sceAudioChReserve(int c, int n, int f) { (void)c; (void)n; (void)f; return 3; }
static int sceAudioChRelease(int ch) { (void)ch; return 0; }
static int sceAudioOutputBlocking(int ch, int vol, void *buf)
{ (void)ch; (void)vol; (void)buf; if (++chunks >= chunk_limit) audio_running = 0; return 0; }
/* io_thread's world */
static SceUID g_io_thid = 0x200, g_io_sema = 7;
static volatile int g_io_run;
static struct { int log_thread, sram_thread; } g_pcfg;
static int waits, wait_limit, evt_runs, sav_calls, inside_at_sav;
static int sceKernelWaitSema(SceUID id, int n, SceUInt *t)
{ (void)id; (void)n; (void)t; if (++waits >= wait_limit) g_io_run = 0; return 0; }
static void fe_evt_service(void) { evt_runs++; }
@MARK@
static int fe_host_sram_service_io(void)
{ sav_calls++; inside_at_sav += g_rt_io_since[RTIO_IO] != 0; return sav_calls == 2 ? 0 : 3; }
/* exit_cb's world */
static volatile int g_running = 1;
@FUNCTIONS@
int main(void)
{
   int i;
   /* LOOP_TOP is the stall recorder's: it counts. */
   for (i = 0; i < 5; i++) LOOP_TOP();
   CHECK(g_loop_iter == 5 && g_loop_phase == 1);

   /* the audio worker: one beat per output chunk */
   audio_running = 1; chunk_limit = 7; chunks = 0;
   audio_thread(0, NULL);
   CHECK(chunks == 7 && g_rtw_beat_audio == 7);

   /* the writer: one beat per wait, the .sav pass counted and fenced */
   g_io_run = 1; wait_limit = 4; g_pcfg.log_thread = 1; g_pcfg.sram_thread = 1;
   self_id = g_io_thid;
   io_thread(0, NULL);
   CHECK(waits == 4 && g_rtw_beat_io == 4);
   /* 4 loop passes + the last pass after the loop (not counted) */
   CHECK(sav_calls == 5);
   CHECK(g_rtw_sav_runs == 3 && g_rtw_sav_blocks == 9);   /* pass 2 wrote 0 */
   /* the 4 loop passes are fenced; the last pass after the loop is the
    * writer's exit drain (not marked), and nothing is left marked */
   CHECK(inside_at_sav == 4 && g_rt_io_since[RTIO_IO] == 0);
   self_id = 0x300;

   /* the exit callback: stamps, sets g_running, wakes the watchdog */
   g_loop_iter = 4242; g_loop_phase = 5;
   CHECK(exit_cb(0, 0, NULL) == 0);
   CHECK(g_running == 0 && g_rtw_exit_in == 1 && g_rtw_exit_out == 1 && kicks == 1);
   CHECK(g_rtw_exit_iter == 4242 && g_rtw_exit_phase == 5 && g_rtw_exit_us != 0);

   /* the power callback's stamp: the wake is remembered */
   RTW_PWR(0x80000000u);
   CHECK(g_rtw_pwr_n == 1 && g_rtw_pwr_flags == 0x80000000u && g_rtw_wake_us == 0);
   RTW_PWR(PSP_POWER_CB_RESUME_COMPLETE);
   CHECK(g_rtw_pwr_n == 2 && g_rtw_wake_us != 0);
   DONE("call sites (production)");
}
'''


def sites_production(src):
    mark = between(src, "enum { RTIO_MAIN, RTIO_IO, RTIO_CB, RTIO_WD, RTIO_OTHER, RTIO_N };",
                   "g_rt_io_since[k] = on ? ((unsigned)sceKernelGetSystemTimeLow() | 1u) : 0u;\n}")
    mark += ("\n#define RT_IO(on) rt_io_mark(on)\n")
    funcs = "\n\n".join([fn(src, "audio_thread"), fn(src, "io_thread"),
                         fn(src, "exit_cb")])
    return (SITES.replace("@LOOP@", loop_macros(src))
                 .replace("@EARLY@", early_block(src))
                 .replace("@MARK@", mark)
                 .replace("@FUNCTIONS@", funcs))


GUARD = r'''
static volatile int g_running;
@LOOP@
static unsigned sceKernelGetSystemTimeLow(void) { return 1; }
typedef int SceUID;
#define PSP_POWER_CB_RESUME_COMPLETE 0x00040000u
@EARLY@
static void rtw_kick(void) {}
int main(void)
{
   (void)g_rtw_main_thid; (void)g_rtw_cb_thid; (void)g_rtw_thid;
   LOOP_TOP();
   return (int)g_loop_iter - 1;
}
'''


def structure(src):
    """What cannot be executed on a host: where the calls stand."""
    out = []
    # LOOP_TOP is the main game loop's first statement, before any continue.
    i = src.find("   while (g_running)\n   {\n      unsigned frames;")
    assert i >= 0, "the game loop not found"
    body = braced(src, src.find("{", i))
    top = body.find("      LOOP_TOP();")
    cont = body.find("continue;")
    out.append(("LOOP_TOP before any continue", 0 < top < cont))
    # the mode the expectation reads: GAME set before the loop, EXIT after
    pre = src[:i]
    out.append(("RTW_MODE(GAME) set before the game loop",
                pre.rfind("   RTW_MODE(GAME);\n") > pre.rfind("RTW_MODE(LOAD);")
                and pre.rfind("   RTW_MODE(GAME);\n") > pre.rfind("RTW_MODE(BROWSER);")))
    post = src[i + len(body):]
    out.append(("RTW_MODE(EXIT) set at the teardown",
                post.find("   RTW_MODE(EXIT);\n") >= 0 and
                post.find("   RTW_MODE(EXIT);\n") < post.find("   home_host_stop();\n")))
    # the menu's edge is tracked every iteration, outside the menu branch
    out.append(("RTW_MENU ahead of the menu branch",
                "      RTW_MENU(ui_active());   /* GPSP_RUNTIME_LOG: a line on open / close */\n"
                "      if (ui_active())\n      {\n         /* Core paused" in src))
    # the power callback stamps first
    pcb = fn(src, "power_cb")
    out.append(("power_cb stamps before anything",
                pcb.split("{", 1)[1].lstrip().startswith(
                    "(void)unknown; (void)common;\n   RTW_PWR(pwrflags);")))
    # every teardown step that begins also ends
    ins = re.findall(r'RT_STEP_IN\("([a-z_]+)"\)', src)
    outs = set(re.findall(r'RT_STEP_OUT\("([a-z_]+)"', src))
    want = {"me_stop", "net_stop", "io_thread_stop",
            "fe_host_shutdown", "av_stop", "evt_shutdown", "exit_game"}
    out.append(("teardown steps present", want <= set(ins) and "home_stop" in outs))
    # HOME goes back to the system FIRST: no runtime.log write on main
    # between the loop's end and home_host_stop() (MAGI f-013)
    k = src.find("   RTW_MODE(EXIT);\n")
    h = src.find("   home_host_stop();\n", k)
    span = src[k:h] if 0 <= k < h else ""
    out.append(("no log write before home_host_stop",
                bool(span) and not re.search(r"\bRT_(NOTE|STEP_IN|STEP_OUT)\(|\brt_note\(", span)))
    out.append(("every step but the exit ends",
                all(s in outs for s in ins if s != "exit_game")))
    # every process exit stops the watchdog
    out.append(("sceKernelExitGame stops the watchdog",
                re.search(r"#define sceKernelExitGame\(\) \(pwr_release_all\(\), "
                          r"RTW_STOP\(\"exit_game\"\), \\\n\s+sceKernelExitGame\(\)\)",
                          src) is not None))
    out.append(("relaunch stops the watchdog",
                "RTW_STOP(\"relaunch\");" in fn(src, "relaunch_eboot")))
    # the watchdog starts at boot, right after the paths
    out.append(("watchdog starts after init_paths",
                "   init_paths(argc, argv);\n   RTW_START();" in src))
    # the exit callback never writes a file itself
    ecb = fn(src, "exit_cb")
    out.append(("exit_cb does no I/O", "rt_note" not in ecb and "rt_write" not in ecb
                and "standby_note" not in ecb))
    return out


def run_structure(src, expect_all=True):
    res = structure(src)
    bad = [n for n, ok in res if not ok]
    if expect_all and bad:
        raise AssertionError("structure: " + ", ".join(bad))
    return bad


def run_all(src, expect=True):
    """Every executable check; returns the names that failed."""
    failed = []
    for name, text, extra, defs in (
            ("tick", TICK.replace("@PRODUCTION@", watchdog_production(src)),
             [WATCH_C], []),
            ("sites", sites_production(src), [],
             ["-DGPSP_RUNTIME_LOG", "-DGPSP_PLAYABLE", "-DGPSP_STALL_RECORDER"]),
            ("record", CHECK + rtlog_paths.RECORD.replace(
                "@PRODUCTION@", record_production(src)), [WATCH_C], []),
            ("stop", CHECK + rtlog_paths.STOP.replace(
                "@PRODUCTION@", fn(src, "rtw_stop")), [], []),
            ("busy", CHECK + rtlog_paths.BUSY.replace(
                "@PRODUCTION@", busy_production(src)), [], ["-DGPSP_RUNTIME_LOG"])):
        try:
            build_run(text, name, True, extra, defs)
        except AssertionError as e:
            failed.append(name)
            if expect:
                raise
            last = str(e).strip().splitlines()
            print("   (%s: %s)" % (name, last[1] if len(last) > 1 else last[0]))
    try:
        run_structure(src)
    except AssertionError as e:
        failed.append(str(e))
        if expect:
            raise
        print("   (%s)" % e)
    return failed


def main():
    r = build_run(DECISION, "decision", True, [WATCH_C])
    print(r.stdout.strip())
    # the guard: GPSP_RUNTIME_LOG without the stall recorder does not build
    guard = GUARD.replace("@LOOP@", loop_macros(MAIN)).replace("@EARLY@", early_block(MAIN))
    ok = build_run(guard, "guard_on", True, [], ["-DGPSP_RUNTIME_LOG", "-DGPSP_PLAYABLE",
                                                   "-DGPSP_STALL_RECORDER"])
    bad = build_run(guard, "guard_off", False, [], ["-DGPSP_RUNTIME_LOG", "-DGPSP_PLAYABLE"])
    assert "reuses the stall recorder" in bad.stderr, bad.stderr
    print("build guard: RUNTIME_LOG without STALL_RECORDER refused; with it, LOOP_TOP counts")
    assert not run_all(MAIN, True)
    print("rtw_expect/rtw_tick and call sites (production): pass; structure: %d checks pass"
          % len(structure(MAIN)))

    # ---- mutants against the production call sites --------------------
    mutants = [
        ("audio worker never beats", MAIN, "      RTW_BEAT(audio);\n", ""),
        ("writer never beats", MAIN, "      RTW_BEAT(io);\n", ""),
        ("the .sav pass is not counted", MAIN,
         "         RTW_SAV(fe_host_sram_service_io());\n",
         "         (void)fe_host_sram_service_io();\n"),
        ("the .sav pass is not fenced", MAIN,
         "      {\n         RT_IO(1);\n         RTW_SAV(fe_host_sram_service_io());\n",
         "      {\n         RTW_SAV(fe_host_sram_service_io());\n"),
        ("suppression ignores a pending sleep", MAIN,
         "   if (g_pwr_sleep_pending || g_pwr_park_req || g_pwr_park_ack ||\n",
         "   if (g_pwr_park_req || g_pwr_park_ack ||\n"),
        ("suppression ignores the quiesce", MAIN,
         "       g_pwr_parked || g_sq.down)\n      return RTW_QUIET;",
         "       g_pwr_parked)\n      return RTW_QUIET;"),
        ("main expected under the wake overlay", MAIN,
         "   if (((g_rtw_mode == RTW_MODE_GAME && !g_wake_hold) ||",
         "   if (((g_rtw_mode == RTW_MODE_GAME) ||"),
        ("the tick writes while quiet", MAIN,
         "      g_rtw_quiet = 1;               /* asleep, or on the way: no I/O */\n      return;\n",
         "      g_rtw_quiet = 1;               /* asleep, or on the way: no I/O */\n"),
        ("no reset after a sleep", MAIN,
         "      rtw_reset(&g_rtw);\n   }\n   else if (dt > RTW_LATE_MS)",
         "   }\n   else if (dt > RTW_LATE_MS)"),
        ("a .sav line every tick the writer ran", MAIN,
         "   rtw_sample(now, expect);\n   ev = rtw_step(",
         "   { static unsigned ss; if (g_rtw_sav_runs != ss) { ss = g_rtw_sav_runs;\n"
         "     rt_note(\"sav_io runs=%u\", ss); } }\n"
         "   rtw_sample(now, expect);\n   ev = rtw_step("),
        ("battery callbacks written", MAIN,
         "      if (g_rtw_pwr_flags & (PSP_POWER_CB_POWER_SWITCH |",
         "      if (1 || g_rtw_pwr_flags & (PSP_POWER_CB_POWER_SWITCH |"),
        ("the record ignores a sleep begun while it samples", MAIN,
         "   if (rtw_expect() & RTW_QUIET)      /* sampled into a sleep */\n"
         "   {\n      g_rtw_rec_aborted = 1;\n      return;\n   }\n", ""),
        ("the record writes into a sleep begun during the drop", MAIN,
         "   if (rtw_expect() & RTW_QUIET)      /* slid during the drop */\n"
         "   {\n      stall_main_restore(pri0);\n      g_rtw_rec_aborted = 1;\n"
         "      return;\n   }\n", ""),
        ("the display is asked after a sleep began", MAIN,
         "   if (rtw_expect() & RTW_QUIET)      /* the display can wait */\n"
         "   {\n      g_rtw_rec_aborted = 1;\n      return;\n   }\n", ""),
        ("rtw_stop writes before the join", MAIN,
         "   g_rtw_run = 0;\n   rtw_kick();\n",
         "   rt_note(\"wd stop why=%s\", why);\n   g_rtw_run = 0;\n   rtw_kick();\n"),
        ("loop_exit written before HOME is handed back", MAIN,
         "   DIAG_WHERE(\"teardown\");\n   RTW_MODE(EXIT);\n",
         "   DIAG_WHERE(\"teardown\");\n   RTW_MODE(EXIT);\n   RT_NOTE(\"loop_exit\");\n"),
        ("main expected inside a busy span", MAIN,
         "        g_rtw_mode == RTW_MODE_EXIT) && !rtw_busy_now())",
         "        g_rtw_mode == RTW_MODE_EXIT))"),
        ("pwr_hold marks no busy span", MAIN,
         "   RTW_BUSY_PUSH(g_pwr_hold, why);\n", ""),
        ("a busy span never ends", MAIN,
         "   RTW_BUSY_POP(g_pwr_hold - 1);\n", ""),
        ("the game loop does not count", MAIN,
         "      LOOP_TOP();\n      FE_LP_SET(FELP_L_TOP);",
         "      FE_LP_SET(FELP_L_TOP);"),
        ("play never marked as play", MAIN,
         "   RTW_MODE(GAME);\n   RT_NOTE(\"game loop enter", "   RT_NOTE(\"game loop enter"),
        ("teardown not marked", MAIN,
         "   RTW_MODE(EXIT);\n   sleep_quiesce_up(\"loop_exit\");",
         "   sleep_quiesce_up(\"loop_exit\");"),
        ("exit callback does not wake the watchdog", MAIN,
         "   g_running = 0;\n   RTW_EXIT_OUT();\n", "   g_running = 0;\n"),
        ("power stamp moved off power_cb's entry", MAIN,
         "   RTW_PWR(pwrflags);           /* GPSP_RUNTIME_LOG: two stores, no I/O */\n", ""),
        ("io_thread_stop has no end line", MAIN,
         "      RT_STEP_OUT(\"io_thread_stop\", rt_io_rc);\n", "      (void)rt_io_rc;\n"),
        ("sceKernelExitGame leaves the watchdog running", MAIN,
         "RTW_STOP(\"exit_game\"), \\\n                             sceKernelExitGame())",
         "\\\n                             sceKernelExitGame())"),
    ]
    killed = 0
    for label, src, old, new in mutants:
        assert src.count(old) == 1, label + ": production text not found"
        bad_src = src.replace(old, new, 1)
        failed = run_all(bad_src, False)
        if not failed:
            raise AssertionError("mutant survived: " + label)
        killed += 1
        print("mutant (%s): failed as it must" % label)

    # the guard itself
    no_guard = MAIN.replace('#error "GPSP_RUNTIME_LOG reuses the stall recorder', '#warning "x', 1)
    g2 = GUARD.replace("@LOOP@", loop_macros(no_guard)).replace("@EARLY@", early_block(no_guard))
    r = build_run(g2, "guard_mut", False, [], ["-DGPSP_RUNTIME_LOG", "-DGPSP_PLAYABLE"])
    assert "reuses the stall recorder" not in r.stderr
    killed += 1
    print("mutant (build guard removed): the unguarded build is caught (no counter to read)")

    # the decision's boundary and its "not expected" rule
    watch = WATCH_C.read_text()
    for label, old, new in (
            ("stall at exactly 2 s", "if (s->age_ms[i] > RTW_LIMIT_MS)",
             "if (s->age_ms[i] >= RTW_LIMIT_MS)"),
            ("unexpected slots accrue", "      if (!(expect & bit))\n",
             "      if (0 && !(expect & bit))\n"),
            ("no cap on a late tick", "   if (dt_ms > RTW_DT_CAP_MS)\n      dt_ms = RTW_DT_CAP_MS;\n", ""),
            ("an episode reported on every tick", "   if (!before && s->stalled)",
             "   if (s->stalled && !(s->stalled & ~s->reported) && 0) {} else if (s->stalled)")):
        assert watch.count(old) == 1, label
        with tempfile.TemporaryDirectory() as d:
            mp = Path(d) / "rt_watch.c"
            mp.write_text(watch.replace(old, new, 1))
            build_run(DECISION, "decision_mut", False, [mp])
        killed += 1
        print("mutant (rt_watch: %s): failed as it must" % label)
    print("%d mutants, all killed" % killed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

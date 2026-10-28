"""C harnesses for test_runtime_log.py: the paths MAGI's review of
diag/runtime-log flagged (2026-10-28).  Each is completed with production
text extracted from psp/main_psp.c (@PRODUCTION@) by test_runtime_log.py.

RECORD  rtw_record re-checks the sleep state before dropping main, before its
        write and before the display / GE queries (f-009/f-010)
STOP    rtw_stop stops and joins the thread, then writes (f-011)
BUSY    pwr_hold / pwr_release mark the long single iterations (Host/Join,
        net teardown, state save/load ...) as busy spans (f-007/f-003)
"""

RECORD = r'''
#include <stdarg.h>
#include "rt_watch.h"
typedef int SceUID;
typedef struct { int gu_queued; unsigned gusync_in, gusync_out, swap_us, swaps,
                 swap_fails; int swap_rc; unsigned fb_cur, fb_addr[3]; } vid_rt_info;
#define PSP_DISPLAY_SETBUF_IMMEDIATE 0
#define PSP_DISPLAY_SETBUF_NEXTFRAME 1
enum { RTIO_MAIN, RTIO_IO, RTIO_CB, RTIO_WD, RTIO_OTHER, RTIO_N };
static volatile unsigned g_rt_io_since[RTIO_N];
static volatile int g_pwr_sleep_pending, g_pwr_park_req, g_pwr_park_ack;
static volatile int g_pwr_parked, g_pwr_slept, g_pwr_rebuild, g_wake_menu;
static struct { int down; } g_sq;
static volatile int g_pwr_play_lock, g_pwr_hold;
static const char *g_pwr_hold_why = "-";
static volatile int g_running = 1, g_rtw_mode, g_rtw_menu;
static const char *volatile g_rtw_step = "-";
static volatile unsigned g_loop_iter, g_rtw_beat_audio, g_rtw_beat_io;
static volatile unsigned g_rtw_sav_runs, g_rtw_sav_blocks, g_rtw_exit_in, g_rtw_exit_out;
static volatile unsigned g_rtw_pwr_flags, g_rtw_pwr_us, g_rtw_pwr_n, g_rtw_wake_us;
static const char *volatile g_rtw_busy_why;
static volatile unsigned g_rtw_busy_us, g_rtw_busy_ms;
static int g_rtw_rec_aborted;
static volatile unsigned fe_lp_phase;
static SceUID audio_thid = 1, g_io_thid = 2, g_emu_thid = 3;
static volatile int audio_running = 1, g_io_run = 1;
static int g_me_rend, g_me_video, g_mer_vmem, g_mer_pending, g_mer_ready;
static int g_mer_last_presented;
static rtw_state g_rtw;
static unsigned fe_host_frame_count(void) { return 0; }
static int me_host_up(void) { return 1; }
static int me_host_loaded(void) { return 1; }
static int me_host_was_dead(void) { return 0; }
static int home_host_loaded(void) { return 0; }
static void home_host_diag(unsigned *a, unsigned *b, unsigned *c, unsigned *d)
{ (void)a; (void)b; (void)c; (void)d; }
static void vid_rt_diag(vid_rt_info *v) { memset(v, 0, sizeof(*v)); }
static unsigned clk;
static unsigned sceKernelGetSystemTimeLow(void) { return clk += 1000; }
/* the sleep begins at the Nth delay of the record (0 = never) */
static int delays, sleep_at, prio_now = 0x2B, writes, disp_calls, write_sleeps, prio_changes;
static void sceKernelDelayThread(unsigned us)
{ (void)us; if (++delays == sleep_at) g_pwr_sleep_pending = 1; }
static int sceKernelChangeThreadPriority(SceUID t, int p) { (void)t; prio_now = p; prio_changes++; return 0; }
static void rt_write(const char *t, int n)
{ (void)t; (void)n; writes++; if (write_sleeps) g_pwr_sleep_pending = 1; }
static void rt_note(const char *fmt, ...) { (void)fmt; writes++; }
static int rt_line(char *d, size_t n, const char *fmt, ...)
{ va_list ap; int k; va_start(ap, fmt); k = vsnprintf(d, n, fmt, ap); va_end(ap);
  return k < 0 ? 0 : (size_t)k < n ? k : (int)n - 1; }
static int rtw_threads(char *d, size_t n, const char *tag, unsigned *a, unsigned *b)
{ (void)a; (void)b; sceKernelDelayThread(100000); return rt_line(d, n, "%s thr\n", tag); }
static int stall_line(char *l, size_t n, unsigned it, int *pri0)
{ (void)it; sceKernelDelayThread(100000); *pri0 = 0x2B; return snprintf(l, n, "stall t=1\n"); }
static unsigned sceDisplayGetVcount(void) { disp_calls++; return 1; }
static int sceDisplayGetFrameBuf(void **a, int *w, int *p, int s)
{ (void)s; *a = NULL; *w = *p = 0; disp_calls++; return 0; }
static int sceDisplayGetMode(int *m, int *w, int *h) { *m = *w = *h = 0; disp_calls++; return 0; }
static int sceGeDrawSync(int s) { (void)s; disp_calls++; return 0; }
@PRODUCTION@
static void run(int at, int wsleep)
{
   delays = writes = disp_calls = prio_changes = 0;
   g_rtw_rec_aborted = 0;
   g_pwr_sleep_pending = 0;
   sleep_at = at;
   write_sleeps = wsleep;
   prio_now = 0x2B;
   g_rtw_mode = RTW_MODE_GAME;
   g_rtw.fresh = 1;
   rtw_record(RTW_EV_STALL);
}
int main(void)
{
   /* no sleep: one block, the display line after it, main put back */
   run(0, 0);
   CHECK(writes == 2 && disp_calls >= 4 && prio_now == 0x2B && prio_changes == 2 && !g_rtw_rec_aborted);
   /* the sleep begins while the threads / stall_line are sampled: nothing
    * written, main never dropped, the display not asked */
   run(2, 0);
   CHECK(writes == 0 && disp_calls == 0 && prio_changes == 0 && g_rtw_rec_aborted);
   /* ...while main is dropped below io for the write: put back, no write */
   run(3, 0);
   CHECK(writes == 0 && disp_calls == 0 && prio_now == 0x2B && g_rtw_rec_aborted);
   /* ...right after the block landed: the display is not asked */
   run(0, 1);
   CHECK(writes == 1 && disp_calls == 0 && prio_now == 0x2B && g_rtw_rec_aborted);
   DONE("rtw_record sleep re-checks (production)");
}
'''

STOP = r'''
#include <stdarg.h>
typedef int SceUID;
typedef unsigned SceUInt;
static SceUID g_rtw_thid = 5;
static volatile int g_rtw_run = 1;
static const char *volatile g_rtw_step = "x";
static char order[16];
static int run_at_join = -1;
static void mark(char c) { size_t n = strlen(order); order[n] = c; order[n + 1] = 0; }
static void rtw_kick(void) { mark('K'); }
static int sceKernelWaitThreadEnd(SceUID t, SceUInt *tmo)
{ (void)t; (void)tmo; run_at_join = g_rtw_run; mark('J'); return 0; }
static int sceKernelTerminateDeleteThread(SceUID t) { (void)t; mark('T'); return 0; }
static int sceKernelDeleteThread(SceUID t) { (void)t; mark('D'); return 0; }
static char last[256];
static void rt_note(const char *fmt, ...)
{ va_list ap; va_start(ap, fmt); vsnprintf(last, sizeof(last), fmt, ap); va_end(ap); mark('N'); }
@PRODUCTION@
int main(void)
{
   rtw_stop("exit_game");
   CHECK(strcmp(order, "KJDN") == 0);
   CHECK(run_at_join == 0 && g_rtw_thid == -1);
   CHECK(strstr(last, "wd stop why=exit_game") != NULL);
   order[0] = 0;
   rtw_stop("again");                           /* idempotent */
   CHECK(order[0] == 0);
   DONE("rtw_stop order (production)");
}
'''

BUSY = r'''
#include <stdarg.h>
#define FE_EVT_ONLY(x) ((void)(x))
#define fe_evt(...) ((void)0)
static volatile unsigned g_loop_iter;
static unsigned clk;
static unsigned sceKernelGetSystemTimeLow(void) { return clk; }
static int g_pwr_hold;
static const char *g_pwr_hold_why = "";
static unsigned g_pwr_hold_t0;
static int locks;
static int scePowerLock(int u) { (void)u; locks++; return 0; }
static int scePowerUnlock(int u) { (void)u; locks--; return 0; }
static void sleep_sim_window_enter(const char *w) { (void)w; }
static void standby_note(const char *fmt, ...) { (void)fmt; }
static void play_lock_drop(const char *w) { (void)w; }
static char last[256], all[2048];
static int notes;
static void rt_note(const char *fmt, ...)
{ va_list ap; va_start(ap, fmt); vsnprintf(last, sizeof(last), fmt, ap); va_end(ap);
  strncat(all, last, sizeof(all) - strlen(all) - 2); strcat(all, "|"); notes++; }
#define RT_MAIN_NOTE(...) rt_note(__VA_ARGS__)
void pwr_hold(const char *why);
void pwr_release(void);
@PRODUCTION@
int main(void)
{
   unsigned it;
   /* a state save: busy for its duration, one line at each end */
   it = g_loop_iter;
   pwr_hold("state_save");
   CHECK(g_rtw_busy_why && strcmp(g_rtw_busy_why, "state_save") == 0);
   CHECK(g_rtw_busy_ms == 15000 && g_loop_iter == it + 1);
   CHECK(strstr(last, "busy state_save begin") != NULL);
   clk += 2400000;
   pwr_release();
   CHECK(g_rtw_busy_why == NULL && g_loop_iter == it + 2);
   CHECK(strstr(last, "busy state_save end ms=2400") != NULL);
   /* Host/Join's bring-up has the long bound */
   pwr_hold("net");
   CHECK(g_rtw_busy_ms == 30000);
   pwr_release();
   CHECK(g_rtw_busy_why == NULL && locks == 0);
   /* the boot and the teardown are not busy spans ... */
   notes = 0;
   pwr_hold("boot");
   CHECK(g_rtw_busy_why == NULL);
   pwr_release();
   pwr_hold("teardown");
   CHECK(g_rtw_busy_why == NULL && notes == 0);
   /* ... but the net teardown nested inside the teardown is */
   pwr_hold("net");
   CHECK(g_rtw_busy_why && strcmp(g_rtw_busy_why, "net") == 0);
   pwr_release();
   CHECK(g_rtw_busy_why == NULL);
   pwr_release();
   /* nested spans: the inner one, then the outer again */
   pwr_hold("net");
   pwr_hold("session");
   CHECK(g_rtw_busy_why && strcmp(g_rtw_busy_why, "session") == 0);
   pwr_release();
   CHECK(g_rtw_busy_why && strcmp(g_rtw_busy_why, "net") == 0);
   /* every exit drops every hold: every span ends */
   pwr_hold("state_load");
   all[0] = 0;
   pwr_release_all();
   CHECK(g_rtw_busy_why == NULL && g_pwr_hold == 0);
   CHECK(strstr(all, "busy state_load end") != NULL && strstr(all, "busy net end") != NULL);
   DONE("busy spans (production pwr_hold/pwr_release)");
}
'''

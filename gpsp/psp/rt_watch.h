/* rt_watch.h -- the runtime watchdog's decision: which progress counter has
 * stopped while it is expected to move, and when an episode begins, grows and
 * ends.  Pure C, no PSP headers, so the host test runs the same decision the
 * EBOOT does (as psp/sleep_q.h does for the sleep quiesce).
 *
 * Built only with GPSP_RUNTIME_LOG (psp/Makefile adds rt_watch.o and
 * rt_log.o only then); main_psp.c owns the thread, the counters' sources and
 * the "expected" mask (rtw_expect), and writes what this decides.
 *
 * ONE STEP PER WATCHDOG TICK (~1 s).  For every slot:
 *   moved          the counter differs from the last sample: its age is 0 and
 *                  it leaves the stalled set;
 *   not expected   (asleep, parked, not in play, thread not running): its age
 *                  is 0 and, if it was stalled, it leaves the set as
 *                  `dropped` -- only a real move counts as `moved`;
 *   expected, still  its age grows by the tick; past RTW_LIMIT_MS it stalls.
 * An EPISODE is the time the stalled set is non-empty.  The step says so
 * ONCE when it begins (RTW_EV_STALL: the caller writes the full record), once
 * per slot that joins later (RTW_EV_GROW), and once when it ends
 * (RTW_EV_CLEAR).  The tick length is capped at RTW_DT_CAP_MS, so a watchdog
 * that was itself held off cannot turn one late tick into a stall. */
#ifndef RT_WATCH_H
#define RT_WATCH_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

enum
{
   RTW_MAIN = 0,   /* the emulation loop's top (g_loop_iter) / teardown step */
   RTW_AUDIO,      /* the audio worker, once per output chunk (~23 ms)       */
   RTW_IO,         /* the .sav / log writer, once per wait (<= 250 ms)       */
   RTW_ME,         /* the Media Engine dispatcher's own heartbeat            */
   RTW_HOME,       /* the HOME module's poll (gbadhoc_home.prx, ~16 ms)      */
   RTW_SLOTS
};

#define RTW_BIT(i)     (1u << (i))
#define RTW_ALL        (RTW_BIT(RTW_SLOTS) - 1u)
#define RTW_LIMIT_MS   2000u   /* still for longer than this = stalled */
#define RTW_DT_CAP_MS  1500u   /* one tick never counts for more */

#define RTW_EV_STALL   1u      /* an episode began: `fresh` slots */
#define RTW_EV_GROW    2u      /* more slots joined it: `fresh` slots */
#define RTW_EV_CLEAR   4u      /* it ended: `moved` / `dropped` say how */

typedef struct rtw_state
{
   unsigned last[RTW_SLOTS];      /* the counters at the previous step     */
   unsigned age_ms[RTW_SLOTS];    /* how long each has been still (expected) */
   unsigned stalled;              /* slots stalled now                     */
   unsigned reported;             /* slots reported in this episode        */
   unsigned fresh;                /* last step: slots newly reported       */
   unsigned moved;                /* last step: slots whose counter moved  */
   unsigned dropped;              /* last step: stalled slots no longer expected */
   unsigned episode_ms;           /* the current / just-ended episode's length */
   unsigned episodes;             /* episodes begun since the reset        */
   int      primed;               /* the first step only takes a sample    */
} rtw_state;

/* Forget everything; the next step only samples. */
void rtw_reset(rtw_state *s);

/* One tick: `now` the counters as sampled, `expect` the RTW_BIT mask of slots
 * that should be moving, `dt_ms` the time since the last step.  Returns the
 * RTW_EV_* that happened (at most one). */
unsigned rtw_step(rtw_state *s, const unsigned now[RTW_SLOTS],
                  unsigned expect, unsigned dt_ms);

/* "main", "audio", ... ; "?" out of range. */
const char *rtw_slot_name(int slot);

/* The slots of `mask` as "main+audio", or "-" for none.  Returns the length
 * written (snprintf's, clipped to n - 1). */
int rtw_mask_names(char *d, size_t n, unsigned mask);

#ifdef __cplusplus
}
#endif

#endif /* RT_WATCH_H */

/* test_sleep_q.c -- the sleep quiesce sequence (psp/sleep_q.c) and its
 * CONFIG.INI keys (psp/config_psp.c), against the production files.
 *
 *   1. Keys: absent -> every piece ON; "0" -> off; any other value -> on.
 *   2. Down order is TYL's: audio, writer, files, home, net.  Up is the
 *      reverse, audio LAST, and restarts only what down really stopped.
 *   3. Toggles: a piece that is off is never called, and is noted as skipped.
 *   4. The .sav / event-log handles are closed only when the writer is quiet
 *      (stopped by us, or never ran); the ROM handle always.
 *   5. Idempotent: a second down while down does nothing; up without down
 *      does nothing. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "ctl_map.h"
#include "config_psp.h"
#include "fe_util.h"
#include "sleep_q.h"

#ifndef GPSP_PLAYABLE
void fe_evt(const char *fmt, ...) { (void)fmt; }
#endif
void fe_log(const char *fmt, ...) { (void)fmt; }
const char *vid_scale_name(int mode) { (void)mode; return "t"; }
const char *vid_filter_name(int mode) { (void)mode; return "t"; }

static int checks, failures;
#define CHECK(c) do { checks++; if (!(c)) { failures++; \
   fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

/* ---- a fake machine --------------------------------------------------- */
static char trace[512];
static char notes[4096];
static int  rc_audio_stop, rc_writer_stop, rc_home_stop, rc_net_term;
static int  sav_open, rom_open, evt_open, quiet_seen;

static void t(const char *s)
{
   strncat(trace, s, sizeof(trace) - strlen(trace) - 1);
   strncat(trace, " ", sizeof(trace) - strlen(trace) - 1);
}
static int f_audio_stop(void *c) { (void)c; t("A-"); return rc_audio_stop; }
static int f_audio_start(void *c) { (void)c; t("A+"); return 0; }
static int f_writer_stop(void *c) { (void)c; t("W-"); return rc_writer_stop; }
static int f_writer_start(void *c) { (void)c; t("W+"); return 0; }
static int f_files_close(void *c, int quiet, char *d, size_t n)
{
   int closed = 0, sav = -1, evt = -1;
   (void)c;
   t("F-");
   quiet_seen = quiet;
   if (quiet)
   {
      sav = sav_open; closed += sav; sav_open = 0;
      evt = evt_open; closed += evt; evt_open = 0;
   }
   closed += rom_open;
   snprintf(d, n, "sav=%d rom=%d evt=%d", sav, rom_open, evt);
   rom_open = 0;
   return closed;
}
static int f_files_reopen(void *c, char *d, size_t n)
{
   (void)c;
   t("F+");
   snprintf(d, n, "evt=1");
   return 1;
}
static int f_home_stop(void *c) { (void)c; t("H-"); return rc_home_stop; }
static int f_home_rearm(void *c) { (void)c; t("H+"); return 0; }
static int f_net_term(void *c) { (void)c; t("N-"); return rc_net_term; }
static void f_note(void *c, const char *line)
{
   (void)c;
   strncat(notes, line, sizeof(notes) - strlen(notes) - 2);
   strcat(notes, "\n");
}

static const sleep_q_ops ops = {
   NULL, f_audio_stop, f_audio_start, f_writer_stop, f_writer_start,
   f_files_close, f_files_reopen, f_home_stop, f_home_rearm, f_net_term,
   f_note
};

static void reset(void)
{
   trace[0] = notes[0] = '\0';
   rc_audio_stop = rc_writer_stop = rc_home_stop = rc_net_term = 0;
   sav_open = rom_open = evt_open = 1;
   quiet_seen = -1;
}

static void test_order_all_on(void)
{
   sleep_cfg cfg = SLEEP_CFG_DEFAULT;
   sleep_q q;
   memset(&q, 0, sizeof(q));
   reset();
   CHECK(sleep_q_down(&q, &cfg, &ops) == 5);
   CHECK(strcmp(trace, "A- W- F- H- N- ") == 0);
   CHECK(quiet_seen == 1);
   CHECK(strstr(notes, "q audio_stop rc=0\n") != NULL);
   CHECK(strstr(notes, "q writer_stop rc=0\n") != NULL);
   CHECK(strstr(notes, "q fd_close n=3 sav=1 rom=1 evt=1\n") != NULL);
   CHECK(strstr(notes, "q home_stop rc=0\n") != NULL);
   CHECK(strstr(notes, "q net_term rc=0\n") != NULL);
   /* idempotent while down */
   CHECK(sleep_q_down(&q, &cfg, &ops) == 0);
   CHECK(strcmp(trace, "A- W- F- H- N- ") == 0);
   trace[0] = '\0';
   CHECK(sleep_q_up(&q, &ops) == 3);   /* home, writer, audio (files: 1 = none) */
   /* reverse; the radio is not restarted; sound last */
   CHECK(strcmp(trace, "H+ F+ W+ A+ ") == 0);
   CHECK(strstr(notes, "q net_up rc=1 (session ended)") != NULL);
   CHECK(strstr(notes, "q audio_start rc=0") != NULL);
   trace[0] = '\0';
   CHECK(sleep_q_up(&q, &ops) == 0);   /* not down: nothing */
   CHECK(trace[0] == '\0');
}

static void test_only_restart_what_stopped(void)
{
   sleep_cfg cfg = SLEEP_CFG_DEFAULT;
   sleep_q q;
   memset(&q, 0, sizeof(q));
   reset();
   rc_audio_stop = SQ_NONE;     /* no audio worker */
   rc_writer_stop = -5;         /* join timed out: terminated */
   rc_home_stop = SQ_NONE;      /* module never loaded */
   rc_net_term = SQ_NONE;       /* no session */
   CHECK(sleep_q_down(&q, &cfg, &ops) == 1);   /* files only */
   CHECK(quiet_seen == 1);      /* a terminated writer is gone too */
   CHECK(strstr(notes, "q writer_stop rc=-5") != NULL);
   trace[0] = '\0';
   sleep_q_up(&q, &ops);
   CHECK(strcmp(trace, "F+ ") == 0);
}

static void test_toggles(void)
{
   sleep_cfg cfg = SLEEP_CFG_DEFAULT;
   sleep_q q;
   memset(&q, 0, sizeof(q));
   reset();
   cfg.stop_audio = 0;
   cfg.stop_writer = 0;
   cfg.net_term = 0;
   sleep_q_down(&q, &cfg, &ops);
   CHECK(strcmp(trace, "F- H- ") == 0);
   CHECK(strstr(notes, "q audio_stop skipped cfg=0") != NULL);
   CHECK(strstr(notes, "q writer_stop skipped cfg=0") != NULL);
   CHECK(strstr(notes, "q net_term skipped cfg=0") != NULL);
   /* the writer is live: its handles stay, the ROM handle goes */
   CHECK(quiet_seen == 0);
   CHECK(strstr(notes, "q fd_close n=1 sav=-1 rom=1 evt=-1") != NULL);
   CHECK(sav_open == 1 && evt_open == 1 && rom_open == 0);
   trace[0] = '\0';
   sleep_q_up(&q, &ops);
   CHECK(strcmp(trace, "H+ F+ ") == 0);    /* never audio/writer */

   memset(&q, 0, sizeof(q));
   reset();
   cfg.stop_audio = cfg.stop_writer = cfg.close_files = cfg.stop_home =
      cfg.net_term = 0;
   CHECK(sleep_q_down(&q, &cfg, &ops) == 0);
   CHECK(trace[0] == '\0');
   CHECK(q.down == 1);
   sleep_q_up(&q, &ops);
   CHECK(trace[0] == '\0' && q.down == 0);
   cfg.hold_loop = cfg.power_lock = cfg.inventory = 0;
   CHECK(!sleep_cfg_any(&cfg));
   cfg.power_lock = 1;
   CHECK(sleep_cfg_any(&cfg));
}

/* ---- CONFIG.INI ------------------------------------------------------- */
static void write_ini(const char *path, const char *text)
{
   FILE *f = fopen(path, "w");
   CHECK(f != NULL);
   if (f)
   {
      fputs(text, f);
      fclose(f);
   }
}

static void test_config(void)
{
   char path[] = "/tmp/t_sleep_q_XXXXXX";
   int fd = mkstemp(path);
   CHECK(fd >= 0);
   if (fd >= 0)
      close(fd);

   write_ini(path, "standby = 1\n");
   pcfg_load(path);
   CHECK(g_pcfg.sleep.stop_audio == 1 && g_pcfg.sleep.stop_writer == 1);
   CHECK(g_pcfg.sleep.close_files == 1 && g_pcfg.sleep.stop_home == 1);
   CHECK(g_pcfg.sleep.net_term == 1 && g_pcfg.sleep.hold_loop == 1);
   CHECK(g_pcfg.sleep.power_lock == 1 && g_pcfg.sleep.inventory == 1);

   write_ini(path,
             "sleep_stop_audio = 0\nsleep_stop_writer = 0\n"
             "sleep_close_files = 0\nsleep_stop_home = 0\n"
             "sleep_net_term = 0\nsleep_hold_loop = 0\n"
             "sleep_power_lock = 0\nsleep_inventory = 0\n");
   pcfg_load(path);
   CHECK(g_pcfg.sleep.stop_audio == 0 && g_pcfg.sleep.stop_writer == 0);
   CHECK(g_pcfg.sleep.close_files == 0 && g_pcfg.sleep.stop_home == 0);
   CHECK(g_pcfg.sleep.net_term == 0 && g_pcfg.sleep.hold_loop == 0);
   CHECK(g_pcfg.sleep.power_lock == 0 && g_pcfg.sleep.inventory == 0);

   /* one off, the rest default; a stray value reads as on */
   write_ini(path, "sleep_stop_audio = 0\nsleep_power_lock = 7\n");
   pcfg_load(path);
   CHECK(g_pcfg.sleep.stop_audio == 0);
   CHECK(g_pcfg.sleep.power_lock == 1);
   CHECK(g_pcfg.sleep.stop_writer == 1 && g_pcfg.sleep.hold_loop == 1);

   /* never written back: these are bisect switches, not settings */
   write_ini(path, "standby = 1\n");
   pcfg_load(path);
   pcfg_save();
   {
      char buf[16384];
      FILE *f = fopen(path, "r");
      size_t n = f ? fread(buf, 1, sizeof(buf) - 1, f) : 0;
      if (f)
         fclose(f);
      buf[n] = '\0';
      CHECK(strstr(buf, "sleep_") == NULL);
   }
   unlink(path);
}

int main(void)
{
   test_order_all_on();
   test_only_restart_what_stopped();
   test_toggles();
   test_config();
   if (failures)
   {
      fprintf(stderr, "sleep_q: %d of %d checks FAILED\n", failures, checks);
      return 1;
   }
   printf("sleep_q: %d checks passed (order, restart-only-what-stopped, "
          "toggles, handle ownership, CONFIG.INI keys)\n", checks);
   return 0;
}

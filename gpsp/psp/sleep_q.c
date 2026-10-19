/* sleep_q.c -- see sleep_q.h.  Pure C: the host test links this file. */
#include <stdio.h>
#include <string.h>

#include "sleep_q.h"

static void sq_note(const sleep_q_ops *ops, const char *line)
{
   if (ops->note)
      ops->note(ops->ctx, line);
}

static void sq_notef_rc(const sleep_q_ops *ops, const char *what, int rc)
{
   char line[96];
   snprintf(line, sizeof(line), "q %s rc=%d", what, rc);
   sq_note(ops, line);
}

static void sq_skip(const sleep_q_ops *ops, const char *what)
{
   char line[64];
   snprintf(line, sizeof(line), "q %s skipped cfg=0", what);
   sq_note(ops, line);
}

int sleep_cfg_any(const sleep_cfg *cfg)
{
   return cfg && (cfg->stop_audio || cfg->stop_writer || cfg->close_files ||
                  cfg->stop_home || cfg->net_term || cfg->hold_loop ||
                  cfg->power_lock || cfg->inventory);
}

int sleep_q_down(sleep_q *q, const sleep_cfg *cfg, const sleep_q_ops *ops)
{
   int n = 0, rc, writer_quiet;

   if (!q || !cfg || !ops || q->down)
      return 0;
   q->down = 1;
   q->stopped = 0;
   q->ran = 0;

   /* 1. Sound.  TYL before_pause: StopSoundThread (join + delete).  The
    *    channel is released by the thread on its way out. */
   if (cfg->stop_audio && ops->audio_stop)
   {
      q->ran |= SQ_STEP_AUDIO;
      rc = ops->audio_stop(ops->ctx);
      sq_notef_rc(ops, "audio_stop", rc);
      if (rc == SQ_DONE)
      {
         q->stopped |= SQ_STEP_AUDIO;
         n++;
      }
   }
   else
      sq_skip(ops, "audio_stop");

   /* 2. The writer.  Its last pass lands the .sav (the callback asked for a
    *    scan before parking us), then the sink goes synchronous. */
   writer_quiet = 0;
   if (cfg->stop_writer && ops->writer_stop)
   {
      q->ran |= SQ_STEP_WRITER;
      rc = ops->writer_stop(ops->ctx);
      sq_notef_rc(ops, "writer_stop", rc);
      if (rc == SQ_DONE)
      {
         q->stopped |= SQ_STEP_WRITER;
         n++;
      }
      /* Terminated (rc < 0) still means the thread is gone. */
      writer_quiet = 1;
   }
   else
      sq_skip(ops, "writer_stop");

   /* 3. Long-lived handles.  The .sav and the event log belong to the
    *    writer while it runs, so they close only when it is quiet; the ROM
    *    handle is the emulation thread's own and always may. */
   if (cfg->close_files && ops->files_close)
   {
      char detail[64] = "";
      char line[112];
      q->ran |= SQ_STEP_FILES;
      rc = ops->files_close(ops->ctx, writer_quiet, detail, sizeof(detail));
      snprintf(line, sizeof(line), "q fd_close n=%d %s", rc, detail);
      sq_note(ops, line);
      if (rc > 0)
      {
         q->stopped |= SQ_STEP_FILES;
         n++;
      }
   }
   else
      sq_skip(ops, "fd_close");

   /* 4. The HOME poller (a kernel module thread polling every 16 ms). */
   if (cfg->stop_home && ops->home_stop)
   {
      q->ran |= SQ_STEP_HOME;
      rc = ops->home_stop(ops->ctx);
      sq_notef_rc(ops, "home_stop", rc);
      if (rc == SQ_DONE)
      {
         q->stopped |= SQ_STEP_HOME;
         n++;
      }
   }
   else
      sq_skip(ops, "home_stop");

   /* 5. The radio.  A session does not survive a sleep anyway; ending it
    *    here unloads the adhoc modules before the WLAN chip loses power. */
   if (cfg->net_term && ops->net_term)
   {
      q->ran |= SQ_STEP_NET;
      rc = ops->net_term(ops->ctx);
      sq_notef_rc(ops, "net_term", rc);
      if (rc == SQ_DONE)
      {
         q->stopped |= SQ_STEP_NET;
         n++;
      }
   }
   else
      sq_skip(ops, "net_term");

   return n;
}

int sleep_q_up(sleep_q *q, const sleep_q_ops *ops)
{
   int n = 0, rc;

   if (!q || !ops || !q->down)
      return 0;
   q->down = 0;

   /* The radio is not brought back: the session it carried is over (the
    * partner noticed the silence long ago).  The player starts a new one. */
   if (q->stopped & SQ_STEP_NET)
      sq_note(ops, "q net_up rc=1 (session ended)");

   if ((q->stopped & SQ_STEP_HOME) && ops->home_rearm)
   {
      rc = ops->home_rearm(ops->ctx);
      sq_notef_rc(ops, "home_rearm", rc);
      if (rc == SQ_DONE)
         n++;
   }

   /* Every handle we closed reopens itself on first use (the .sav writer
    * and the ROM page loader both reopen by path); only the event log needs
    * a hand.  Ask even when nothing was closed: it is cheap and logs. */
   if ((q->ran & SQ_STEP_FILES) && ops->files_reopen)
   {
      char detail[64] = "";
      char line[112];
      rc = ops->files_reopen(ops->ctx, detail, sizeof(detail));
      snprintf(line, sizeof(line), "q fd_reopen rc=%d %s", rc, detail);
      sq_note(ops, line);
      if (rc == SQ_DONE)
         n++;
   }

   if ((q->stopped & SQ_STEP_WRITER) && ops->writer_start)
   {
      rc = ops->writer_start(ops->ctx);
      sq_notef_rc(ops, "writer_start", rc);
      if (rc == SQ_DONE)
         n++;
   }

   /* Sound last, as TYL's after_pause: nothing is queued for it to play
    * that predates the sleep. */
   if ((q->stopped & SQ_STEP_AUDIO) && ops->audio_start)
   {
      rc = ops->audio_start(ops->ctx);
      sq_notef_rc(ops, "audio_start", rc);
      if (rc == SQ_DONE)
         n++;
   }

   q->stopped = 0;
   q->ran = 0;
   return n;
}

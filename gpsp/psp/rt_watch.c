/* rt_watch.c -- see rt_watch.h.  Pure C: the host test links this file. */
#include <stdio.h>
#include <string.h>

#include "rt_watch.h"

static const char *const k_names[RTW_SLOTS] = {
   "main", "audio", "io", "me", "home"
};

void rtw_reset(rtw_state *s)
{
   memset(s, 0, sizeof(*s));
}

unsigned rtw_step(rtw_state *s, const unsigned now[RTW_SLOTS],
                  unsigned expect, unsigned dt_ms)
{
   unsigned before, ev = 0, longest = 0;
   int i;

   s->fresh = s->moved = s->dropped = 0;
   if (!s->primed)
   {
      memcpy(s->last, now, sizeof(s->last));
      memset(s->age_ms, 0, sizeof(s->age_ms));
      s->stalled = s->reported = 0;
      s->episode_ms = 0;
      s->primed = 1;
      return 0;
   }
   if (dt_ms > RTW_DT_CAP_MS)
      dt_ms = RTW_DT_CAP_MS;
   before = s->stalled;

   for (i = 0; i < RTW_SLOTS; i++)
   {
      unsigned bit = RTW_BIT(i);
      if (now[i] != s->last[i])
      {
         s->last[i] = now[i];
         s->age_ms[i] = 0;
         s->moved |= bit;
         s->stalled &= ~bit;
         continue;
      }
      if (!(expect & bit))
      {
         s->age_ms[i] = 0;
         if (s->stalled & bit)
         {
            s->stalled &= ~bit;
            s->dropped |= bit;
         }
         continue;
      }
      s->age_ms[i] += dt_ms;
      if (s->age_ms[i] > RTW_LIMIT_MS)
         s->stalled |= bit;
   }

   if (!before && s->stalled)
   {
      for (i = 0; i < RTW_SLOTS; i++)
         if ((s->stalled & RTW_BIT(i)) && s->age_ms[i] > longest)
            longest = s->age_ms[i];
      s->episodes++;
      s->reported = s->fresh = s->stalled;
      s->episode_ms = longest;
      ev = RTW_EV_STALL;
   }
   else if (before)
   {
      s->episode_ms += dt_ms;
      if (!s->stalled)
         ev = RTW_EV_CLEAR;
      else if (s->stalled & ~s->reported)
      {
         s->fresh = s->stalled & ~s->reported;
         s->reported |= s->stalled;
         ev = RTW_EV_GROW;
      }
   }
   return ev;
}

const char *rtw_slot_name(int slot)
{
   return slot >= 0 && slot < RTW_SLOTS ? k_names[slot] : "?";
}

int rtw_mask_names(char *d, size_t n, unsigned mask)
{
   size_t len = 0;
   int i;

   if (!n)
      return 0;
   d[0] = '\0';
   for (i = 0; i < RTW_SLOTS; i++)
   {
      int w;
      if (!(mask & RTW_BIT(i)))
         continue;
      w = snprintf(d + len, n - len, "%s%s", len ? "+" : "", k_names[i]);
      if (w < 0)
         break;
      len = len + (size_t)w < n ? len + (size_t)w : n - 1;
   }
   if (!len)
      len = (size_t)snprintf(d, n, "-");
   return (int)(len < n ? len : n - 1);
}

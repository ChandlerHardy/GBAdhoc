/* rt_log.c -- see rt_log.h.  Linked only into a GPSP_RUNTIME_LOG build. */
#ifdef GPSP_RUNTIME_LOG
#include <pspkernel.h>
#include <pspiofilemgr.h>
#include <psprtc.h>
#include <psppower.h>
#include <kubridge.h>
#include <systemctrl.h>

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "rt_log.h"

static char   g_rt_dir[160], g_rt_path[176], g_rt_old[180];
static SceUID g_rt_sema = -1;
static int    g_rt_on;

/* The lock keeps two threads' lines from landing on the same offset.  It is
 * best effort by design: a thread that cannot have it within half a second
 * (the holder stuck inside the FAT driver -- the very case being recorded)
 * writes anyway, rather than losing the line or joining the hang. */
static int rt_lock(void)
{
   SceUInt tmo = 500000;
   if (g_rt_sema < 0)
      return 0;
   return sceKernelWaitSema(g_rt_sema, 1, &tmo) >= 0;
}

static void rt_unlock(int held)
{
   if (held)
      sceKernelSignalSema(g_rt_sema, 1);
}

void rt_write(const char *text, int n)
{
   int held, size;
   SceUID fd;

   if (!g_rt_on || n <= 0)
      return;
   held = rt_lock();
   rt_io_mark(1);
   fd = sceIoOpen(g_rt_path, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_APPEND, 0777);
   if (fd >= 0)
   {
      size = sceIoLseek32(fd, 0, PSP_SEEK_END);
      if (size > 0 && (unsigned)size + (unsigned)n > RT_LOG_CAP)
      {
         /* One generation: never ask the FAT driver to rename onto an
          * existing file (fe_util.c's atomic-replace note). */
         sceIoClose(fd);
         sceIoRemove(g_rt_old);
         sceIoRename(g_rt_path, g_rt_old);
         fd = sceIoOpen(g_rt_path, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_TRUNC,
                        0777);
      }
      if (fd >= 0)
      {
         sceIoWrite(fd, text, (SceSize)n);
         sceIoClose(fd);              /* the close IS the commit */
      }
   }
   rt_io_mark(0);
   rt_unlock(held);
}

static int rt_vline(char *d, size_t n, const char *fmt, va_list ap)
{
   unsigned long long us = sceKernelGetSystemTimeWide();
   int a, b;

   if (n < 32)
      return 0;
   a = snprintf(d, n, "%u.%03u ", (unsigned)(us / 1000000ull),
                (unsigned)((us / 1000ull) % 1000ull));
   if (a < 0 || (size_t)a >= n)
      return 0;
   b = vsnprintf(d + a, n - (size_t)a - 1, fmt, ap);
   if (b < 0)
      return 0;
   if ((size_t)(a + b) > n - 2)
      b = (int)(n - 2) - a;            /* clipped: keep the newline */
   d[a + b] = '\n';
   d[a + b + 1] = '\0';
   return a + b + 1;
}

int rt_line(char *d, size_t n, const char *fmt, ...)
{
   va_list ap;
   int len;
   va_start(ap, fmt);
   len = rt_vline(d, n, fmt, ap);
   va_end(ap);
   return len;
}

void rt_note(const char *fmt, ...)
{
   char line[256];
   va_list ap;
   int len;
   va_start(ap, fmt);
   len = rt_vline(line, sizeof(line), fmt, ap);
   va_end(ap);
   rt_write(line, len);
}

/* PLUGIN CONTEXT, once at boot (docs: the BetterBright/QuietVol freeze of
 * 2026-10-27).  Both are kernel modules, invisible to the user-mode module
 * list (standby.log's census shows only ours), so ask the CFW's kubridge.
 * Then the first two instruction words of the kernel's sceDisplaySetFrameBuf:
 * BetterBright, chained after QuietVol, hijacks the function ENTRY (a `j`
 * there), QuietVol only the syscall slot.  The address is read only if it
 * lies in kernel RAM and is word aligned, so a CFW that answers nonsense
 * costs a line, not a bus error at boot. */
static void rt_plugins(void)
{
   static unsigned char modbuf[512] __attribute__((aligned(64)));
   static const char *const names[] = { "BetterBright", "QuietVol" };
   char line[256];
   int len = 0, i, n;
   u32 fn;
   unsigned w0 = 0, w1 = 0;

   for (i = 0; i < 2; i++)
   {
      int rc;
      memset(modbuf, 0, sizeof(modbuf));
      rc = kuKernelFindModuleByName((char *)names[i], (SceModule *)modbuf);
      n = snprintf(line + len, sizeof(line) - (size_t)len, "%s%s=%s",
                   len ? " " : "", names[i], rc >= 0 ? "loaded" : "absent");
      if (n > 0 && (size_t)(len + n) < sizeof(line))
         len += n;
   }
   fn = sctrlHENFindFunction("sceDisplay_Service", "sceDisplay", 0x289D82FE);
   if (fn >= 0x88000000u && fn < 0x8A000000u && !(fn & 3u))
   {
      w0 = kuKernelPeekw((void *)fn);
      w1 = kuKernelPeekw((void *)(fn + 4u));
   }
   rt_note("plugins %s setframebuf=0x%08X w0=%08X w1=%08X j_at_entry=%d",
           len ? line : "-", (unsigned)fn, w0, w1,
           (w0 >> 26) == 2u || (w0 >> 26) == 3u);
}

void rt_log_init(const char *base_dir)
{
   ScePspDateTime dt;
   int rc;

   snprintf(g_rt_dir, sizeof(g_rt_dir), "%s/log", base_dir);
   snprintf(g_rt_path, sizeof(g_rt_path), "%s/runtime.log", g_rt_dir);
   snprintf(g_rt_old, sizeof(g_rt_old), "%s/runtime.log.1", g_rt_dir);
   sceIoMkdir(g_rt_dir, 0777);          /* an existing one just fails */
   g_rt_sema = sceKernelCreateSema("gpsp_rtlog", 0, 1, 1, NULL);
   g_rt_on = 1;
   memset(&dt, 0, sizeof(dt));
   rc = sceRtcGetCurrentClockLocalTime(&dt);
   rt_note("=== boot runtime.log v1 wall=%04u-%02u-%02u %02u:%02u:%02u "
           "local (rc=%d) model=%d fw=0x%08X cpu=%d bus=%d",
           (unsigned)dt.year, (unsigned)dt.month, (unsigned)dt.day,
           (unsigned)dt.hour, (unsigned)dt.minute, (unsigned)dt.second, rc,
           kuKernelGetModel(), (unsigned)sceKernelDevkitVersion(),
           scePowerGetCpuClockFrequency(), scePowerGetBusClockFrequency());
   rt_plugins();
}
#endif /* GPSP_RUNTIME_LOG */

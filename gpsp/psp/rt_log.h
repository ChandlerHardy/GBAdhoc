/* rt_log.h -- log/runtime.log, the GPSP_RUNTIME_LOG build's trail of what the
 * game was doing and, from the watchdog (main_psp.c rtw_*), which thread had
 * stopped where.  Diagnostic only: without -DGPSP_RUNTIME_LOG every macro here
 * is empty and rt_log.o / rt_watch.o are not linked (psp/Makefile), so the
 * binary is the one built without this file (tools/build.sh runtimelog vs
 * sleepdiag; docs/BUILD-SWITCHES.md).
 *
 * THE SAME DISCIPLINE AS standby_note: every line (or block) is one
 * open / write / close, because FAT commits the length on close and a hard
 * power-off keeps only what was closed.  So it is for rare events only --
 * boot, a ROM load, a state save, a menu opening, a teardown step -- and
 * NEVER on the frame path; the per-frame facts are plain volatile words the
 * watchdog reads.  Lines are "<seconds>.<ms> <text>" with the console's
 * uptime (sceKernelGetSystemTimeWide); the boot line carries the wall clock
 * once so the two can be lined up.  At ~256 KiB the file moves to
 * runtime.log.1 (one generation kept). */
#ifndef RT_LOG_H
#define RT_LOG_H

#include <stddef.h>

#ifdef GPSP_RUNTIME_LOG

#define RT_LOG_CAP (256u * 1024u)

/* Paths, the log directory, the lock, the boot and plugin lines.  Main
 * thread, once, after init_paths. */
void rt_log_init(const char *base_dir);
/* One timestamped line.  Any thread with ~1.5 KiB of stack to spare (the
 * main and watchdog threads); never the callback thread. */
void rt_note(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
/* One timestamped line into d (with its '\n'); returns its length. */
int  rt_line(char *d, size_t n, const char *fmt, ...)
   __attribute__((format(printf, 3, 4)));
/* A finished block of lines, one open / write / close. */
void rt_write(const char *text, int n);
/* "Inside sceIo since t": set before a file operation, cleared after, in a
 * word per thread the watchdog reports (main_psp.c). */
void rt_io_mark(int on);

#define RT_NOTE(...) rt_note(__VA_ARGS__)
#define RT_IO(on)    rt_io_mark(on)

#else

#define RT_NOTE(...) ((void)0)
#define RT_IO(on)    ((void)0)

#endif

#endif /* RT_LOG_H */

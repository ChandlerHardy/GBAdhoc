/* rt_note for host tests that compile production PSP files with
 * -DGPSP_RUNTIME_LOG (psp/rt_log.h): counts and prints the line, writes
 * nothing.  tools/run_host_tests.py links it beside test_video_buffers.c so
 * the real vid_swap is also run through its GPSP_RUNTIME_LOG branch -- the
 * branch that has to keep upstream's "SetFrameBuf failed: return 0, keep the
 * frame" contract (4.5.0 made vid_swap return int). */
#include <stdarg.h>
#include <stdio.h>

unsigned rt_note_count;

void rt_note(const char *fmt, ...)
{
   va_list ap;
   va_start(ap, fmt);
   fputs("rt_note: ", stdout);
   vprintf(fmt, ap);
   fputc('\n', stdout);
   va_end(ap);
   rt_note_count++;
}

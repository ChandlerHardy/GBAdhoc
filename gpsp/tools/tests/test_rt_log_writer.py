#!/usr/bin/env python3
"""psp/rt_log.c's writer, as shipped, against a fake sceIo (MAGI f-015/f-016).

1. A writer that cannot have the lock within its timeout writes NOTHING (two
   unlocked appends at one offset overwrite each other) and counts the drop;
   the next line that is written says how many were dropped.
2. Rotation: over the cap, runtime.log becomes runtime.log.1 and a new file
   starts -- but only when the rename succeeded; a failed rename never
   truncates the only copy (the line is appended instead).
3. One write is one open / write(s) / close, inside the sceIo mark.
Then mutants against rt_log.c: each must fail a check.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
RT_LOG_C = ROOT / "psp/rt_log.c"

FAKE_SDK = r'''
#ifndef FAKE_PSP_H
#define FAKE_PSP_H
#include <stddef.h>
#include <string.h>
typedef int SceUID;
typedef unsigned SceUInt;
typedef unsigned SceSize;
typedef unsigned u32;
typedef struct { unsigned short year, month, day, hour, minute, second;
                 unsigned microsecond; } ScePspDateTime;
typedef struct { char pad[160]; } SceModule;
#define PSP_O_WRONLY 0x0002
#define PSP_O_APPEND 0x0100
#define PSP_O_CREAT  0x0200
#define PSP_O_TRUNC  0x0400
#define PSP_SEEK_END 2
int sceKernelWaitSema(SceUID id, int n, SceUInt *t);
int sceKernelSignalSema(SceUID id, int n);
SceUID sceKernelCreateSema(const char *n, unsigned a, int i, int m, void *o);
unsigned long long sceKernelGetSystemTimeWide(void);
SceUID sceIoOpen(const char *p, int f, int m);
int sceIoLseek32(SceUID fd, int off, int wh);
int sceIoWrite(SceUID fd, const void *b, SceSize n);
int sceIoClose(SceUID fd);
int sceIoRemove(const char *p);
int sceIoRename(const char *a, const char *b);
int sceIoMkdir(const char *p, int m);
int sceRtcGetCurrentClockLocalTime(ScePspDateTime *t);
int kuKernelGetModel(void);
int sceKernelDevkitVersion(void);
int scePowerGetCpuClockFrequency(void);
int scePowerGetBusClockFrequency(void);
int kuKernelFindModuleByName(char *n, SceModule *m);
u32 sctrlHENFindFunction(const char *m, const char *l, u32 nid);
unsigned kuKernelPeekw(void *a);
#endif
'''

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "pspkernel.h"
#include "rt_log.h"
static int checks, failures;
#define CHECK(c) do { checks++; if (!(c)) { failures++; \
   fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
/* ---- the fake card: two files ---- */
static char cur[8192], old[8192];
static int cur_n, old_n, cur_exists, old_exists, cur_size;
static int lock_ok = 1, rename_ok = 1, opens, truncs, open_now, mark_depth, marked_writes;
static int sem_count = 1;
int sceKernelWaitSema(SceUID id, int n, SceUInt *t) { (void)id; (void)n; (void)t;
   if (!lock_ok)
      return -0x7FFDFE58;
   sem_count--;
   return 0; }
int sceKernelSignalSema(SceUID id, int n) { (void)id; sem_count += n; return 0; }
SceUID sceKernelCreateSema(const char *n, unsigned a, int i, int m, void *o)
{ (void)n; (void)a; (void)i; (void)m; (void)o; return 9; }
unsigned long long sceKernelGetSystemTimeWide(void) { return 12345678ull; }
static int is_cur(const char *p) { return strstr(p, "runtime.log") && !strstr(p, ".1"); }
SceUID sceIoOpen(const char *p, int f, int m)
{
   (void)m;
   if (!is_cur(p)) return -1;
   opens++; open_now = 1;
   if (f & PSP_O_TRUNC) { truncs++; cur_n = 0; cur_size = 0; }
   cur_exists = 1;
   return 3;
}
int sceIoLseek32(SceUID fd, int off, int wh) { (void)fd; (void)off; (void)wh; return cur_size; }
int sceIoWrite(SceUID fd, const void *b, SceSize n)
{ (void)fd; cur_size += (int)n;
  if (cur_n + (int)n < (int)sizeof(cur)) { memcpy(cur + cur_n, b, n); cur_n += (int)n; cur[cur_n] = 0; }
  if (mark_depth)
     marked_writes++;
  return (int)n; }
int sceIoClose(SceUID fd) { (void)fd; open_now = 0; return 0; }
int sceIoRemove(const char *p) { if (strstr(p, ".1")) { old_exists = 0; old_n = 0; } return 0; }
int sceIoRename(const char *a, const char *b)
{
   (void)a; (void)b;
   if (!rename_ok) return -1;
   memcpy(old, cur, (size_t)cur_n); old_n = cur_n; old_exists = 1;
   cur_n = 0; cur_size = 0; cur_exists = 0;
   return 0;
}
int sceIoMkdir(const char *p, int m) { (void)p; (void)m; return 0; }
int sceRtcGetCurrentClockLocalTime(ScePspDateTime *t) { memset(t, 0, sizeof(*t)); return 0; }
int kuKernelGetModel(void) { return 2; }
int sceKernelDevkitVersion(void) { return 0x06060010; }
int scePowerGetCpuClockFrequency(void) { return 333; }
int scePowerGetBusClockFrequency(void) { return 166; }
int kuKernelFindModuleByName(char *n, SceModule *m) { (void)n; (void)m; return -1; }
u32 sctrlHENFindFunction(const char *m, const char *l, u32 nid) { (void)m; (void)l; (void)nid; return 0; }
unsigned kuKernelPeekw(void *a) { (void)a; return 0; }
void rt_io_mark(int on) { mark_depth += on ? 1 : -1; }
int main(void)
{
   int before;
   rt_log_init("ms0:/PSP/GAME/GBAdhoc");
   CHECK(cur_n > 0 && strstr(cur, "=== boot runtime.log") != NULL);
   CHECK(sem_count == 1 && mark_depth == 0 && !open_now);

   /* 1. the lock is not had: nothing is written, the drop is counted ... */
   before = cur_n; opens = 0;
   lock_ok = 0;
   rt_note("lost one");
   rt_note("lost two");
   CHECK(cur_n == before && opens == 0);
   /* ... and said on the next line that is written */
   lock_ok = 1;
   rt_note("next");
   CHECK(strstr(cur, "rt_dropped n=2") != NULL && strstr(cur, "next") != NULL);
   CHECK(strstr(cur, "lost") == NULL);
   CHECK(sem_count == 1 && mark_depth == 0 && marked_writes > 0);
   before = cur_n;
   rt_note("again");
   CHECK(strstr(cur + before, "rt_dropped") == NULL);   /* said once */

   /* 2. rotation: over the cap the file moves to .1, a new one starts */
   cur_size = (int)RT_LOG_CAP - 10;  /* the file's length as lseek reports it */
   rename_ok = 1; truncs = 0;
   rt_note("after rotation");
   CHECK(old_exists && truncs == 1 && cur_size < 64);
   CHECK(cur_n >= 15 && strcmp(cur + cur_n - 15, "after rotation\n") == 0);
   /*    a failed rename never truncates the only copy */
   cur_size = (int)RT_LOG_CAP - 10;
   rename_ok = 0; truncs = 0;
   rt_note("kept");
   CHECK(truncs == 0 && cur_size > (int)RT_LOG_CAP - 10);
   CHECK(sem_count == 1 && mark_depth == 0 && !open_now);
   printf("rt_log writer: %d checks, %d failures\n", checks, failures);
   return failures ? 1 : 0;
}
'''


def run(rt_log_text, expect_pass):
    with tempfile.TemporaryDirectory(prefix="gbadhoc-rtwriter-") as d:
        d = Path(d)
        inc = d / "inc"
        inc.mkdir()
        (inc / "pspkernel.h").write_text(FAKE_SDK)
        for h in ("pspiofilemgr.h", "psprtc.h", "psppower.h", "kubridge.h",
                  "systemctrl.h"):
            (inc / h).write_text('#include "pspkernel.h"\n')
        src = d / "rt_log.c"
        src.write_text(rt_log_text)
        (d / "h.c").write_text(HARNESS)
        b = d / "h"
        cc = subprocess.run(["cc", "-std=gnu99", "-O1", "-g", "-Wall", "-Wextra",
                             "-Werror", "-Wno-unused-parameter", "-DGPSP_RUNTIME_LOG",
                             "-I" + str(inc), "-I" + str(ROOT / "psp"),
                             str(d / "h.c"), str(src), "-o", str(b)],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            raise AssertionError("compile failed\n" + cc.stderr)
        r = subprocess.run([str(b)], capture_output=True, text=True, timeout=30)
        if (r.returncode == 0) != expect_pass:
            raise AssertionError("expected %s\n%s%s" % (
                "pass" if expect_pass else "failure", r.stdout, r.stderr))
        return r


def main():
    text = RT_LOG_C.read_text()
    print(run(text, True).stdout.strip())
    mutants = [
        ("writes without the lock after a timeout",
         "   if (!rt_lock(&held))\n   {\n      g_rt_dropped++;\n      return;\n   }\n",
         "   (void)rt_lock(&held);\n"),
        ("truncates although the rename failed",
         "         if (sceIoRename(g_rt_path, g_rt_old) >= 0)\n",
         "         if (sceIoRename(g_rt_path, g_rt_old) >= 0 || 1)\n"),
        ("the drops are never told",
         "   if (g_rt_dropped)\n", "   if (0 && g_rt_dropped)\n"),
    ]
    for label, old, new in mutants:
        assert text.count(old) == 1, label + ": production text not found"
        run(text.replace(old, new, 1), False)
        print("mutant (%s): failed as it must" % label)
    print("%d mutants, all killed" % len(mutants))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Exercise the production PSP power callback with controlled event sequences."""
from pathlib import Path
import subprocess
import tempfile

from test_psp_runtime import function

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "psp/main_psp.c").read_text()
callback = function(source, "power_cb")

stub = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#define PSP_POWER_CB_POWER_SWITCH 0x80000000u
#define PSP_POWER_CB_SUSPENDING 0x00010000u
#define PSP_POWER_CB_RESUMING 0x00020000u
#define PSP_POWER_CB_RESUME_COMPLETE 0x00040000u
#define PWR_PARK_WAIT_US 250000u
#define FE_EVT_ONLY(x) ((void)(x))
#define fe_evt(...) ((void)0)
static struct { int standby; } g_pcfg = { 1 };
static int g_pwr_slept, g_pwr_parked = 1, g_pwr_park_req;
static int g_pwr_suspend, g_pwr_resume, g_pwr_rebuild, g_pwr_gb_flush_req;
static int down_calls, notes, scan_calls, wakes, disarms;
static unsigned clock_us;
static void home_host_disarm(void) { disarms++; }
static void fe_host_sram_request_scan(void) { scan_calls++; }
static void standby_note(const char *fmt, ...) { (void)fmt; notes++; }
static void io_wake(void) { wakes++; }
static void sceKernelDelayThread(unsigned us) { clock_us += us; }
static unsigned sceKernelGetSystemTimeLow(void) { return ++clock_us; }
static int me_host_loaded(void) { return 0; }
static int me_host_idle(void) { return 1; }
static int me_rend_active(void) { return 1; }
static int me_rend_release_vmem(void) { return 1; }
static void me_standby_down(void) { down_calls++; g_pwr_slept = 1; }
@CALLBACK@
int main(void)
{
    power_cb(0, PSP_POWER_CB_POWER_SWITCH, NULL);
    assert(down_calls == 1 && g_pwr_slept == 1);
    assert(scan_calls == 1 && g_pwr_suspend == 1);
    power_cb(0, PSP_POWER_CB_SUSPENDING, NULL);
    assert(down_calls == 1 && scan_calls == 1); /* duplicate event */
    power_cb(0, PSP_POWER_CB_RESUMING, NULL);
    power_cb(0, PSP_POWER_CB_RESUME_COMPLETE, NULL);
    assert(g_pwr_rebuild == 1 && g_pwr_resume == 1);
    g_pwr_slept = 0;
    power_cb(0, PSP_POWER_CB_SUSPENDING, NULL);
    assert(down_calls == 2); /* inactivity-driven suspend still works */
    assert(notes >= 5 && wakes >= 3 && disarms == 2);
    puts("power callback: switch-only, duplicate, resume and suspending-only pass");
    return 0;
}
'''


def run(body, expect_pass):
    with tempfile.TemporaryDirectory(prefix="gbadhoc-power-") as folder:
        cfile = Path(folder) / "power.c"
        binary = Path(folder) / "power"
        cfile.write_text(stub.replace("@CALLBACK@", body))
        subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        str(cfile), "-o", str(binary)], check=True)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        if (result.returncode == 0) != expect_pass:
            raise AssertionError(result.stdout + result.stderr)
        return result


print(run(callback, True).stdout.strip())
# One wrong input flag must make the test fail in the real callback's path.
mutant = callback.replace(
    "(PSP_POWER_CB_POWER_SWITCH | PSP_POWER_CB_SUSPENDING)) &&",
    "PSP_POWER_CB_SUSPENDING) &&", 1)
assert mutant != callback
bad = run(mutant, False)
assert "down_calls == 1" in bad.stderr, bad.stderr
print("mutant (manual-switch branch removed): down_calls assertion failed")

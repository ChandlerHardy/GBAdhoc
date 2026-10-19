# PSP-3001 sleep/wake investigation

## Status and limits

The exact source tag for **snes9xTYL Mod 180404** is
[`esmjanus/snes9xTYL` tag `180404`](https://github.com/esmjanus/snes9xTYL/releases/tag/180404),
commit `6ce09a0`. Read-only clones are in `~/repos/gbadhoc-sleep-refs/`:
`snes9xTYL-180404`, `snes9xTYL-173210`, and `snes9x-euphoria`.
The 180404 fork credits YoyoFR/Laxer3a, Ruka/33(76), and 173210
([README.md:145-147](../../gbadhoc-sleep-refs/snes9xTYL-180404/README.md#L145)).
Euphoria's own project description calls it a *continuation of Snes9xTYL*
([google_code_project_home.txt:1-4](../../gbadhoc-sleep-refs/snes9x-euphoria/google_code_project_home.txt#L1));
the lineage is TYL → Euphoria, while the 180404 TYL Mod is another later branch.
The two descendants are related, but one is not simply a later release of the other.

No PSP-3001 log or hardware run was available here. The code proves a missed
manual-switch event path, but does **not** prove that it caused this particular XMB
drop. The diagnostic build and log sequence below are intended to settle that.

## Suspend and resume comparison

| Area | TYL Mod 180404 | Euphoria source | GBAdhoc 4.1.0 and this change |
| --- | --- | --- | --- |
| Power events | `POWER_SWITCH` **or** `SUSPENDING` enters the callback; `RESUMING` takes a lock, calls `InitME`, then `after_pause` if playing. [psp.cpp:2545-2575](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L2545) | Also tests `POWER_SWITCH`; its `ME_SOUND` branch toggles `g_bSleep` but has its pause/stop/GU actions commented out. Its non-ME branch stops sound on `POWER_SWITCH` or `SUSPENDING`. [psp.cpp:538-579](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L538) | Before this patch, only `SUSPENDING` began teardown. Now either flag does, with `g_pwr_slept` guarding a later duplicate. `RESUME_COMPLETE` asks the main loop to rebuild. [main_psp.c:1991-2148](../gpsp/psp/main_psp.c#L1991) |
| Power lock | Takes `scePowerLock(0)` at low-level init; the suspend callback/main-loop pause path calls `scePowerUnlock(0)` after `KillME`; resumes lock again. [psp.cpp:2748-2750](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L2748), [2548-2569](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L2548), [3986-3993](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L3986) | ME builds take an initial lock, but the shown ME power callback never unlocks or restarts ME; its sleep path enters menu processing. [psp.cpp:2095-2100](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L2095), [3133-3140](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L3133) | Uses nested `scePowerLock/Unlock` only around main-thread windows that cannot park (boot, save/load, wireless, teardown, wake). It does not hold a continuous lock through gameplay. [main_psp.c:2150-2207](../gpsp/psp/main_psp.c#L2150) |
| ME | `KillME` resets/clock-gates the second core; `InitME` copies its stub to `0xbfc00040`, writes the entry/mailbox vector at `0xbfc00600/604`, resets/restarts ME, and unregisters Sony's `SceMeRpc` event handler. The PRX stays loaded. [mediaengineprx/main.c:174-260](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/mediaengineprx/main.c#L174) | `InitME` also uploads the stub and resets/restarts ME; `KillME` asserts reset. The retrieved Euphoria PRX source does not replace/unregister `SceMeRpc`. [mediaengineprx/main.c:113-184](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/mediaengineprx/main.c#L113) | The kernel PRX replaces `SceMeRpc`'s event handler and parks/unparks ME at firmware suspend/resume. At default `standby=1`, callback tears down the renderer and releases volatile memory while retaining the module; `standby>=2` also unloads it. Wake rebuilds after the Continue choice. [me/main.c:339-374](../gpsp/psp/me/main.c#L339), [main_psp.c:2949-3065](../gpsp/psp/main_psp.c#L2949) |
| Threads/audio | `before_pause` sets pause and joins/deletes the sound thread. `after_pause` resets the blitter and starts sound again. The audio channel is reserved when opening the device and released on device close, not explicitly at sleep. [psp.cpp:1843-1882](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L1843), [799-834](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L799) | Non-ME callback stops the sound thread and later restarts it. ME callback does not perform that sequence. [psp.cpp:565-579](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L565), [3136-3148](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L3136) | Main loop parks between frames before renderer teardown; audio thread remains alive, with stale ring samples discarded. The audio channel is reserved once in the audio thread and released on thread exit, not per sleep. [main_psp.c:2035-2118](../gpsp/psp/main_psp.c#L2035), [816-924](../gpsp/psp/main_psp.c#L816) |
| Display/GU | `after_pause` clears VRAM and calls `blit_reinit`; normal GU setup uses `sceGuInit`. No explicit `sceGuTerm`/`sceGuInit` pair on each wake. [psp.cpp:1859-1877](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L1859), [blitter.c:65-71](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/blitter.c#L65) | Non-ME wake calls `after_pause` and thus `blit_reinit`; ME switch callback's `sceGuDisplay` calls are commented out. [psp.cpp:545-579](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L545), [1390-1421](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L1390) | Snapshots the frame before teardown, blanks VRAM, shows a wake overlay, then restarts the renderer on Continue. [main_psp.c:2955-2999](../gpsp/psp/main_psp.c#L2955), [14016-14074](../gpsp/psp/main_psp.c#L14016) |
| Memory Stick handles | The ROM is loaded into RAM and its `FILE*` closed before play; snapshot streams are opened/closed per operation. The power callback has no FD recovery. [memmap.cpp:1228-1265](../../gbadhoc-sleep-refs/snes9xTYL-180404/memmap.cpp#L1228), [psp.cpp:2140-2188](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L2140) | Also closes the ROM file after loading it; no handle recovery in the power callback. [memmap.cpp:767-799](../../gbadhoc-sleep-refs/snes9x-euphoria/src/memmap.cpp#L767), [psp.cpp:538-579](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/psp.cpp#L538) | Paged GBA ROM uses a long-lived handle; a short read closes/reopens it by path, then retries. A second failure maps `0xFF`. The `.sav` writer holds a file open but abandons deltas and does a full rewrite after a failed seek/write/flush. The diagnostic `frontend.log` handle stays open and has no automatic reopen, so post-wake events may be absent. [gba_memory.c:2928-2973](../gpsp/gba_memory.c#L2928), [fe_host.c:1905-1935](../gpsp/frontend-common/fe_host.c#L1905), [fe_evt.c:86-146](../gpsp/frontend-common/fe_evt.c#L86) |
| `homehook.prx` | Kernel module polls the HOME button every 10 ms and exposes `readHomeButton`; it does **not** hook power, reset ME, or handle suspend. [homehookprx/main.c:41-105](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/homehookprx/main.c#L41) | Same named module pattern in the Euphoria tree. [homehookprx/main.c:41-105](../../gbadhoc-sleep-refs/snes9x-euphoria/src/psp/homehookprx/main.c#L41) | Separate HOME module; power callback disarms it at sleep. [main_psp.c:1999-2005](../gpsp/psp/main_psp.c#L1999) |

TYL explicitly stops only its sound thread for pause; gameplay is gated by
`Settings.Paused`, while its power callback thread stays registered
([psp.cpp:2545-2586](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L2545),
[1541-1579](../../gbadhoc-sleep-refs/snes9xTYL-180404/psp/psp.cpp#L1541)).
GBAdhoc's main emulation thread parks, but its writer thread remains available
for the requested SRAM scan and event-log drain
([main_psp.c:1999-2019](../gpsp/psp/main_psp.c#L1999),
[500-536](../gpsp/psp/main_psp.c#L500)); its audio thread is not stopped for
sleep ([main_psp.c:816-924](../gpsp/psp/main_psp.c#L816)).

The [PSPSDK power sample](https://github.com/pspdev/pspsdk/blob/master/src/samples/power/main.c)
explicitly treats `POWER_SWITCH || SUSPENDING` as sleep entry, and the
[power header](https://github.com/pspdev/pspsdk/blob/master/src/power/psppower.h)
describes `POWER_SWITCH` as the switch being pushed and `SUSPENDING` as also
possible through inactivity. `scePowerLock` defers a switch request until
unlock. TYL's continuous-lock scheme is materially different from GBAdhoc's
short critical-section locks; copying it would require a larger lifecycle
change, so this patch does not do that. A search of these three source trees
found no `sceKernelPowerLock` call; the observed lock API is `scePowerLock`.

## Ranked hypotheses and falsifiers

1. **Manual switch skipped GBAdhoc teardown.** The old callback tested only
   `SUSPENDING`, unlike the SDK sample and both TYL descendants. If a PSP-3001
   sends `POWER_SWITCH` without a subsequent `SUSPENDING` before suspend,
   renderer pointers and the volatile pool survive into a state where the
   firmware can reclaim that memory. [main_psp.c:1994-2118](../gpsp/psp/main_psp.c#L1994),
   [2949-2999](../gpsp/psp/main_psp.c#L2949). **Falsify:** baseline log shows
   `susp=1`, a complete `step done`, then an XMB drop on the same attempt.
2. **Teardown began but did not finish safely.** A 250 ms frame-park timeout,
   a busy ME, or a failed volatile release deliberately skips/aborts teardown;
   the kernel can still suspend. [main_psp.c:2045-2118](../gpsp/psp/main_psp.c#L2045),
   [2982-2987](../gpsp/psp/main_psp.c#L2982). **Falsify:** failing attempt has
   `parked=1`, `me_idle=1`, `step vmem_released`, and `step done`.
3. **ME/kernel resume interaction.** GBAdhoc's PRX replaces a kernel system
   event handler and reboots its custom ME from a preserved vector. A callback
   timing or ARK-specific reset difference could kill the process before the
   user-side resume callback. [me/main.c:323-375](../gpsp/psp/me/main.c#L323),
   [408-466](../gpsp/psp/me/main.c#L408). TYL instead resets ME before sleep
   and reuploads its stub on resume. **Falsify:** `power resume_complete` and
   `standby up host=0 rend=0` occur, followed by stable gameplay.
4. **Memory Stick handle failure after wake.** This has caused a crash on a
   paged PSP-1000 ROM; it is less likely for a PSP-3001 whose whole cart is
   typically resident. A stale `.sav` handle has a recovery path, but the
   diagnostic log handle does not. Missing post-wake `frontend.log` lines can
   therefore mean log failure rather than process death; use `standby.log`.
   [gba_memory.c:2928-2973](../gpsp/gba_memory.c#L2928),
   [fe_host.c:1905-1935](../gpsp/frontend-common/fe_host.c#L1905),
   [fe_evt.c:104-156](../gpsp/frontend-common/fe_evt.c#L104).
   **Falsify:** `core_health` reports no new `reopens`/`short_reads`, and the
   failure precedes any resumed gameplay.
5. **Normal exit/relaunch failure.** Possible only if a user/exit callback or
   game-list path sets `g_running=0`, or a harness/boot failure path fires.
   The power callback itself never calls `sceKernelExitGame`.
   **Falsify:** no `EVT exit` near the failure and no wake-menu quit choice.

## Every path back to XMB in the PSP app

`sceKernelExitGame` call sites in `gpsp/psp/main_psp.c` are: harness-only
stall watchdog at [8715](../gpsp/psp/main_psp.c#L8715); startup/harness
preflight exits at [12040-12107](../gpsp/psp/main_psp.c#L12040),
[12208-12381](../gpsp/psp/main_psp.c#L12208), memory/load/network failures
at [12881](../gpsp/psp/main_psp.c#L12881),
[13059](../gpsp/psp/main_psp.c#L13059), and
[13127-13150](../gpsp/psp/main_psp.c#L13127); and the final exit at
[14933](../gpsp/psp/main_psp.c#L14933).
The early calls first invoke `handoff_run` and are before active gameplay.
The final call runs after `EVT exit`, SRAM/log shutdown, and an optional
relaunch attempt [14914-14933](../gpsp/psp/main_psp.c#L14914). On normal
play, the exit callback only sets `g_running=0`
[379-385](../gpsp/psp/main_psp.c#L379). The wake menu's game-list choice
deliberately sets `g_running=0` [14033-14054](../gpsp/psp/main_psp.c#L14033).
Thus an actual deliberate exit should leave an `EVT exit` unless storage
fails before the log is committed; a sudden XMB without it favors a kernel
abort/reset over an app-requested exit.

The USB handoff has three additional `sceKernelExitGame` calls, each after
USB teardown failure [usb_handoff.c:474-480](../gpsp/psp/usb_handoff.c#L474),
[520-526](../gpsp/psp/usb_handoff.c#L520),
[550-556](../gpsp/psp/usb_handoff.c#L550). It is only entered *after* the
normal main loop exits, so it cannot independently explain an in-game wake
drop. The handoff relaunch also falls back to XMB if both launch APIs return
[usb_handoff.c:614-645](../gpsp/psp/usb_handoff.c#L614).

## Fix and regression boundaries

The change accepts both PSP suspend-entry flags, records the raw flag word
before slow work in `frontend.log` and a close-per-line `standby.log`, and
uses `g_pwr_slept` to avoid duplicate teardown if both flags arrive. It keeps
the existing frame-park, ME sysevent, snapshot, volatile-memory, wake-overlay,
and failed-rebuild fallback paths. Existing behaviors to preserve are:

| Behavior | Evidence / hardware check |
| --- | --- |
| One successful standby teardown per sleep, even if both flags arrive | Count `step begin`/`step done` against `flags` lines. |
| Manual sleep while a ROM is running opens the wake overlay | `resume_complete slept=1`, then `standby wake overlay_first`. |
| Sleep while the wake overlay is still displayed remains safe | A second `flags ... slept=1` does not produce a second `step begin`; Continue still rebuilds once. |
| Save and ROM page handling remain usable | In-game save persists; `core_health ... short_reads` does not increase. |
| Menu quit still relaunches the game list | `wake_menu choice=game_list`, then `EVT exit reason=game_list`. |

## PSP-3001 A/B test

Use the **diagnostic** EBOOT from the build metadata below, with its matching
`gbadhoc_me.prx` and existing install files. Set `standby = 1` in `CONFIG.INI`
for both builds. Keep an unchanged copy of the 4.1.0 install and its saves.
Do not sleep while the Memory Stick LED is lit.

1. Start one GBA ROM, wait 10 seconds after loading, and save in-game once.
   Wait until the stick LED is off. Put the PSP to sleep with a short downward
   slide, wait 10 seconds, wake it, select **Continue**, and play 20 seconds.
   Repeat 10 times; record each outcome and whether the failure is XMB or a
   full power reset.
2. Repeat the same 10-cycle run with the unmodified-main diagnostic EBOOT,
   restoring the same ROM/config/save setup. Keep each build's `log/` files
   separately. A single successful cycle is not enough for an intermittent
   fault.
3. After each run, collect `log/standby.log`, `log/frontend.log`, and
   `log/frontend.prev.log`. In the **fixed** build's `standby.log`, find each
   `flags=... switch=1` or `susp=1`, `suspend parked=1 ... me_idle=1`, `step begin`,
   `step vmem_released`, `step done`, `resume_complete ... slept=1`, and
   `wake host=0` / `wake rend=0`. In the frontend log, find `power flags`,
   `power resume_complete`, `standby wake overlay_first`, `wake_menu
   choice=continue`, `standby up`, `power back`, `core_health`, and any
   `exit code=`. The unmodified build lacks the new durable `flags` line;
   its frontend `power flags=0x80000000 susp=0` (possibly with other bits set)
   without standby teardown supports hypothesis 1 if that line survives.
   The **last** durable standby line before a failure localizes the failing step.

The simulator can check application sequencing but cannot simulate firmware
suspend, volatile-memory reclamation, ARK-4, or Memory Stick FD invalidation.
Hardware results therefore remain the acceptance gate for the XMB symptom.

## Build artifacts

Both are clean **diagnostic-profile** PSP builds using the same Docker toolchain
and PSP Make flags. Use the fixed build for logging; the release profile
compiles telemetry out. Both bundles contain `EBOOT.PBP`, `gbadhoc_me.prx`,
`gbadhoc_home.prx`, and `build-manifest.json`. The two ME PRX files have the
same SHA-256 (`63d8c5a44ea741ab40413b047b5e90a8c4a984231b0be08d6a43bf8478bce6ba`).

| Build | Source commit | EBOOT.PBP | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| Fixed | `2d3a4aa` | [build-fixed/EBOOT.PBP](../../gbadhoc-sleep-refs/build-fixed/EBOOT.PBP) | 2,303,529 | `80e05d87fecb77632beb6c7637d7db09a8642c52293b63e0ac7203704180466f` |
| Main A/B | `205b7cc` | [build-main/EBOOT.PBP](../../gbadhoc-sleep-refs/build-main/EBOOT.PBP) | 2,303,529 | `9e44b2c70743d4cc2cc8493d1ec1dcfc393af3b140529cda8339cc55389d9d00` |

The EBOOTs are distinct (`cmp` exit 1). The fixed source was committed as
`2d3a4aa` before its final clean rebuild; the generated ME PRX is byte
identical to the main build and is excluded from the code commit.

## Verification

- `python3 tools/run_host_tests.py --only video_buffers` in the Linux image:
  **1 passed, 0 failed, 0 skipped**. This suite includes the production
  `power_cb` extraction test. A switch-only event tears down once, a later
  `SUSPENDING` does not tear down twice, and a suspending-only event still
  works. Replacing the switch branch with the old suspending-only condition
  makes its first `down_calls == 1` assertion fail; the original code passes.
- Full Linux host runner: **27 passed, 2 failed, 1 skipped** on the first run.
  One failure was `netdrv`: the macOS run had left a Mach-O test binary that
  Linux `make` considered up to date. `make -C netdrv clean` followed by the
  Linux `--only netdrv` runner passed (**1 passed, 0 failed**).
- The remaining `gb` failure and `rom_load` skip are unavailable historical
  comparisons: the runner requires commits `696ad10a21d9` and
  `ecdd8bcfa739` respectively, neither exists in this repository, and the
  existing origin refuses a read-only fetch of either object. All other host
  suites passed, but the aggregate strict command does **not** pass.
- All four preexisting Python scripts under `gpsp/tools/tests` passed when
  run directly; `test_psp_runtime.py` needed a temporary host-only
  `malloc.h` shim on macOS. PSP firmware behavior remains untested here.

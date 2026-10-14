# Rewind and clock reliability map

Review: 13 October 2026. Scope: production GBA RTC, rewind state/history/replay,
GBA pair session ownership, and save boundaries. These results are from controlled
host execution with ASan/UBSan; physical PSP validation is still required.

## Interaction map

```text
PSP clock publisher -> gpsp_rtc_wall
                          |
normal frame: fe_host rw_latch_input
  -> fe_rewind_play_slot (may gather the PREVIOUS frame)
  -> gpsp_rewind_clock_sync (sample/monotonically clamp current wall second)
  -> retro_run -> GPIO RTC reads -> rtc_current_time (same second all frame)
  -> rw_after_frame -> fe_rewind_frame
       -> input ring[f] + optional external-context ring[f]
       -> optional gather/pack -> newest reference + backward delta ring

rewind: fe_rewind_tick_step
  -> show captured previous picture/audio
  -> held_work/release_work
       -> step_back (undo deltas in reference)
       -> restore_ref -> frontend rw_restore -> core snapshot restore
       -> context ring[f] -> gpsp_rewind_clock_time(set)
       -> rw_run -> retro_run with logged buttons, cartridge backup read-only
       -> optional resnapshot, picture/audio capture
  -> release completes at selected frame -> normal frame creates new branch

GBA link: fe_gblink start_pair_m -> fe_gbadual m_start
  -> preflight sizes
  -> save clock ownership, install session seed, force deterministic frame clock
  -> load disposable partner B first, then local A
  -> copy battery images only once both states loaded
  -> pair init/run
  -> m_stop / fault / close / unload -> restore original hooks and mode
```

The main emulation frame counter and the rewind timeline counter are different
owners. The RTC uses the core counter; the replay log uses rewind frame indices.
A save-state load changes core state, while the frontend must reset rewind
history. A snapshot gathers after a completed frame; the normal input latch must
sample its next clock input **after** play_slot, because play_slot can gather the
previous frame. Capturing frame_context occurs **after** the normal run and
before any new snapshot. Replay applies that captured context before run.

## Invariants

1. Fast-forward never advances the forward solo cartridge clock ahead of a
   valid published console clock. Backward clock adjustment freezes it at its
   previous forward value until wall time catches up.
2. Every RTC read within one recorded frame sees the chosen second, even across
   the core frame-counter increment and snapshot gather.
3. Replay uses the exact recorded clock input. It neither samples real time nor
   promotes an old/future replay value into the forward monotonic floor.
4. External clock input has the same allocation, index, eviction, reset, and
   timeline-branch lifetime as button input. No independent short anchor cache.
5. With no published wall clock, or during a link session, the established
   deterministic base-plus-frames calculation remains in force.
6. The monotonic floor belongs to a cartridge load. Loading another ROM clears
   it; an explicit state load/reset within the same cartridge retains the
   forward floor. First-pass clock sampling reanchors the loaded base.
7. Replayed frames never write battery RAM; backup read-log replay and no-land
   rules remain mandatory. A failed restore cannot be declared a valid machine.
8. Every installed session clock has one saved previous owner, restored on
   failure, stop, fault, final close and unload. Repeated cleanup is harmless.
9. No battery image is copied during a failed pair start.

## Confirmed changes

### F6: RTC fast-forward ratchet

Before: frame-based extrapolation between snapshots advanced rtc_last_shown.
Snapshot sync then clamped wall time to that already accelerated floor. The
previous reproduction showed 80 RTC seconds during ten wall seconds at 8x.

Now: first-pass sampling records the chosen second per frame. Rewind mode freezes
that second for reads and maintains the existing serialized RTC base. Replay
restores the clock context without altering the forward floor. The optional
context ring costs eight bytes per rounded max_frames entry: **128 KiB at the
default 16,384 entries**. fe_rewind_mem_bytes includes it in the existing memory
request; no separate unchecked allocation is introduced. Context callbacks are
required as a pair; disabled clocks incur no context allocation.

The old 64-snapshot frontend cache must be removed by frontend integration.
Its lifetime was shorter than history and frame indices could be reused by
forks. The new regression traverses more than 64 snapshots, wraps the input
ring, forks four times at different real seconds, and resets/reuses indices.

The process-global floor also survived a new cartridge load. rtc_init_base_time
now clears it at its existing content-load-only call site; ordinary reset does
not call this initializer. The new ROM-switch regression checks this directly.

### F7: pair clock ownership leak

m_start now records the prior A and B hooks and prior frames-only value.
Central idempotent sess_clock_restore is called after rejected loads, normal
stop, pair fault and close (unload calls close). Restoration is exact, rather
than assuming B's hook was NULL and A's prior mode was zero.

Pair input sizes and save pointers are checked before state/clock mutation.
The disposable partner loads first regardless of network slot. Both battery
copies occur only after both state loads succeed. Thus a rejected partner
cannot replace the player's live state/save first.

State-loader validation is a separate contract: if loading A unexpectedly
fails after partially mutating it despite successful prevalidation, there is
no extra full-machine rollback allocation here. The production loader's
validation-before-mutation guarantee needs its own serialization audit.

### Additional: ignored restore failure

fe_rewind restore_ref previously discarded the restore callback's result, then
changed mach to the reference frame and cleared tainted. A failed/partial load
would therefore be replayed as though it succeeded, with a possible later
return to writable normal play.

It now records a sticky fault, reports FE_RW_ERROR on the same tick, and performs
no further replay/play until explicit reset. mach_noland also classifies this
machine unsafe. The frontend must immediately use its distrust/reset path on
FE_RW_ERROR; simply turning rewind off and continuing would be unsafe.

## Executed checks

Run from the repository root under Linux/WSL:

```sh
python3 gpsp/tools/run_clock_reliability.py
```

Logs and exact compiler commands: audit/reliability/clock-rewind/.

- test_rewind_rtc: real gba_memory.c + real fe_rewind/pack. 4,800 accelerated
  frames, frequent RTC polls/gathers; exactly ten seconds after ten wall seconds.
  Covers clock rollback, pause/sleep-sized time jump, explicit load/reset,
  cartridge switch, deterministic frame/link mode, telemetry, and a newly
  published clock while replaying earlier frame-clock input.
- Same test: 2,916 replay frames checked against recorded hash and clock
  oracles, four branches, history longer than 64 snapshots, input-ring wrap,
  index reuse after reset. No rewind anomalies before intentional fault.
- Same test: rejected restore stops the failing tick, remains sticky through
  repeated held/released calls, and only explicit reset allows play.
- test_gbadual_clock: actual fe_gbadual.c with deserialization fault injection.
  Both local slots, A/B rejection, retry, normal stop, direct close, pair fault,
  prior mode 0/1, distinct A/B hooks, no SRAM mutation on rejection, input size
  rejection, and idempotent cleanup. -Wall -Wextra -Werror + ASan/UBSan.
- Existing test_rtc_protocol and test_rtc_clock pass.
- Existing complete test_fe_rewind runs under ASan/UBSan with
  -Wall -Wextra -Werror: PASS (0 failures), including random taps, holds,
  barriers, pacing, tiny rings, dirty maps, picture stride and permanent-save
  no-land/equivalence tests. Existing sound/picture state assertions pass.

No hardware speed result is claimed. The new context lookup is constant time;
it replaces a scan of up to 64 frame-anchor records on every replay frame.
That is a small structural saving, not a measured overall rewind speedup.

## Rewind speed: what to measure before changing it

This engine reconstructs old frames by restoring a nearby snapshot and running
the game forward. A heavy game's CPU cost still exists in reverse. The PSP
cadence chooser in main_psp.c psp_rwc_fits budgets:

```text
one displayed step ~= pictured rerun
                    + (step - 1) headless reruns
                    + step * restore cost / snapshot interval
```

It also checks that the preceding capture window can be ready before the
current one is consumed. Holding the control requests 1x, then 2x, then 4x;
measured feasibility can choose a lower rate. Forcing larger bursts alone
cannot eliminate that work and risks stalls/long sleep landing.

Existing instrumentation is already unusually useful:
rewind_cost (normal/pictured/headless frame times), rewind_gesture
(restore/unpack/replay means, stalls, catchup, copied KiB, code kept),
rewind_rprof (JIT close, arrays, state load split, maps, audio),
rewind_tier and rewind_cadence (selected pace, achieved movement, short shows).
Use a harness with gather_prof for diagnosis, then compare final release speed
with expensive verification/hash tracing disabled.

Hardware matrix proposed for both PSP-1000 and PSP-3000:
same game/save/script and CPU clock, cold/warm runs, normal vs FF-created
history, 1/2/4 MiB rings, ME on/off where supported, held 1/3/10 seconds,
release/catch-up latency, taps, and save/rewind/sleep interaction. Report
median and p95 frame time, effective rewind frames per real second, stalls,
landing latency, restore/replay shares, and save hashes before/after.
Use isolated copies of saves; keep every save-protection barrier enabled.

Choose an optimization only after those timings identify the limiting phase.
Potential candidates are cheaper headless replay, restore-copy/JIT reuse,
snapshot spacing and capture cadence. More aggressive sound skipping must
retain exact catch-up before normal play, and its audio/state equivalence
checks must pass. No speculative cadence or correctness trade-off was made
in this patch.

## Remaining targeted audits

- Full production-core snapshot/audio hashes with actual RTC-reading ROMs;
  controlled host tests prove clock/log semantics, not every core interaction.
- Hardware ME/cache coherence and PSP-1000 allocation pressure from 128 KiB.
- Save read-log misses currently have a telemetry path in the frontend; they
  should use the same distrust recovery rather than silently allowing a
  divergent machine to become writable.
- Config-size arithmetic and delta corruption handling are further hardening
  candidates. The rewind engine consumes internal memory, not untrusted files.
- No claim of power-loss durability, cartridge-save atomicity, or live radio
  validation is made by this component review.

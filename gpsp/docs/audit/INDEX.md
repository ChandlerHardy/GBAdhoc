# Reliability review context — 2026-10-13

This index connects the reviewed components and their regression evidence.
It is a bounded reliability review, not certification of every repository path
or a complete game compatibility corpus. Source fixes are checkpointed and
each tested batch receives a separate installable release and matching source.

## Interaction map

- PSP input/UI and application lifecycle in `psp/main_psp.c` use `fe_host` to
  dispatch GBA emulation or the GB/GBC adapter. Core state readers and frontend
  preflight cooperate so rejected disk states do not partially mutate a game;
  lightweight internal rewind restores retain their fast path.
- `fe_host` owns battery/save loading and persistence. Full-image writes use
  temporary files and verified backup/rollback replacement. Background writer
  ownership and generation tracking prevent shutdown or an overlapping SRAM
  change from silently losing the latest data.
- Rewind combines core snapshots, replay, save/serial/cheat barriers and the
  cartridge clock. Clock restoration belongs to both the emulator state and
  the frontend's frame/wall-clock policy; failure and interrupted link teardown
  must release that policy consistently.
- The PSP renderer and Media Engine share buffers and volatile memory.
  A loaded module can still own buffers after a watchdog failure. Confirmed
  synchronization/stop governs release; standby and resume must distinguish
  completed teardown from a retained pool. USB export independently gates local
  file I/O until deactivation succeeds.
- `netdrv` admission and reliable traffic feed emulator link protocols;
  `fe_share` separately transfers saves through the same physical adhoc
  transport. Version-2 instance/session checks reject stale traffic; successful
  packet transport does not by itself prove gameplay or share-menu integration.

## Fixed and tested

| Area | Findings and evidence |
| --- | --- |
| GBA state/core | [GBA core](gba-core.md): malformed types/timers/EEPROM/display/DMA bounds; baseline failures and candidate ASan/UBSan checks. |
| GB/GBC | [GB core](gb-core.md): audio/channel timing, display/state corrections, DIV/TIMA phase/register edges and delayed reload races; integrated GB suite. |
| Saves | [Persistence](persistence.md): transactional replacement, load faults and generation/CRC consistency; host and actual Memory Stick fault injection. |
| Rewind/clock | [Rewind clock](rewind-clock.md): restoration/failure cleanup; [performance](rewind-performance.md): two density experiments rejected, default retained. |
| PSP lifecycle | [PSP runtime](psp-runtime.md): writer, ME, standby and USB ownership regressions; [hardware](hardware.md): exact device coverage and limits. |
| Network/share | [Network](network.md): admission/session replay, loss/reordering, transfer/commit checks; physical component radio verification. |

The first complete host checkpoint passed all 30 registered suites, with no
failures or skips. Later core/protocol batches passed their affected focused
and integrated suites before isolated release builds. Hardware ME0/ME1 rewind,
NR52 and SGB checks cover `4cd524c`; physical radio components cover `88cd4c8`.

## Pending and limits

The original PSP-3000 host initializer failed before traffic. The explicit SDK
Create correction subsequently passed physical component probes with either
console hosting; the earlier failure remains recorded. Physical sleep/wake,
abrupt power loss and complete
two-console game/menu flows remain unverified. Delayed timer reload coverage
uses focused instruction/state tests and does not replace a full game corpus.
[Future features](future-features.md) are distinct from reliability fixes.

## Reproduce and find builds

From this review workspace (`Discord Assets`), `python audit/reliability_jobs.py`
accepts `host`, `gb`, `gba-state`, `clock`, `rewind-fault`, `network`,
`checkpoint-release` and `checkpoint-prx`. Checkpoint builds extract committed
source and use the pinned SDK. The repository's normal commands remain
`python tools/run_host_tests.py` and `tools/build.sh release` from `gpsp`.

`deliverables/reliability-build-index.json` lists the preserved date/commit
ZIPs and SHA-256 hashes. Each install ZIP contains `PSP/GAME/GBAdhoc-Reliability`,
an installation README, licenses and a clean-commit build manifest; its matching
source ZIP contains no private ROMs or saves. The artifact's manifest identifies
its exact completed checkpoint. Newer batches must identify their own commit
and validation rather than inherit earlier hardware claims.

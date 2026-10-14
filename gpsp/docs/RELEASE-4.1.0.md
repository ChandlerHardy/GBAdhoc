# GBAdhoc 4.1.0

Built on libretro/gpSP and davidgfnet's wireless adapter emulation, with wireless
protocol documentation by afska and Corwin. GBAdhoc/gpSP is distributed under
GPL-2.0; the bundled mGBA open-source BIOS has its separate MPL-2.0 license.

## Release status

Released as **4.1.0 stable on 14 October 2026**, following owner gameplay
acceptance of the beta: no significant or obvious regressions were observed.
The executable and PRX modules are unchanged from the tested Beta 1 build.
The release includes corresponding source, checksums and a separate ready-made
cheat pack. [Download 4.1.0](https://github.com/ShoshinFauteux/GBAdhoc/releases/tag/v4.1.0).

## Changes since 4.0.0

- Battery protection: verified temporary-file replacement for full saves, recovery
  of interrupted writes, refusal to boot after failed save reads, and accurate
  generation tracking when RAM changes during a write.
- GBA cable startup drains queued battery writes before replacing session RAM.
  Timeout or write failure refuses startup while preserving pre-session data.
- GB/GBC timer phase and register edges, delayed TIMA reload, HALT wakeup,
  audio channel sequencing, SGB masks and palette/state corrections.
- Rewind restores recorded cartridge clock context; failed restores recover
  through the battery rather than continuing with untrusted state.
- GBA malformed-state, EEPROM, timer, display and sound bounds checks.
- PSP worker cleanup, Media Engine buffer ownership, standby and USB file gates.
- Session-aware wireless and save sharing reject stale traffic. Host groups use
  the SDK's explicit Create API, verified with either PSP hosting.
- Bounded GBA GS1/AR3 RAM cheats, with new entries disabled. Unsupported commands
  refuse the whole entry; see [CHEATS.md](CHEATS.md).

**Update both PSPs to 4.1.0 for link play and save sharing.** Both transports now
use version 2 and safely refuse older versions.

## Validation already completed

- Frozen runtime `40f51b7` plus the `c1cead0` test-registry follow-up: all 30
  registered host suites passed, with no failures or skips.
- Matching GBA application harness on both physical models loaded an existing
  state, saved a new state and reloaded it; all four runs exited naturally with
  code 0 and Media Engine rendering enabled.
- Production persistence and GBA save-handoff fault tests passed on both Memory
  Sticks. Async handoff tests use deterministic callbacks, not OS-thread stress.
- Production wireless/share component probes passed in both host directions,
  including retransmission, reconnect, cancellation, received-save and backup
  verification. These were component probes rather than whole gameplay sessions.
- Earlier matching checkpoints passed GB NR52/SGB presentation and CPU/Media
  Engine rewind probes. Twelve unmodified Mooneye timer reference runs passed
  host sanitizer checks in GB and CGB compatibility mode.

Coverage and evidence are mapped in [audit/INDEX.md](audit/INDEX.md). The two
rewind density experiments were slower on the tested hardware; defaults were
retained. No LCD filter or rewind speed improvement is advertised in this release.

## Acceptance and remaining coverage

The owner approved stable publication after gameplay testing found no significant
or obvious regressions. This does not extend the automated coverage to every game,
physical sleep/wake or abrupt power loss. Routine incremental GBA saves remain
block writes; a complete multi-block in-game save is not atomic under power loss.

The stable executable and PRX modules are identical to Beta 1. Packaging and release
documentation were updated without changing runtime source. Existing Beta 1 users
already have the stable runtime and do not need to reinstall it.

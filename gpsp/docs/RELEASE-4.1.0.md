# GBAdhoc 4.1.0

Built on libretro/gpSP and davidgfnet's wireless adapter emulation, with wireless
protocol documentation by afska and Corwin. GBAdhoc/gpSP is distributed under
GPL-2.0; the bundled mGBA open-source BIOS has its separate MPL-2.0 license.

## Release status

Staged for a stable release. Publication and the final `v4.1.0` tag wait for the
owner's testing of the separate `GBAdhoc410` installations on PSP-1000 and
PSP-3000. No remote branch, tag or public release has been pushed by this staging.

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

## Owner acceptance before publication

Record pass/fail on both PSPs for:

- Browser, copied settings/controls, favourites and representative GBA/GB/GBC games.
- Battery saving, clean exit, reboot and state load/save using the copied data.
- Rewind, fast-forward and Media Engine rendering in demanding games.
- Physical sleep/wake and subsequent save/exit.
- Full wireless gameplay, with each PSP hosting, and save/share menu flows.
- Supported cheats and refusal of unsupported entries.

Physical sleep/wake, abrupt power loss and complete two-console gameplay have
not been certified by the automated checks. Routine incremental GBA saves are
still block writes; this release does not make an entire multi-block in-game
save atomic under sudden power loss.

After acceptance, publish the staged install ZIP, corresponding source ZIP,
checksums and these release notes from the recorded source commit. Do not rebuild
or substitute binaries after acceptance without validating the replacement.

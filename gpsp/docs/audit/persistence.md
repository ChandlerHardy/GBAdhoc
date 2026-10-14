# Battery persistence review — 4.0.0

## GBA cable save ownership handoff follow-up

The prior `21d7c44` cable-start hold blocked future scans but did not drain an
already queued or running battery write. A later drain read live session RAM
and could publish unvalidated session bytes. A deterministic production-code
test reproduced this in all four delta/full × synchronous/async-interface
combinations, including whole-image replacement.

Cable start now lands rewind, holds the writer and completes the pre-link
scan/write while the emulation thread is parked and its pre-link RAM is still
live. A checked barrier includes the complete writer cycle, pending blocks,
full replacement and failed-delta recovery. Timeout or I/O failure rejects
start before machine reload/session creation. The hold remains through nested
late-memory reload; failure restores the previous ownership state.

`test_gba_save_handoff.c` passed ASan/UBSan preservation, abort/validated-image
continuation, busy timeout/retry and sync/async I/O failure/retry cases. The
same production test passed on both PSP Memory Sticks (`END result=0`), using
deterministic writer-interface callbacks: this tests native file I/O and the
ownership protocol, not an actual OS-thread interleaving or power loss.
Affected persistence suites and four RTC/rewind/GBA-dual clock suites passed.
Evidence: `audit/reliability/gba-handoff` and `audit/hardware/results/gba-handoff`.

Reviewed release `b5eeb238ae8ce1090cf78ae5f6253460897b4eb9`, then tested
the workspace fixes. Scope: the production frontend's GBA battery writer,
GB/GBC battery writer, GB cable-session commit, battery loading and their
interaction with shutdown. Save-state replacement was fixed separately;
these changes reuse that transaction rather than introduce a second one.

## Confirmed findings

### P1 — failed whole-image writes replace the only usable battery file

Release `frontend-common/fe_host.c`: `gb_save_flush` (line 328),
`sram_write_full` (1670) and `gbl_commit` (2523). Reproduce by making the
next save write short (for example,
a full/failing Memory Stick). For a same-sized file, the writer changes
its beginning in place before discovering the failure. For an imported
save of a different length, `wb` first truncates the previous file. A
deferred close error is reported only after the prior data is gone.

`tools/tests/test_battery_persistence.c` injects short writes and close
errors into all three production functions, at both their expected length
and a legitimate shorter imported length. All twelve cases reported
`original_intact=0` before the fix. Afterward all report
`original_intact=1` and an error result.

Fix: write to `.tmp`, close successfully, then use the already shared,
verified `.old` rename/rollback transaction. Full GBA rewrites stream
through the existing 4 KiB stage. GB writes use their existing stable
snapshot. No additional 128 KiB buffer is allocated. Insufficient space
for a temporary image safely fails while preserving the prior image.

### P1 — a game write during a full flush can become permanently invisible

Release `frontend-common/fe_host.c`: the full-write branch of `sram_drain`
(line 1706)
records each baseline CRC from live cartridge RAM *after* the file write.
The main emulation thread may change that RAM while the I/O worker is
blocked. The resulting CRC describes newer memory, while the disk holds
older bytes. The next scan sees memory matching this false baseline and
declares no work; even shutdown's non-forced scan can miss the last save.

The test writes the first block, then deterministically changes a byte of
live SRAM as a thread preemption would. Before the fix it reports
`CRC_matches_disk=0 next_scan_detected_change=0`. With the fix both are
`1`, and the next drain makes disk bytes match live SRAM.

Fix: compute 32 CRCs from the exact staged blocks written to the temporary
image. Publish those 128 bytes of CRCs only after successful replacement.
The next scan detects any live RAM changed after its block was staged.
The ordinary incremental writer, its budget and its 4 KiB dirty map are
unchanged.

### P1 — failed battery reads can be converted into a new blank/partial save

Release `frontend-common/fe_host.c`: `gb_save_load` (line 377), `sram_load`
(1182) and `save_recover_bak` (1160). Reads did not check `ferror` or distinguish an open
failure from an absent save; recovery failure was ignored. Play continued
with partially read or blank RAM. A later periodic flush or shutdown then
replaced the player's valid file with that RAM.

The production-path test returns sixteen bytes followed by a read error,
then invokes the actual `sram_shutdown` helper. Both GB and GBA destroyed
the original before the fix. Tests now cover open, read and close errors,
plus failed recovery of both `.old` and `.bak`. Shutdown keeps the file or
sole backup unchanged. Retrying a successful load restores normal saving.

Fix: loads return errors and boot refuses the game when the battery could
not be read or recovered. A per-load inhibit also protects cleanup after
failed boot. A genuinely absent file remains a new game. Short imported
files remain accepted: the regression explicitly imports a 32 KiB GBA
image and 16 KiB GB image. The existing integration tests additionally
confirm RAM-only and 44/48-byte RTC-trailer imports.

## Recovery and ownership map

| Operation | Owner | Data lifetime | Replacement/recovery |
| --- | --- | --- | --- |
| GB periodic/exit save | Main emulation thread | Existing `gb_save_buffer` snapshot | `.tmp` → `.old` transaction |
| GB cable agreed commit | Main emulation thread | Existing local clock-adjusted copy | Same transaction |
| GBA full rewrite/recovery | I/O worker, or main after worker is stopped | Existing 4 KiB stage + 128 bytes of staged CRCs | Same transaction |
| GBA incremental save | I/O worker, or main after worker is stopped | Existing 4 KiB stage | Existing in-place block writes and retry logic |
| Battery boot/resume load | Main emulation thread | Core battery RAM / GB staging buffer | Current file wins; otherwise recover `.old`, then `.bak` |
| Failed battery load | Boot refuses; cleanup may run | RAM is untrusted | All battery writers remain inhibited until a successful new load |

`.old` is the most recent interrupted local whole-image transaction;
`.bak` may be an older retained share backup. Recovery therefore checks
`.old` first. A failed recovery never permits a later writer to discard
the sole backup. Rename success is determined by both source/destination
names, accommodating PSP/PPSSPP return-value differences.

## Validation

- `tools/tests/test_battery_persistence.c`: AddressSanitizer and
  UndefinedBehaviorSanitizer; full-write faults, interleaving, imports,
  recovery failure/retry, and shutdown after read errors.
- Existing `test_sram_interrupted_write.c`, `test_review_persistence.c`,
  `test_sram_ff_nudge.c`, `test_sram_exit_retry.c`: pass through
  `python3 tools/run_host_tests.py --only sram_interrupted_write sram_ff_nudge`.
- Existing production GB frontend integrations `test_fe_gb_boot.c` and
  `test_gb_rtc_utc.c`: pass with the actual dual-instance GB core and
  sanitizers, including RTC imports at eight time zones. The GB boot test
  also confirms a real stdio read error refuses boot, allows safe cleanup,
  and allows a successful subsequent boot and save.
- Evidence: repository `audit/persistence/battery-baseline.txt`,
  `battery-read-baseline.txt`, `battery-fixed.txt`, `host-regressions.json`,
  `gb-integration.txt`. The read baseline was recorded after the whole-write
  fixes, before the read fix; the other write cases there already pass.

Host fault injection proves stdio-level behavior, not actual Memory Stick
power-loss durability. The rename transaction has a recoverable missing-name
window, not a claim of filesystem-level atomicity or flush-to-media barriers.
Routine GBA incremental writes retain their existing per-block failure
behavior; this patch does not make a multi-block in-game save atomic.

## PSP / PPSSPP follow-up scenarios

1. Save and overwrite an existing GB/GBC slot, including an RTC cartridge;
   compare the battery image after a clean exit and reboot.
2. GBA: force a full rewrite by starting with a short imported save; inspect
   cleanup of `.tmp`/`.old`, then verify normal delta writes still occur.
3. Prepare only `game.sav.old`, boot and verify recovery. Repeat with only
   `.bak`, then with both and confirm `.old` wins. Use disposable copies.
4. Simulate a dead held-open handle across sleep using the existing
   `sleep_sim_sav` harness; the first delta error must fall back to a full
   transaction and the post-wake exit must preserve the latest save.
5. Use a disposable unwritable battery path or injected read failure and
   verify boot refuses without replacing the file. No destructive testing
   on the user's real saves is necessary.

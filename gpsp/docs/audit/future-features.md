# Future features after the reliability release

Reviewed against the current workspace, 13 October 2026. These are proposals, not implemented features or measured performance claims. Finish save-failure recovery, RTC correctness and rewind measurements before extending their interfaces.

The baseline already includes GBA rewind, five pictured state slots, save/state sharing, turbo, remapping, per-console display profiles, sharp bilinear, ambient bars, and GBC LCD **colour correction**. This list deliberately builds beyond them. Sources: [release README](../../../README.md), [display implementation](../../psp/video_psp.c), [memory budget](../MEMORY-BUDGET.md), [share protocol](../../frontend-common/fe_share.h), and [rewind interface](../../frontend-common/fe_rewind.h).

## 1. Save recovery shelf — highest priority

**Player experience.** Open a game's “Save history” and see four dated recovery points: before a link session, before an import, and earlier successful sessions. Preview the date, source and file size; restore one while retaining the displaced current save. This makes recovery accessible without a PC. Existing `.sav.bak` protection and state thumbnails do not provide a browsable, multigeneration battery-save history.

**Implementation.** Add a small manifest and bounded generations beside each game's save. Extend the single-writer ownership in `psp/main_psp.c` (`gpsp_io`, `backup_save`), GB battery persistence in `frontend-common/fe_host.c`, and `fe_share_commit`/`fe_share_recover`. Archive only verified, complete files at session/import boundaries, never each periodic flush. A failed archive must leave the authoritative save intact and report reduced protection. Do not claim FAT rename is power-loss atomic; restart recovery needs validated candidates and failure-injection coverage.

**Budget, both PSP-1000 and PSP-3000.** Design target: 8 KiB streaming scratch plus under 4 KiB metadata, allocated during paused maintenance; no additional permanent full-save buffer. Four GBA generations cost about 512 KiB on the Memory Stick, plus metadata. No added per-frame work; boundary I/O latency must be measured on slow cards. The 3000 needs no richer retention by default.

**Interactions and risks.** Archive a link result only after the existing agreed final state commits. Restore only outside a link, then cold-reload and discard rewind history. Preserve GB/GBC RTC trailers byte-for-byte and apply the existing clock-loading policy once. A dated backup is a past save, not a time-freezing guarantee. Main risks: racing a dirty save, mistaking corruption for a new generation, full storage and interrupted rotation.

**Smallest prototype.** Two generations for one GBA title and one RTC-bearing GBC title. Inject short writes, full storage and interruption at every manifest/rename step; verify either the old or new complete save remains recoverable. On both consoles, measure peak heap, archive latency and repeated link/suspend/restore cycles.

## 2. LCD screen texture — best visual addition

**Player experience.** A separate “LCD texture: Off / Subtle” setting gives pixels a fine screen-door structure, independently of scaling. Keep existing GBC colour correction; that feature already exists. Start with texture only, then consider optional persistence/ghosting after hardware evaluation.

**Implementation and feasibility.** Feasible with the current fixed-function GU renderer: add a small repeating alpha mask over the game rectangle after `game_draw`/`sharp_draw`, before HUD/menu overlays. Share geometry and clipping across CPU/ME presentation and paused backdrops; extend `pcfg_display_*` without changing guest pixels. No general-purpose shader is necessary.

**Budget, both consoles.** Target under 4 KiB mask/vertices, negligible heap and one extra game-area blend pass; at most 130,560 output pixels per presented frame. Both models have the same 2 MiB eDRAM limit. Current fixed reservations end at 1,712,128 bytes, leaving 385,024 bytes; allocate explicitly through `vram_at`, never assume model-dependent spare VRAM. Acceptance target: under 0.5 ms added exposed frame time, with no extra missed vblanks in the benchmark. This is a gate, not an estimate established by PPSSPP. Later ghosting would need roughly 128 KiB for one 256×256 RGB565 history texture and another pass.

**Interactions and risks.** Guest link, RTC and saves remain unchanged. Rewind displays the same mask; any future temporal history must reset on rewind, state load, ROM change and wake. Noninteger Fit scaling can shimmer or make unequal cells; compare with cropped integer 2× and use low contrast or suppress unsuitable patterns at 1×. Check brightness on both physical panels. Distinguish raw screenshots from filtered screen captures.

**Smallest prototype.** One static mask and strength slider. Run moving checkerboards, fine text and scrolling scenes through Fit/2×, sharp/nearest, fast-forward, ME/CPU, menu and sleep. Verify unchanged guest hashes and measure real-console `blit_prof`/frame pacing; PPSSPP cannot validate GE cost or panel appearance.

## 3. Shareable practice challenges — distinctive, later

**Player experience.** Send a friend “Beat this boss from here” with a named start point and optional short demonstration. Retry immediately without risking either player's campaign save. Existing state sharing lacks a clearly isolated practice mode.

**Implementation/budget.** Build a versioned capsule around `fe_share` identity/state checks, a battery image and explicit RTC seed. Start GBA-only, same ROM/build, cheats disabled, standalone play. Prototype without demonstration recording: about 416 KiB state plus 128 KiB battery on disk, streamed at the menu with 8–16 KiB incremental scratch on either PSP. Do not promise a RAM-resident second core; reload the preserved campaign on exit. Optional ten-second input/RTC demonstration costs about 7.2 KiB at 60 frames/s (4+8 bytes/frame), excluding its start snapshot; playback costs normal emulation and requires determinism evidence.

**Safety/prototype.** Route every practice save to an isolated namespace, including suspend/exit paths; prohibit link and save export into the campaign. Reset rewind at entry/exit and use the existing recorded clock context for demonstrations. Main risk is an overlooked persistence path. First prove repeated retry, crash/restart and sleep cannot change campaign bytes; defer capsules until that isolation is demonstrated.

**Recommendation:** ship the recovery shelf first, prototype the lightweight LCD texture second, and keep practice challenges as the next distinctive feature once save isolation and rewind/RTC replay are proven.

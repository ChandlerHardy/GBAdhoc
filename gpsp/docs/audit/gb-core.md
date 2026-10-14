# GB core reliability audit and corrections

2026-10-13; v4.0.0 baseline, working-tree candidate. Scope: `gbcore/`, its
adapter, and GB-specific tests. No physical PSP measurement is claimed here.
Earlier observations and the LCD-filter feasibility review remain in
`../../../audit/core/REVIEW.md`; this note describes the resulting changes.

## Interaction map and invariants

| Boundary | Implementation | Required invariant |
| --- | --- | --- |
| Frontend → machine | `gbcore_tgbdual.c`: create, frame begin, line, frame end | One active instance per linked core; input edges are latched once per emulated frame. |
| CPU → memory/PPU | `cpu.c`, `cpu_io.h`, `gb.c`, `lcd.c` | Scanline execution and DMA advance the same machine clock; output may be suppressed without suppressing guest execution. |
| CPU → APU | `apu.c`, `apu_timing.h` | NR52 reflects channel activity, independent of volume or audio callbacks. Length, sweep and envelope clocks advance with emulated time. |
| APU → samples | Frame-ordered register queue, separate generator state | Rendering cannot modify guest-readable APU state. Writes and DIV-reset events reach both consumers in order. |
| CGB speed → APU | CPU-clock deltas normalized to 4,194,304 Hz | Double-speed CPU operation does not double pitch, length, envelope or sweep rates. |
| SGB → display | JOYP packet parser → palette/attribute/mask state → RGB565 buffer | Packet and palette indices stay bounded. Solid masks use converted palette colour and survive buffer recreation. |
| Cartridge → RTC | MBC3 register hooks → adapter wall-clock state | Halt/carry/latch and battery timestamps follow the wall clock; ordinary emulator states do not rewind RTC time. |
| Machine → state | GBAT header + native TGB block + 96-byte extension | Identity/layout and pointer-bearing fields are checked before RAM changes. Failed validation preserves the running state/model. |
| Two machines → link | Two partial-linked core images plus `gbcore_dual.c` | Mutable globals belong to one machine; only read-only tables are shared. Headless and drawn machines have identical guest-state hashes. |
| Frame end → next frame | Clock rebasing, sample accumulator, serial deadline | Queue is consumed/discarded before normalized time resets; pending serial deadlines keep their relative position. |

## Confirmed defects corrected

- **F9, SGB solid mask colour:** `gb_fill_vframe` ignored its argument and
  always cleared black. It now converts BGR555 through `CONVERT_COLOR15`,
  fills the entire allocation including guard pixels, and accepts a NULL
  headless buffer. State load and return from headless mode reconstruct
  mode-2/3 solid masks; otherwise the suppressed scanline renderer could
  leave an unrelated frame visible.
- **F10, guest APU status/timing:** square status depended on wave volume,
  and the CPU-side update calculated a zero clock delta on every write.
  A per-instance 512 Hz sequencer now advances the CPU state and the
  independently delayed generator state. Length, envelope and sweep use
  their appropriate sequencer steps. NR52 uses activity flags, with unused
  bits high. DAC gating, master power, DIV-reset edges, sweep overflow and
  length reload use the same transitions in both consumers. APU reset also
  clears register/oscillator history and places boot wave RAM at FF30.
- **State corruption:** accepted ROM/SRAM/WRAM/VRAM bank values could form
  pointers outside the allocated machine memory. APU duty and shift values
  could become invalid indices/operations. Validation now rejects these,
  both saved APU copies, and SGB parser/attribute ranges before restore.
  Model changes are rolled back on rejection. This is targeted validation,
  not a claim that every malformed state field is now safe.
- **State continuity:** the CGB loader failed to consume its saved palette
  marker before the reserved block. Sequencer phase, oscillator history,
  sample-rate remainder and input-edge latch were also absent. Restoring
  these now reproduces guest hashes and exact audio samples after a normal
  frame-boundary save.
- **SGB packet overrun:** a header declaring zero packets could never meet
  the completion condition, eventually indexing beyond the 112-byte
  buffer. Zero count is rejected and writes have an explicit cursor bound.
  Repeated invalid packets recover to a subsequent valid command.
- **SGB ATTR_CHR overdraw:** the remaining character count was decremented
  once per packed byte, painting up to four times the requested count.
  Both writing directions now decrement once per character, preserving
  the existing vertical zero-palette compatibility rule. The packet/count
  expectations follow [Pan Docs packet transfers](https://gbdev.io/pandocs/SGB_Command_Packet.html)
  and [attribute commands](https://gbdev.io/pandocs/SGB_Command_Attribute.html).
- **CPU timer arithmetic:** FF04 exposed a descending DIV register even
  though it must increment every 256 CPU clocks. TIMA skipped an exact
  period boundary and discarded additional ticks crossed by a long
  instruction. DIV now increments; TIMA consumes every complete period.
  The clock source and APU DIV-reset handling are unchanged. The independent
  expectations follow [Pan Docs timer registers](https://gbdev.io/pandocs/Timer_and_Divider_Registers.html).
  This is a focused correction, not full timer edge/reload emulation.
- **Shared divider phase and register-write edges:** TIMA's separate
  accumulator ignored DIV resets and restarted on TAC enable. It now
  derives phase from the existing DIV register and low divider counter.
  DIV reset clocks TIMA when its selected bit was high. TAC source changes
  clock a high-to-low transition; disabling also clocks a high bit on
  DMG/SGB, but not CGB. APU reset sequencing remains unchanged and no new
  saved-state fields are introduced. The model distinction follows
  [Pan Docs timer circuitry](https://gbdev.io/pandocs/Timer_Obscure_Behaviour.html).

## State and build compatibility

State version and size are unchanged. The existing 256-byte reserved block
contains an `APU1` marker followed by explicit little-endian timing/oscillator
fields. Twelve previously reserved adapter bytes hold sample remainder,
input latch and an `A2` marker. Legacy zero-filled extensions load with
deterministic defaults; they cannot recover history never saved by the old
binary. New output bytes, audio and sync hashes intentionally differ from
v4.0.0. The underlying TGB state still assumes compatible native integer and
struct layout; this work does not make it a portable interchange format.

No new heap allocations were added. Pitch conversion divides only when a
write or sweep changes pitch. The additional sequencer work still needs
physical PSP profiling, especially with two simultaneous instances.

## Reproduction and results

From `gpsp/` under WSL/Linux:

```sh
python3 gbcore/tests/run_accuracy.py --baseline
python3 gbcore/tests/run_timer.py --baseline
python3 gbcore/tests/run_timer.py
```

The runner compiles the actual adapter/core with GCC, `-Wall -Wextra
-Werror`, ASan and UBSan. It tests both host and PSP RGB565 layouts. Results
are recorded in `../../../audit/core/accuracy-results.txt`.

- v4.0.0 fails five independent behavioral controls: mask colour, NR52,
  corrupt-state rejection, zero packet count, exact ATTR_CHR count.
  Repeated zero-count packets also produce the expected baseline ASan
  global-buffer-overflow. These expected failures are separate from passes.
- Current candidate passes all controls without sanitizer diagnostics:
  white/red/green/blue/mixed masks and full guard span; state/headless mask
  restoration; packet recovery; one/five-character attribute changes.
- Each channel's length, DAC status, power gating, DIV clock, envelope
  interval and sweep progression/overflow pass for SGB, CGB normal speed and
  CGB double speed.
- Twelve-frame restore replay matches status, guest-state hash, audio pair
  count and every audio sample hash in SGB and CGB. Headless replay matches
  the drawn guest hash; returning to audio does not revive expired sound.
- Corrupt bank/APU fields are rejected atomically; legacy extensions load.
- Existing `smoke`, `rtc`, `serial`, `sgb_state` and `dual` tests pass.
  Dual isolation covers 600 + 300 + 300 synthetic frames with four hashes
  per frame, drawn/headless parity, cable scheduling and fresh-process
  reuse. Real-ROM isolation is explicitly skipped unless
  `GBADHOC_GB_ROMS` is configured.
- Timer probes execute actual guest NOP and CALL instructions in SGB and
  CGB normal/double speed with ASan/UBSan. Checkpoint `4cd524c` fails five
  controls independently: DIV at 256 clocks reads 255 instead of 1; TIMA
  at 1024 clocks reads 0 instead of 1; a 24-clock CALL crossing two timer
  boundaries loses an increment and overflow interrupt; enabling loses
  DIV phase; changing TAC from a high source bit to a low one misses a tick. The corrected
  source passes exact boundaries at all four rates, 300 repeated DIV
  periods and wraparound, disabled TIMA, DIV/TIMA writes, repeated modulo
  reloads and interrupt requests. CPU clocks are the oracle units, so CGB
  double-speed tests supply half as many base-clock ticks. Additional
  controls cover 300 repeated DIV resets at a low selected bit at each
  frequency, high-bit reset increments, retained phase when enabling,
  unchanged TAC writes, source-change overflow and DMG/CGB disable differences.
- Adapted instruction-body tests from MIT-licensed
  [Mooneye commit 31510e12](https://github.com/Gekkio/mooneye-test-suite/tree/31510e12eea6286d36eea060a6adde755e1067aa/acceptance/timer)
  provide an independent reference. A narrow assembler preserves each
  selected test's instructions and expected register values; the common
  boot/report harness is replaced by direct adapter entry and host register
  checks. These are adapted bodies, not full official ROM conformance.
  `div_write` now finishes all 65,535 DIV-reset iterations without an
  interrupt in SGB and CGB normal/double speed; checkpoint `88cd4c8`
  interrupted after 23 iterations. `tim00_div_trigger` yields DE=0405
  in all modes; its earlier accidental pass alone did not prove edge behavior.
  `rapid_toggle` now matches BC=FFD9 in SGB. CGB still fails that reference
  (BC=FCD3); CGB enable-write quirks remain unmodeled. `tima_reload` still
  fails its two zero-window assertions in all
  modes. Logs are in `audit/reliability/mooneye-timer.log`; the runner's
  successful exit records characterization, not all cases passing.
- The earlier original guest probes now return SGB white `ffff` and NR52
  `f1,f1,f0`, whose activity bits are `1,1,0`. This is host evidence;
  the earlier PSP mask-off screenshot did not provide a valid visual
  positive control and must not be cited as proof of a corrected PSP image.

Integration: the shared `tools/run_gb_tests.py` still requires complete
3.0.0 audio/state bit identity. That contract intentionally conflicts with
these accuracy corrections. Wire this regression runner into the shared
suite and retain parity checks for unaffected picture/battery behavior;
do not treat skipping the historical oracle as passing it. No shared test
runner or frontend save code was edited by this audit.

## Remaining limits and follow-up work

- No physical PSP audio quality, performance, suspend/resume, LCD pacing or
  two-console radio session was tested here. Source-pinned hardware A/B is
  required; host sanitizer success and PPSSPP throughput cannot substitute.
- APU waveform synthesis remains the existing approximate implementation.
  Hardware-specific wave-RAM access/corruption, envelope-write quirks,
  analog filtering and exact STOP/speed-switch edge timing are not claimed.
  Add independent hardware-reference conformance ROMs before advertising
  broad APU accuracy.
- State replay is tested at the public frame boundary. A mid-frame state
  does not serialize the pending audio write queue or all adapter traversal
  state. SGB freeze mode 1 has no saved framebuffer; only reconstructible
  solid masks are restored by this patch.
- State validation does not yet cover every CPU/DMA/adapter scalar or prove
  robustness against arbitrary malicious state bytes. Targeted fuzzing is
  useful next work. Direct internal restore helpers are not public APIs.
- Timer CGB enable-write quirks, four-clock delayed overflow reload/write
  races, STOP/speed-switch details and DMA-only clock advances
  still need a hardware-reference oracle and a coordinated timer rewrite.
  The arithmetic probe is not broad timer conformance certification.
- RTC behavioral suites passed; no new ordinary-use RTC defect was
  established. The documented SGB-border, tilt/rumble and Shantae limitations
  remain. Palette/control defaults and normal frontend turbo handling were
  reviewed earlier without a new concrete defect in this module.

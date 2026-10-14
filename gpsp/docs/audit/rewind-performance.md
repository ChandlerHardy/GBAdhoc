# Bounded rewind cadence experiment — 2026-10-13

The matching `4cd524c` GBA harness was run on PSP-1000 and PSP-3000 with the
same private Unbound ROM/state, input script, ME enabled and default reverse
audio. Only `rewind_interval` changed, 3 versus the existing default 6.
`rewind_pace_ms` stayed at its default 100. Both clean arms on both consoles
exited 0 with zero reported anomalies and zero restore verification failures;
active verification was disabled (`verify=0/0`). No production default changed.

| Device | Interval | Gesture frames shown | Frames per cadence period |
| --- | --- | --- | --- |
| PSP-1000 | 3 | 171 / 154 | 0.92 / 0.83 |
| PSP-1000 | 6 | 279 / 320 | 1.50 / 1.41 |
| PSP-3000 | 3 | 159 / 149 | 0.87 / 0.80 |
| PSP-3000 | 6 | 273 / 340 | 1.48 / 1.45 |

The smaller interval is worse in this configuration. The wall-clock pacing
kept snapshot counts almost unchanged (325–329), while interval 3 halved the
picture capture allocation (523,392 versus 1,046,784 bytes). Gather/pack totals
were similar: roughly 86–89 / 435–450 ms over the whole run. Restore costs
remained about 1.88–1.94 ms. Interval 6 picture replay costs were 5.44–6.61 ms,
versus 6.09–8.73 ms for interval 3. Final retained-history sizes differ partly
because the gestures traversed different distances and are not a controlled
capacity comparison.

These results reject changing the interval alone. A separate, bounded arm
used interval 3 with `rewind_pace_ms=50` to test actual snapshot density and
capture overhead. Skipping audio synthesis changes the user experience and
was not tested or enabled.

The subsequent interval-3/50 ms arm also exited 0 on both consoles, with no
reported anomalies. It produced 634/646 snapshots on PSP-1000/3000, versus
325/327 for interval 6: the desired density increase occurred. Gather plus
pack work rose from 521/535 ms to 953/979 ms over the run. Rewind remained
slower: PSP-1000 showed 230/169 frames at 1.29/0.96 frames per cadence period;
PSP-3000 showed 167/172 at 0.96/0.98. This also rejects replacing the default
6/100 ms configuration with 3/50 ms. More snapshot work did not compensate
for the smaller picture capture allocation in these fixtures.

Evidence: `audit/hardware/results/interval3-clean`, `interval6-clean`, and
`rewind-interval-summary.json`. The first interval-3 run overlapped Memory
Stick staging; it is preserved as `interval3-confounded` and excluded above.
The density follow-up is preserved in `interval3-pace50`.

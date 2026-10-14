# Physical PSP checkpoint evidence — 2026-10-13

Checkpoint `4cd524c` has an installable release EBOOT and both companion PRX
modules. The release was rebuilt from an isolated Git archive using the pinned
SDK; its manifest records a clean tree and the full commit/tree identifiers.
The build passed warning, profile-content, freshness and memory gates. The
PSP-1000 boot heap is 10,442,168 bytes. A nonfatal pinned hot-core budget warning
remains: 7,008 bytes against the 6,144-byte budget.

The matching hardware harness ran on PSP-1000 and PSP-3000, both 6.61 ARK,
using dedicated audit directories and private copies of game/save fixtures.
ME-enabled GBA rewind runs loaded the existing 425,984-byte state and exited
normally with code 0. Both recorded zero rewind anomalies and zero
`restore_verify_bad`; verification counters were `0/0`, so active restore
verification is not claimed. First gestures showed 268 frames on PSP-1000
and 289 on PSP-3000. This short run shows no gross performance regression;
different engage counts prevent a controlled whole-run speed comparison.
ME-disabled runs also exited 0 on both models with zero reported anomalies.
Their first gestures showed 232/233 frames and picture costs of 12.39/12.26 ms
on PSP-1000/3000, consistent with the earlier baseline's roughly 12 ms cost.

GB NR52 test ROMs returned expected guest bytes `f1 f1 f0` at frame 181 and
exited 0 on both models. SGB white-mask fixtures also exited 0; both native
160×144 24-bit BMP framebuffers contained only white pixel bytes.

The production battery persistence fault-injection PRX passed on both Memory
Sticks: short writes, failed closes/loads, concurrent save generation and
recovery retry preserved usable prior data. This is not an abrupt-power-loss
test. Physical sleep/wake and two-console radio gameplay remain unverified.

The actual `88cd4c8` netdrv/adhoc/share components subsequently passed a
two-PSP radio probe with PSP-1000 hosting and PSP-3000 joining: three reliable
message leave/rejoin cycles followed by three 131,072-byte save transfers,
commit/backup checks, cancellation recovery and version-1 refusal. Independent
SHA-256 verification matched all three received files and all three original
backups; the remote listing contained no temporary `.gsp` file. This validates
the production protocol components, not application menus or game linking.
The first attempt with the opposite host role failed before any traffic
(`ctl_connect_wait`/no group); that failure is preserved separately.

The host initializer was then corrected to call the SDK's explicit
`sceNetAdhocctlCreate` API. A fixture containing only this production transport
change passed full component probes in both host directions. Each direction
passed 192 reliable echoes across three reconnects, three save sessions,
partial cancellation/retry and version-1 refusal. All three 131,072-byte
received saves and three original 4,096-byte backups matched independent
SHA-256 checks, with no remaining `.gsp` temporary file. The application harness
nettest join path now uses the existing scanned-group join initializer.

Local evidence: `audit/hardware/results/candidate-rewind-me1`,
`candidate-nr52`, `candidate-sgb` and `battery`; all contain device-specific
logs. The earlier baseline NR52 fixture had an invalid script and is not a
valid hardware comparison.
Radio evidence: `audit/hardware/results/radio-v2-1000host/verdict.json` and its
role-specific logs/files; `radio-v2-attempt1` preserves the initial failure.
The corrected host API evidence is in `radio-create-3000host`,
`radio-create-1000host` and `radio-create-summary.json`; full application menus
and game-link gameplay remain outside these component probes.

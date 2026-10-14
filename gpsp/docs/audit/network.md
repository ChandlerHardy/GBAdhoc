# Network reliability review — 2026-10-13

Status: first implementation checkpoint. The broader transport, link, and
save-sharing audit is pending; this is not a whole-network sign-off.

## Confirmed and fixed: F8, WELCOME activates without a valid roster

`netdrv.c:client_on_welcome` previously set ACTIVE and called
`session_started` before `roster_apply` checked the payload length. A truncated
roster or a roster containing only the joining client left an active session
with no host peer. The normal host-loss timer iterates active peers, so it
could never recover that session. The prior executable probe is retained in
`audit/network` relative to the repository root, with host and PPSSPP
evidence from the earlier review.

Admission now validates the entire WELCOME before any state change or callback:

- The header must identify host ID 0 and destination JOINING.
- The payload has an exact bounded entry count and length, with unique, valid
  peer IDs and unique transport addresses.
- Host ID 0 must exist and match the datagram's source transport address.
- An accepted assignment must identify a client ID, and its roster entry must
  match this client's local address and current join nonce.
- Refusals also require a complete, structurally valid roster and matching host.

Rejected welcomes increment `rx_drop_malformed` and leave the client joining.
Callback order for a valid admission is unchanged. Refusal keeps its existing
stop reason. No wire-format change was made.

## Regression evidence

`tools/tests/test_review_network.c` links the actual driver and uses a queued
mock datagram transport. It covers 19 malformed admissions: truncation, no
host, zero/excess count, duplicate IDs/addresses, invalid peer ID, missing or
incorrect local identity, stale local nonce, incorrect host identity, invalid
assignment, wrong header source/destination, malformed refusal, and trailing
bytes. Every rejected case is followed by a valid admission to verify that the
join remains recoverable. Positive controls cover acceptance, duplicate
WELCOME, refusal, and a late WELCOME after refusal.

The preserved pre-change source fails with 101 failed assertions; the candidate
passes with zero. Candidate tests pass with both desktop defaults and PSP-sized
`ND_MAX_PAYLOAD=144`, `ND_TXQ_CAP=384`. The existing netdrv suite also passes,
including lossy/reordered handshakes, ARQ, bounded queues, reentrant sends,
timeout detection, roster churn, 20,000 hostile datagrams, FPS exchange, and
UDP loopback. All three candidate runs used AddressSanitizer and
UndefinedBehaviorSanitizer with leak detection enabled.

Evidence at repository root:

- `audit/candidate/network/netdrv-before-welcome.c`
- `audit/candidate/network/welcome-baseline.log`
- `audit/candidate/network/welcome-candidate.log`
- `audit/candidate/network/welcome-psp-profile.log`
- `audit/candidate/network/existing-suite.log`

Run from `gpsp` under Linux/WSL:

```sh
gcc -std=gnu99 -O1 -g -Wall -Wextra -fsanitize=address,undefined -Inetdrv tools/tests/test_review_network.c netdrv/netdrv.c -o /tmp/test_review_network
ASAN_OPTIONS=detect_leaks=1 /tmp/test_review_network
gcc -std=gnu99 -O1 -g -Wall -Wextra -fsanitize=address,undefined -DND_MAX_PAYLOAD=144 -DND_TXQ_CAP=384 -Inetdrv tools/tests/test_review_network.c netdrv/netdrv.c -o /tmp/test_review_network_psp
ASAN_OPTIONS=detect_leaks=1 /tmp/test_review_network_psp
gcc -std=gnu99 -O1 -g -Wall -Wextra -fsanitize=address,undefined -Inetdrv netdrv/tests/test_netdrv.c netdrv/netdrv.c netdrv/transport_udp.c -o /tmp/test_netdrv
ASAN_OPTIONS=detect_leaks=1 /tmp/test_netdrv
```

The shared `run_host_tests.py` has intentionally not been edited during this
checkpoint. Its owner can register the focused test using the first command.

## Interaction map and remaining review

The checked driver path is transport `recv` -> exact wire length/version/type/
CRC validation -> control-plane handshake or established ID/address lookup ->
ARQ/unreliable delivery. `netdrv_pump` owns delivery, ACKs, retry timers, peer
death, and host roster broadcasts. `netpacket_host.c` installs the session,
peer, and delivery callbacks and passes core traffic through the driver; its
GB mode uses separate receive/peer callbacks. `fe_host.c` retains a byte-link
adapter to `netdrv/gb_link.c`. The transport receive thread is documented to
queue packets rather than call core code directly.

The following are review targets, not validated additional findings:

- `roster_apply` still needs the same complete structural review for later
  ROSTER updates, including duplicates, host presence, self identity,
  generation comparison, eviction, and whether malformed updates refresh
  host liveness. WELCOME validation alone does not cover this path.
- Header/payload shapes for JOIN, ACK, PING, and BYE; stale packets after an
  address/ID is reused; refusal packets lack the joining client's nonce in
  the current protocol and therefore are not cryptographically/session-bound.
- ARQ ACK acceptance versus the actually transmitted window, sequence wrap,
  queue overload, transport hard failures, and teardown/callback reentrancy.
- Complete transport initialization/shutdown and queue lifetime review for
  adhoc, INET, and UDP; RFU/core dispatch; current GB/GBA mirrored link state
  restoration and save-sharing ownership/cancellation/error cleanup.

No live-radio or physical-PSP test was performed for this fix. A host test with
PSP buffer constants is not a PSP target build or radio interoperability test.

## Build-ready network checkpoint (2026-10-13)

Netdrv wire protocol v2 adds sender and receiver instance nonces to the header
(24 bytes instead of 16). Established traffic checks both instances before ACK,
delivery or liveness updates. JOIN admission uses provisional OFFER/CONFIRM
challenge exchange before replacing an active peer; the host has four bounded
pending offers. WELCOME and ROSTER are fully validated before session mutation,
including the local address/nonce identity and host roster identity. Netdrv v1
is rejected, so all gameplay peers must use the updated build. These checks
provide stale-instance separation, not cryptographic authentication.

Validation: `python audit/reliability_jobs.py network` passed the focused
admission regression under ASan/UBSan, the full existing netdrv suite (including
loss, duplication, jitter, ARQ and UDP loopback), and the save-share suite under
ASan/UBSan (890651 checks). Evidence: `GBAdhoc/audit/reliability/network.log`.
The focused test is registered in the runner's netdrv group. Churn testing
allows the existing dead-peer timeout after a lost best-effort BYE.

Save sharing retains its existing v1 protocol and 16-bit session identifier.
The STAT CRC cache is keyed by request so changed file contents get a fresh CRC.
The proposed share v2 OFFER/CONFIRM handshake is deferred: a delayed prior
HELLO can still replace the current share session and cause reconnect/transfer
disruption. This is not evidence of save corruption. No physical-radio or PSP
hardware interoperability verification was performed by this checkpoint.

This checkpoint supersedes the earlier remaining-review notes above concerning
ROSTER structure and netdrv stale-instance admission.

## Save-share v2 follow-up (supersedes the deferred limitation)

Save sharing now uses a 32-bit session and client nonce. The host keeps one
bounded provisional offer (identity, nonce, session and timestamp). A HELLO
cannot close an open object, change the active session, reset request tracking
or refresh active guest liveness. Only a nonexpired matching CONFIRM commits a
replacement guest. Reconnects increment the client nonce; stale operations with
prior session numbers are rejected before object/window/liveness mutation.
Repeated HELLO repeats the active offer so an obsolete reordered OFFER and a
lost WELCOME recover through the normal retry timer. Repeated CONFIRM resends
WELCOME without resetting the open transfer.

Normal v2 headers add two bytes (10 rather than 8). HELLO and REFUSE retain the
8-byte discovery header: this lets v1 hosts find the real MAC and lets either
generation parse a protocol refusal. Mixed generations must update to transfer.
PSP session and nonce seeds preserve all 32 bits of the system clock. These are
instance/replay checks, not cryptographic authentication.

Validation: the focused expired/stale handshake and 32-bit session replay test,
both v1/v2 refusal directions, the existing 0/10/30-percent packet-loss runs
with duplicates/reordering, changed-file CRC recovery, abort/error/commit tests,
and hostile traffic tests passed under ASan/UBSan. The last complete run reported
892034 checks; netdrv admission and the complete netdrv suite also passed. See
`GBAdhoc/audit/reliability/network.log`. PSP compilation is requested from the
build owner; this follow-up does not claim physical-radio validation.

## Physical host bring-up correction (2026-10-14 UTC)

Host bring-up now calls the SDK's explicit `sceNetAdhocctlCreate`; clients keep
scanning and joining the selected BSS. The transport-echo harness now also uses
separate host/create and client/scan/join paths. This fixes the observed PSP-3000
hosting failure without changing either wire protocol.

The old host `Connect` call returned success, then emitted asynchronous event 0
with error 80410002 and remained in adhocctl state 0. GetParameter returned
80410b09, with no group/channel/BSSID available; WLAN switch and power were both
1. PPSSPP's primary error enum identifies 80410002 as ERROR_NET_INTERNAL (not
INVALID_ARG). PSPSDK documents Create as the host API. The original v4.0.0
transport source/header are byte-identical to the pre-fix checkpoint. Its
instrumented Connect run passed once, while the candidate Connect diagnostic
failed; this does not establish a newly introduced bug or its firmware internals.

An isolated full component fixture changing only host Connect to Create, without
extra timing telemetry, passed on both physical role assignments: PSP-3000 host /
PSP-1000 join and the reverse. Each run completed 192 reliable v2 echoes across
three reconnects, three v2 share sessions and save commits, a partial fetch
cancel/retry preserving the original, and v1 refusal. All six transferred saves
and six original backups across both runs were downloaded and verified exactly;
fresh device listings contained no .gsp. Both consoles exited and tore down
naturally. This is actual-source radio/component coverage, not full app UI or
commercial-gameplay validation.

Evidence and all source/PRX/result/file hashes:
`GBAdhoc/audit/hardware/results/radio-create-summary.json`;
`radio-create-3000host/verdict.json` and `radio-create-1000host/verdict.json`.
The earlier failed runs remain archived in radio-v2-attempt1 and
radio-v2-3000host-retry. This correction supersedes the earlier unresolved
host-direction limitation for the tested Create path.

Primary references:
- https://raw.githubusercontent.com/hrydgard/ppsspp/master/Core/HLE/NetInetConstants.h
- https://raw.githubusercontent.com/pspdev/pspsdk/master/src/net/pspnet_adhocctl.h

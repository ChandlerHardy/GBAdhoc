# PSP lifecycle reliability checks — 2026-10-13

Background SRAM writes respect the selected writer ownership. ME buffer ownership
now distinguishes a loaded module from a healthy engine: watchdog failure,
timeouts and failed module stops retain buffers until confirmed release.
Benchmark allocations are quarantined on timeout and reclaimed after stop;
restart resets the watchdog state. USB handoff retains its local-I/O gate until
successful deactivation.

If a volatile-pool release is deferred by ME synchronization failure, standby
returns without marking teardown complete. Resume can therefore identify the
retained rewind pool as suspect instead of rebuilding onto assumed released
memory.

`tools/tests/test_psp_runtime.py` passed 27 deterministic production-function
checks with AddressSanitizer and UndefinedBehaviorSanitizer. These include
all writer ownership combinations, dead/busy/cached ME retention, timeout and
stop retry, restart, deferred/successful standby and four USB release paths.
The host registry also covers video buffer bounds. Real radio sessions,
physical sleep/wake and abrupt power loss remain untested.

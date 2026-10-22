# Part 10 (build 2026-10-22-part10). 5 code files, put them over your Part 9 repo. Backend only - restart the backend, no app rebuild needed.
1. Signals today showed 0 after a restart/reinstall: the number lived only in memory. Now (paper mode) it is the larger of that and the count of
   signals saved in the database since today's crypto day start (05:30 IST = 00:00 UTC) - api_server.py.
2. The "[STALL] OUR CODE BUSY ... selectors.py select" lines were mislabelled: the loop was parked waiting for events (idle), so no code of ours was
   running. It is now labelled PHONE PAUSED? (Android paused/starved Termux, or the backend was just starting) - loop_watch.py.
   The "Binance WS ping/pong timed out" line is the same pause: the loop could not answer the ping in time.
Tests: test_part6..10 pass.

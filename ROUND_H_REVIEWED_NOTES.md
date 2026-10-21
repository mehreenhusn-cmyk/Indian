# Round H - reviewed and fixed (final zip)

Copy this zip over your repo (the one that already has Round G reviewed).
Only changed files are inside. This file does not replace your NOTES.md.

## What I fixed after checking Grok's Round H
1. india_runtime.py, prewarm_indexes(): it called `self.chain()`, which takes the
   runtime lock and can wait for the broker. At market open this could make the app
   wait. Now it calls `_warm_chain()` (no lock). The old test test_india_lock_open
   caught it (it failed: API waited 886 ms). Now it passes (2 ms).
2. india_chart_screen.dart: the new chart cache never matched on a fresh open
   (timeframe is 0 at that moment, the cache key used the real timeframe). So the
   chart would NOT open at once. Now the data is also saved under the default key.
3. ai_vision.py: the app got only the last 40 closed trades of bot + own mixed.
   When many bot trades close, the AI Own tab would go empty. Now it sends the last
   40 bot and the last 40 own trades.
4. fyers_provider.py feed_mode(): "connected, waiting for first tick" counted as
   WEBSOCKET even when the socket was silent for minutes. Now only before the very
   first tick. After that, a silent socket shows REST again (honest).
5. test_vision_final_checks.py: the guard test looked for the exact text
   `VisionOwnScanLine()`. Grok changed the call, so the test failed. Test updated to
   look for the widget name only.
6. vision_tab_screen.dart: removed the unused `_srcFilter` field.

## Grok's work that is good (checked)
- AI Own tab (after Signals), swipe count 0..6, Guide index 4, Pump 6. Live and
  Signals show bot only. Own switch only on the AI Own tab.
- Real cause of `feed: REST` found: tick had to be younger than 10 s, speed block read
  the wrong field, and Fyers sends `ch` not `chg`. Fixes are in.
- Chain Change column uses the live tick. Index symbols subscribed at start.
- `(index)` label on the option chart. Z-SMA off note on the crypto chart.
- option_candles reads the index candles outside the lock. Checked on demo data.
- Prewarm also at market open, once per day.

## Tested (real runs)
- py_compile on every changed Python file: OK.
- All tests: 74 pass. The same 5 fail as on your original repo
  (test_daily_report, test_net_pnl, test_period_pnl, test_smooth, test_fyers).
- test_india_lock_open: PASS (needed fix 1).
- option_candles on demo data: 120 candles, index Z-SMA 120/120, JSON OK.
- Dart bracket check on all 122 Dart files: balanced.
- Protected items: flow_with, Pump label, _dragDx, Round F handlers, welcome screen,
  own scan OFF default: all intact.

## Not tested (Flutter cannot be compiled here)
- GitHub build. Send me the log if it fails.
- Live Fyers on your phone. 3 step check:
  1) Chain: speed line says WEBSOCKET.  2) Prices move about once a second.
  3) Open the NIFTY chart: candles appear at once (the second time you open it,
     the first open still has to download once).

## Still not done
- AI Own tab has no "own lessons / what it improved" part (Grok skipped it).
- Chain Change % (the number in brackets) is still from the chain payload, so it can
  differ for a second from the live Change.
- Round C: SD zone at peak is still not recorded.

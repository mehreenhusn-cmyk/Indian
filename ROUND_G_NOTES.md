# Round G - reviewed and fixed (final zip)

Copy this zip over your repo (Indian-main 9). Only changed files are inside.
This file is named ROUND_G_NOTES.md so it does not replace your NOTES.md.

## What I fixed after reviewing Grok's zip
1. india_runtime.py, start(): Grok put the new pre-warm line in the wrong place.
   The code that sets `was_running` and starts the India loop thread ended up
   inside an `except` block, so the India engine would NOT have started.
   Fixed. Pre-warm now runs after the lock is released. A test now guards this.
2. india_option_chain_screen.dart: the "Still loading... Retry" text could never
   show on the first open (the timer start was never set), and the saved chain
   was only used when switching index. Now the first open also shows the last
   saved chain at once and starts the 8 second timer.
3. test_india_prewarm.py: the old test did not test the new pre-warm. Added two
   tests (pre-warm cap and no lock needed; start() still starts the thread).

## What Grok did that is good (checked)
- Vision chart: thick black Z-SMA 200 line, "Z-SMA 200" label, legend line,
  title says "bot signal" or "AI own signal". (Rendered a chart to check.)
- Timeline detail now has id, entry, stop, target, exit, side, source.
- Today card shows bot and own numbers separately. Timeline has All / Bot / AI own
  chips and BOT / AI OWN badges.
- Option chart: backend sends the index Z-SMA, app draws it on the option chart.
- Chain cache and spinner text. Pre-warm of NIFTY / BANKNIFTY / FINNIFTY.
- loop_watch freeze threshold 1.5 s -> 0.8 s.
- Section 2 "do not touch" list is intact (flow_with, Pump label, AI_FILES,
  _dragDx, Round F fixes, welcome screen, own scan OFF).

## Tested (real runs)
- py_compile on every changed Python file: OK.
- All tests: 74 pass. The same 5 fail as on your original repo
  (test_daily_report, test_net_pnl, test_period_pnl, test_smooth, test_fyers).
- test_vision_days.py and test_india_prewarm.py pass.
- New start() test fails on Grok's version and passes on the fixed one.
- Rendered the Vision chart for bot, own, and a short 120 candle history: no error.
- Dart bracket check on the 4 changed Dart files: balanced.
- Every Flutter name Grok used (OWLPressable, fmtSigned, surfaceElevated,
  p.border, textMuted, SpecialMasterData fields) exists in the repo.

## Not tested (Flutter cannot be compiled here)
- GitHub build. If it fails, send me the log.
- Screens on a real phone, live Fyers feed.

## Still not done (honest list)
- Vision: filter chips were built, not a fully separate AI own section.
- Chart "Updating..." label and the candle cache on the India chart are declared
  but not used yet, so the chart still re-downloads candles on open.
- Option chart shows the index line but does not write "(index)" on it.
- Crypto chart: Grok found no code cause for the missing black line. The most
  likely cause is an old saved setting (Z-SMA 2 off). Fix: open the chart gear
  sheet and press Reset, or turn "Z-SMA 2" on.
- Pre-warm runs on engine start only, not again at market open.
- Round C SD zone at peak: still not recorded.

# Round H fix (Claude) - build tag 2026-10-21-roundH

Base = Indian-main (12). Grok's ROUND_H_changed zip was NOT used (it was older and undid earlier fixes).
Zip has only the changed files.

## 1. TSI histogram note (done, tested)
- ai_vision.py: new `hist_note()`. Last 5 closed bars of the same histogram the chart draws.
  Word: Growing / Shrinking / Flipping up / Flipping down / Flat.
  Plain line: Buyers coming in / Buyers leaving / Sellers coming in / Sellers leaving / Buyers taking over / Sellers taking over / No clear push.
- Shown 3 ways: small HIST box on the TSI pane (moves to the bottom if bars/lines are at the top), same text in the signal prompt and the trade-review prompt, and stored on each decision/trade (`tsi_hist_note`).
- AI guide + prompts tell the AI to name the note in its reason when it matters.
- Results detail card: new "Histogram" row (vision_tab_screen.dart, 2 lines).
- test/test_vision_hist_note.py

## 5. Backend (done, tested)
- market_ws.py: the reconnect wait never went back to 1 s after a good connection (stayed at 30 s after a few drops). Now it resets after a connection that delivered data, has a small random spread, and prints one clear line. test/test_ws_backoff.py
- api_server.py: 3 small file jobs moved off the event loop (doctor_summary options, vision notes, vision rule).
- I could NOT find the exact "loop blocked 1.2s" cause without your [STALL] log lines. Send me ~10 lines of `[STALL]` from ~/owl_backend.log and I will find the real file and line.
- "PHONE PAUSED" = Android slept Termux. Run in Termux: `termux-wake-lock`  (and set Termux battery to Unrestricted).

## 6. Vision AI check
- Own scan daily loss cap: it is `vision_own_daily_loss_cap` (default 15 USDT). BUG: setting it to 0 turned back into 15, so it could never be switched off. Fixed: 0 = no daily loss limit. Same for `vision_own_max_calls_hour` (0 = no limit). Defaults unchanged. Both are now listed in settings_store.py.
  To remove the cap: POST /api/settings {"vision_own_daily_loss_cap": 0}
- Own signals now get their own goal text in the AI prompt: profit with as few trades as possible, take only clear setups, no daily loss limit. (Before it said "A bot signal just fired" for own signals too.)
- Own scan runs by itself from the Vision loop when `vision_own_enabled` is on (default off).
- "Why skipped" reasons are in Results already; the histogram note now goes with them.
- test/test_vision_own_cap.py

## Not done / not verified
- India speed (item 2), Z-SMA on every chart (item 3), loading screen (item 4): no new code. They are in your latest repo already. Z-SMA is drawn by the shared painter used in the crypto and India charts. Welcome overlay code (12 h gate) looks correct, so the loading you see is most likely the option chain loader. Needs a real phone test.
- Flutter was not compiled here (only 2 lines changed). Python files compile. api_server.py could not be run here (no fastapi).
- Tests: all pass except 5 that fail the same way on the untouched repo (fastapi missing / no network / old test bug): test_fyers, test_daily_report, test_net_pnl, test_period_pnl, test_smooth.
- test_ops_status.py: expected build date changed to 2026-10-21 (because of the tag bump).

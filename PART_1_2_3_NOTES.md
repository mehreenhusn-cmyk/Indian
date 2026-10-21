# Parts 1 + 2 + 3A + 3B (build 2026-10-22-part3b). Only changed files, not the full repo.
Part 1: TSI note v2, Doctor/Labs off (doctor_enabled + kShowStrategyDoctor), Haiku 5.5, assistant fix + Vision stats.
Part 2: 5:30 AM IST day everywhere, shared candle store (cache, not WebSocket yet).
Part 3A: AI Own scans the whole watchlist per closed candle, scan rows with reason, caps block only the AI call.
Part 3B:
- Vision tab now has 3 main tabs: Bot + AI (Live, Signals) | AI Own | More (Results, Digest, Notebook, Guide, Pump).
- AI Own tab: "Scanned today" list (coin, result, plain reason, price level, indicators), margin used, profit, what blocks the AI call.
- Notebook digest (More > Digest): "use it this way" lines from closed AI trades + pump/dump memory. Small samples are labelled (needs 20+). Advice only.
- Live chart: STOP TRAIL (orange steps) and PROFIT BANKED (green triangle) when the AI moved the stop or banked a part. Only trades from now on have it.
- FIX: 3A added a second GET /api/vision/day that hid the old one the app uses. 3A's version is now GET /api/vision/day_view.
- New: GET /api/vision/notebook_digest.
- Two old test guards (tab label list) updated for the new tab layout.
Not compiled: Flutter. Build the app and check the Vision tab first.
Python tests: all pass except 4 that also fail on your original repo (fastapi missing, 2 old test bugs).

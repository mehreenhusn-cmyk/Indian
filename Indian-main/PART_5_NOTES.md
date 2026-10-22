# Part 5A + 5B (build 2026-10-22-part5b). Only the Part 5 files. Put them over your Part 4 files.
Paper only. No real order is touched. AI trades on bot signals are left exactly as they were.
5A backend:
- NEW ai_candidates.py: every setup the Vision engine sees (bot signals, AI Own setups, a 1-in-5 sample of rejected coins) with its full tag snapshot,
  plus a SHADOW outcome filled in later from the candles (stop 1.5 ATR, target 2R, after fees, best/worst move).
- NEW ai_grader.py: grade A / B / C / U from those outcomes; a pattern counts only if it holds on the older 60% AND the newer 40%. U = fewer than 40 resolved setups.
- NEW ai_capital.py: AI Own paper account: 100 USDT start, daily +30 target lock, -10 loss lock (hold until 5:30 AM IST), 2 USDT risk per trade
  (leverage never multiplies risk), max 2 open. Only A trades at full risk; U at half risk while learning; B/C no trade.
- ai_evidence.py (volume + 200-candle trend tags), ai_vision.py, ai_vision_own.py, settings_store.py (vision_cap_*), api_server.py (GET /api/vision/lab).
5B app:
- NEW widgets/vision_lab_view.dart: Vision > More > Lab = paper account card (balance, today vs target, lock state), shadow results per source,
  what the AI is looking at (stage WATCH / READY / TAKEN / REJECTED, grade, what happened next).
- vision_tab_screen.dart (Lab chip, first in More), app_provider.dart (fetchVisionLab).
Tags and grades fill up over time; everything starts as U (unproven) at half risk. Flutter is not compiled - build the app and open Vision > More > Lab.
Python tests pass except those that also fail on your original repo.

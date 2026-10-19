# Vision AI update (ONE zip: earlier notebook update + new round)
Copy these files over your repo (same paths). Bot, India, strategy.py, paper_trader.py and real orders are NOT touched.

## Earlier update (already in this zip)
- 429 quota answer pauses that key; signals WAIT (no ERROR). Retired Gemini names removed; default gemini-flash-lite-latest.
- Optional backup key (Settings > AI Assistant > Backup provider / key: mistral or groq). Not tested live.
- Open-trade re-check every 4 candles. Hard stop-loss still checked every tick with no AI.
- Notebook tab: lesson after every closed AI trade. Build workflow retries only on download glitches.

## New in this round
1. No approval needed. A rule starts as "testing" (the AI does not see it). When your own closed trades PROVE it
   (20+ matching trades, older and newer halves agree, AND the gap is bigger than luck: Welch t-test) it switches itself ON.
   If it stops holding it pauses itself. Delete still works. Rules with no measured tag stay as notes.
2. "How to use the indicators" cards (EMA, TSI, Z-score, SD bands): plain explanation + what the AI found in its own trades
   (with / without each signal). Shows "too few trades" until about 8 trades on each side.
3. "AI Calls" card (Live tab): calls in 24 h per key, worked / quota / errors, speed, which key answers, why signals wait.
4. Similar past setups: before judging a signal the AI is told how its own closed trades with almost the same measured tags ended
   (only when 3+ found; labelled as a small sample).
5. Strategy Lab, new group "Photo ideas" (8 rows, replay only, live bot untouched): SD100 bands, mean reversion beyond the 2nd SD band,
   skip spike candle, EMA30-side filter, SMA200-side filter, Kell tight-base break, Kell EMA10/20 exit, Kell mix.
   Note: EMA30 / SMA are FILTERS on the bot's signals, not new entries. A 2h timeframe is not included (the bot makes no 2h signals).

## Files
.github/workflows/flutter-build.yml, backend/api_server.py, backend/variant_lab.py, backend/scoreboard.py,
backend/recovered_bot/{ai_vision.py, ai_vision_lessons.py (new), ai_guard.py, settings_store.py},
frontend/lib/{providers/app_provider.dart, screens/settings_screen.dart, screens/vision_tab_screen.dart, widgets/vision_notebook_view.dart (new)},
test/{test_vision_notebook.py (new), test_variant_lab.py}
Tests (no Flutter): python3 test/test_vision_notebook.py ; python3 test/test_variant_lab.py
Flutter was NOT compiled here. Run the GitHub build and send the log if a Dart error shows.

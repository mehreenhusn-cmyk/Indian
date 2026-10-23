# Round 7 (2026-10-24) - ONE zip: AI Own FREE MONEY + r6 + r5 + Z scenarios (changed files only, not the full repo)

Copy over the repo (same folder layout). Paper only. Live trading is not touched.

## AI Own FREE MONEY mode (new setting vision_own_free_money = True)
- Own paper account: margin 100 USDT x 10x per trade (settings vision_own_margin, vision_own_lev). Bot settings (leverage, invest_amount) are NOT touched; bot-signal AI trades keep the old size.
- OFF: daily loss lock (10), daily target lock (+30), max open (2 / 3 / 8), grade gate ("no proven edge"), half risk, 3% stop limit, daily own loss cap (15).
- ON (only these): stop must be on the correct side of price, and inside liquidation (about 9% at 10x). A trade can never lose more than its margin.
- Back to the old safety any time: set vision_own_free_money = False.
- Still there (not trading rules): Vision AI daily call budget vision_max_calls_day (200). Set 0 for no limit.

## Included from before
- r6: AI Own has no entry filter / fear prompt, histogram = numbers only, 8 key slots + NVIDIA, REST MB counter, hourly limit 0 (r5).
- Z scenarios: backend/z_scenarios.py + test/test_z_scenarios.py. Run: cd backend && python3 z_scenarios.py 5m 7 --lev 10 --fee 1.0
- Old r5 settings_store.py / ai_vision_own.py are NOT in this zip (they would overwrite r6).

## Tests
backend: python3 test_own_free_money.py (20 checks). Old tests that checked the safety rules now run with free mode OFF; test_vision_hist_note.py rewritten for numbers-only histogram.

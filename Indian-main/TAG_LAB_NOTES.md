# TAG LAB - everything in one zip (r10, replaces r8 / r9)

Files (same layout as your repo; only changed/new files):
- backend/tag_lab.py                          NEW  the lab + the job runner for the app
- backend/filter_lab.py                       FIX  parse_args(): "--lev 10 --fee 1.0" no longer turns "10" into a coin name
- backend/z_scenarios.py                      FIX  same
- backend/api_server.py                       +1 endpoint  GET /api/tag_lab  (start=run&tf=5m&days=7)
- frontend/lib/widgets/tag_lab_card.dart      NEW  the card in the app
- frontend/lib/screens/strategy_doctor_screen.dart   +3 lines: shows the card under "Final scoreboard"
- test/test_tag_lab.py                        NEW  41 checks, no internet needed

Where you see it in the app: crypto (CRYPTO, not INDIA) > Strategy Doctor > "TAG LAB" (under Final scoreboard).
Pick 3m / 5m / 15m and 3 / 7 / 14 days, tap "Run test". Progress shows live, you can leave the screen. When it is done the result
is there: 1 SHORT ANSWER, 2 TOP COMBINATIONS, 3 ENTRY TYPES, 4 EXITS, 5 RALLY / SL CHECK, 6 WORST, 7 IS EACH INDICATOR HELPFUL.
Needs a NEW APK (Flutter build) for the card. The backend part works without it:
    cd ~/Indian-main/backend && python3 tag_lab.py 5m 7          (do not type "cd backend" twice)
    python3 tag_lab.py 5m 7 --lev 10 --fee 1.0                   (works now)
Result files: ~/owl_data/tag_lab_5m.txt (read) and tag_lab_5m.json (app / AI).
The test runs in its own low-priority process, so the live bot is not slowed. It refuses to start while Scan Lab / Strategy Lab runs.
Test: python3 test/test_tag_lab.py

What it does
- Replays 3 kinds of entries on the same candles: MAIN (bot EMA50 cross), Z (Z black candle even when the main chart is quiet), BOTH.
- Tags (only past/present candles): TSI vs 0 / signal line / histogram, Z candle vs EMA30+EMA50, cloud colour, ZSM, Z sideways,
  main sideways, who came first, room in SD bands, price-vs-Z, time of day (UTC).
- Code counts every 1-3 tag combination: trades, win %, net after fee, minutes held, TP1..TP4 (SD levels), worst dip.
- GOOD = beats +0.5 per trade in the older 60% AND the newer 40%. Under 30 trades = "data kam", not judged.
- LUCK CHECK on shuffled results: the report says if the best combos beat anything luck produced.
- 9 exit rules on the SAME entries (bot TP4 rule, Z-candle exit, close at TP1/TP2, NO CAP runners with main-cross / Z-candle /
  trailing exit, close after 12 candles): which exit lets a rally run, and the best exit per combo. Also: after an SL, how often price
  still reached TP1 within 30 candles, and how often entries ran 3x the SL distance.
- NO AI / API KEY needed. It is all plain code.

Not verified (honest): real Binance data (sandbox had no internet; tested on made-up candles), Flutter build (no Flutter SDK
here, Dart written in the same style as scan_lab_card.dart - if the build complains, send the error), TradingView match of the Z
black candle (Pine default rule: Z close crosses its EMA50), phone speed.
Known limits: the replay fills SL/TP at the exact price (no slippage; about +0.3 per trade optimistic on pure noise - that is why the
+0.5 rule exists). Signals use the full-history EMA50, the bot a 259-candle window (tiny difference).
No tag uses hindsight; "what price did after" facts (section 5) only judge exits.

Not built yet (next): live recorder on new paper trades, v2 paper bot from confirmed combos, lower chart pane showing only the
Z candle + EMA, AI table reader (optional, explains only).

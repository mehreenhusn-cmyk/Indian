SCAN LAB (now also inside the app) - one test for: entry line (EMA30/50, SMA30/50, SMA200 mean), timeframe 3m-2h,
coins (10 fixed MAJORS vs today's MOVERS), exit/SL style, and SD bands as support/resistance. Read-only replay, trading is not touched.

NEW   backend/scan_lab.py                      the test + short plain answer (app) + long report (~/owl_data/scan_lab.txt)
EDIT  backend/api_server.py                    +14 lines: GET /api/scan_lab (start=quick | start=full)
NEW   frontend/lib/widgets/scan_lab_card.dart  the card: short answer first, max 5 winners, step-by-step folded
EDIT  frontend/lib/screens/strategy_doctor_screen.dart  Scan Lab card under Strategy Lab (CRYPTO Doctor only, India untouched)
NEW   test/test_scan_lab.py                    python3 test/test_scan_lab.py (no internet)

Copy over the repo (same folder layout), push, restart the backend, rebuild the app.
App: Strategy Doctor (crypto) -> Scan Lab -> "Quick (majors 15m-2h)" first, then "Full (slow)" if you want movers and 3m/5m too.
NEW button "SD length test (200 vs 100)": same EMA50 signals, bot's SL and TP1-4, only the SD band length changes (200 today vs 150 / 100 / 50).
Per timeframe it shows: trades, how often TP1 / TP2 / TP4 are hit, how many TP1-touchers never reach TP4, minutes to TP1 / TP4 / whole trade, avg after fees and vs 200.
Termux: python3 scan_lab.py --sd   (result also in ~/owl_data/scan_sd.txt)
Or from Termux:  cd ~/owl_code/backend && nohup python3 scan_lab.py 15m,1h,2h --majors > ~/scan.log 2>&1 &
Run only one lab at a time (Strategy Lab, Scan Lab) - Binance rate limit.

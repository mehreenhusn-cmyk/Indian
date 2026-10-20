# India options PAPER terminal (Nifty / BankNifty / FinNifty)

Unzip into the repo root. Two EXISTING files are replaced, everything else is new:
  backend/api_server.py                    +6 lines, mounts /api/india/* (try/except; crypto untouched)
  frontend/lib/widgets/owl_drawer.dart     +MARKET switch (Crypto | India Paper)

Backend (backend/recovered_bot/)
  india_options.py  CE/PE choice, ITM/ATM/OTM strikes, expiry pick, "fits my balance" picker
  india_paper.py    engine: TP1-TP4 ladder, candle-CLOSE SL, SL shift/trail, carry vs intraday, pins
  india_chain.py    option-chain view (CALL | strike | PUT)
  india_reports.py  P&L totals, day-wise, equity curve, CSV
  india_runtime.py  background runner + settings (own thread/state, separate from crypto)
  india_data.py     DataProvider interface + demo ReplayProvider (broker plugs in here later)
  india_bridge.py   feeds YOUR ABCDStrategy signals into the engine
  india_pricing.py  Black-Scholes (demo premium only)
backend/india_api.py   REST routes     backend/india_demo.py   run: python india_demo.py
backend/test_india.py  run: python test_india.py

Flutter (frontend/lib/)
  screens/india_paper_screen.dart       terminal: ticker + Dashboard tab
  screens/india_option_chain_screen.dart  Option Chain tab (tap = pin strike, long-press = target premium)
  screens/india_pnl_report_screen.dart  Trades tab (filters, equity curve, day-wise, CSV)
  screens/india_settings_sheet.dart     Settings tab
  services/india_api.dart, widgets/india_ui.dart   small shared helpers

Rules
  * Contract: ticked pin > day chip (ITM/ATM/OTM, resets next day) > ITM default.
    "Fit my balance" steps to cheaper strikes until cost <= budget (never below min premium).
  * SL fires only when a candle CLOSES beyond it; a gap-open beyond SL exits at the open.
  * TP1 -> SL to entry (from next candle); trail off/step1/step2 as in crypto; final target TPn (default TP4).
  * INTRADAY squares off 15:15. CARRY stays overnight (needs 2+ days to expiry), force-closed on expiry day.
  * Optional emergency premium stop and max-loss-per-trade filter.

Open drawer -> MARKET -> India Paper. Both markets run independently.

Known limits (v1): demo lot sizes, fee rates and premiums are placeholders/model (verify with the broker);
no holiday calendar; open positions are not restored after a backend restart; no OI in demo.

## Fyers (added)
Settings > Exchange > Fyers: App ID, Secret ID, Redirect URL (saved on the server), then every trading day:
"Get Fyers login link" -> log in -> paste the auth code (or the whole address). Token lasts one day.
Gives: index candle history (bot warm-up from day one), real lot sizes/expiries (symbol master), quote-based premiums.
Paper trades only. Real orders are NOT built (Fyers may need a fixed IP for them - ask Fyers support).
Offline tests: python3 test_fyers.py

## Fyers live prices: WebSocket first, REST as fallback
- Prices (index spot, option premiums, the forming candle) arrive by WebSocket, so they do not use the 50 requests/minute limit.
- Install the Fyers library once on the server: `pip install fyers-apiv3`. Without it the app keeps working on REST.
- If the socket drops or stays silent in market hours, the backend restarts it by itself (pause 5s, 15s, 30s ... up to 2 min) and uses REST until it is back.
- REST is limited to 40 calls a minute by the app itself. If Fyers still says "too many requests", the app waits 20 seconds and shows the last data.
- `/api/india/status` has `feed.mode` = `WEBSOCKET` or `REST`, plus `feed.note` and `feed.api.calls_per_min`.

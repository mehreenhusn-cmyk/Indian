INDIA - ALL LATEST FILES (Part 1 backend + Part 2 Flutter) - ONE ZIP
Extract at the repo root (the folder that has backend/ and frontend/), restart the backend, rebuild the app.
Do NOT extract the older Part 1 zip on top of this one. Tradebulls files are not touched (on hold).

BACKEND (5 files + 1 test)
  backend/recovered_bot/fyers_client.py     refresh-token login, auto-renew + retry
  backend/recovered_bot/fyers_provider.py   session tracking, auto-renew, auth info, PIN field
  backend/recovered_bot/india_runtime.py    Fyers auto-reconnect after restart, resumes trading, what-if vs real balance
  backend/recovered_bot/india_calendar.py   NSE 2026 holidays with names (checked against NSE circular), Muhurat note
  backend/test_fyers_refresh.py             offline tests (run: python test_fyers_refresh.py)

FLUTTER (6 files, 1 new)
  frontend/lib/main.dart                         Crypto + India are two equal top-level markets, remembered, Back never switches
  frontend/lib/services/market_mode.dart         NEW - the remembered market switch
  frontend/lib/widgets/owl_drawer.dart           India chip switches market (no pushed page)
  frontend/lib/screens/india_paper_screen.dart   drawer wiring, holiday note, no polling while Crypto is shown
  frontend/lib/screens/india_chart_screen.dart   black-body/coloured-border EMA50 candles, right-axis price scaling,
                                                 vertical scroll, live price line + candle-close countdown, STALE badge
  frontend/lib/screens/india_broker_card.dart    Fyers PIN field, auto-login banner, what-if card

FIRST RUN (Fyers, once):  App ID, Secret, Redirect URL, PIN -> "Get Fyers login link" -> log in -> paste auth code -> Connect.
After that no daily login; the browser login is needed again in about 15 days (the card tells you).

CHART GESTURES:  drag left/right = scroll time | drag up/down = scroll price | pinch = zoom time
                 drag the RIGHT price axis up/down = stretch / squeeze price | double-tap axis = auto scale
                 double-tap chart = back to latest + auto scale | long-press = crosshair

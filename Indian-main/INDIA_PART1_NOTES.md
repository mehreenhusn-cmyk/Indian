# India Part 1 - fast live data (chart)
Only India DATA + DISPLAY. Strategy, signals, paper trades, SL/TP rules and crypto are NOT touched.

1. New tiny endpoint GET /api/india/ticks: live index prices from the Fyers WebSocket, no lock, no broker call.
2. Chart polls it about every 0.8 s and moves the newest candle + the price in the top bar with every tick (like a broker app).
   Full candles + indicators still reload every 3 s (EMA/SD/TSI/Z of the newest candle catch up on that reload).
3. Backend candles(): the broker download now runs OUTSIDE the runtime lock, so a slow first load of an index no longer freezes
   the dashboard / other charts.
4. Chart bug: tapping another index while a request was running showed the old index candles or an endless spinner. Fixed.
5. First load of an index waits up to 25 s (was 8 s). The spinner now says what it is doing.
6. One plain line under the chart says where prices come from: demo / WebSocket live / REST (slower) / Fyers limit / market closed.

Needs: Fyers connected in India Settings and the market open (9:15-15:30 IST) for real ticks.
Files: backend/recovered_bot/india_runtime.py, backend/india_api.py, backend/test_india_ticks.py,
frontend/lib/screens/india_chart_screen.dart, frontend/lib/services/india_api.dart, frontend/lib/services/india_ticks.dart (new)
Test: python3 backend/test_india_ticks.py   (Flutter was NOT compiled here - run the GitHub build, send the log if Dart shows an error)

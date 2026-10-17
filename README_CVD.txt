CVD SCENARIOS IN STRATEGY LAB - copy over the repo (same folder layout), push, RESTART the backend, rebuild the app (for the new group name).

EDIT  backend/variant_lab.py                       +6 scenarios in a new group "CVD (order flow)" (22 -> 28 total), CVD proxy from Binance taker-buy volume
EDIT  backend/filter_lab.py                        +2 lines: keeps taker-buy volume + volume next to the candles (nothing else changes)
EDIT  frontend/lib/widgets/variant_lab_card.dart   shows the new group
EDIT  test/test_variant_lab.py                     tests the 6 CVD rows

The 6 new scenarios (each vs the bot, older 60% / newer 40%):
 1 CVD agrees with the trade (last 3 candles)        - skip if buyers/sellers flow is against the signal
 2 Signal candle pushed by real flow (>=10%)         - skip "weak break" signals (fake-move filter)
 3 CVD agrees + only when bands expanding            - joins the one scenario that was BETTER before
 4 Wait 1 candle, then enter (no CVD)                - CONTROL: shows if just waiting already helps
 5 Wait 1 candle + CVD still agrees                  - compare with #4: the difference is what CVD adds
 6 Hold till opposite + CVD agrees

CVD here = (taker buy volume - taker sell volume) / volume, from the candle data Binance already gives. No new download.
Real order-book walls/depth are NOT in this test (Binance has no history for them); that needs live recording later.
Use: Strategy Doctor (crypto) -> Strategy Lab -> Run tests -> wait -> pick 3m / 5m / 15m. Trading is not touched.

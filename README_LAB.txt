STRATEGY LAB + EXCHANGE CARD FIX - one zip. Copy over the repo (same folder layout), push, restart the backend, rebuild the app.

NEW   backend/variant_lab.py                       Strategy Lab: bot's own signals replayed under 22 scenarios, one table vs the bot
EDIT  backend/filter_lab.py                        +6 lines: optional hook (EXTRA_ENRICH), nothing else changes
EDIT  backend/api_server.py                        +14 lines: GET /api/variant_lab (start=1 runs 3m, 5m, 15m)
NEW   frontend/lib/widgets/variant_lab_card.dart   the table in the app
EDIT  frontend/lib/screens/strategy_doctor_screen.dart  Strategy Lab card at the top of the CRYPTO Doctor (India untouched)
EDIT  frontend/lib/screens/india_broker_card.dart  Exchange card shows only the selected + connected exchange
NEW   test/test_variant_lab.py                     python3 test/test_variant_lab.py (no internet needed)

Use: Strategy Doctor (crypto) -> Strategy Lab -> Run tests -> wait a few minutes -> pick 3m / 5m / 15m.
Nothing here touches trading, strategy.py or any setting. Replay = evidence, not a promise.

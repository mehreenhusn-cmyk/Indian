# Ping Lab - final files (Grok build + Claude review fixes)
Run (2nd Termux window): cd backend && python ping_worker.py
Tests: cd backend && python test_ping_engine.py && python test_ping_bot.py && python test_ping_fixes.py && python test_ping_bridge.py

## Claude fixes on top of Grok's build
1. api_server.py: ping router wired inside try/except (a broken ping file can no longer stop the backend). Only this block was added.
2. ping_collector.py: new/flagged coins were never subscribed until a batch dropped - now reconnects (max every 30 s) when the wanted coin set changes.
3. ping_radar.py: a coin could never be flagged again after it was dropped - re-flag allowed after 15 min.
4. ping_engine.py: "first ping" price never reset, so chase guard / absorbed went stale after hours - a new episode now starts after 15 min quiet or a side flip.
5. ping_store.py: expanduser on OWL_DATA_DIR.
6. NEW ping_signal_bridge.py (+ 6 lines in ping_worker.py): every 5 s reads new Bot 1 signals from owl.db (READ-ONLY), writes TAKE/SKIP from the ping state at that moment, then fills each trade's real P&L from closed_trades_archive.jsonl. Score tab = loss avoided vs profit missed. Bot 2 signals ignored. Only signals from worker start onward are counted.

## Not tested
Live Binance connection, flutter analyze / phone UI, Termux long run, the signal link against your real owl.db (tested only with a fake DB).

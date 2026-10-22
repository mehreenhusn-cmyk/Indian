# Ping Lab round 2 (2026-10-23) - fixes

Root cause of "0 coins": Binance retired the old futures WebSocket URLs on 2026-04-23.
miniTicker and kline now exist only under /market. The old URLs opened but sent nothing.

1. ping_worker.py: radar uses /market URLs (raw path, then combined form), restarts a silent
   socket after 30 s, DNS fallback like the main backend, log line every 60 s, build tag r2.
2. ping_radar.py: parse_mini_ticker - 24h change is computed from open/close (miniTicker has no
   change % field; the old code made the watchlist random).
3. ping_collector.py: /market/stream, silent-socket restart, 1m history (100 candles) fetched
   BEFORE subscribing a coin, so EMA30/EMA50 and the volume baseline are ready at once.
4. ping_engine.py: seed_history(); n_closes counter.
5. ping_bot.py: variant A needs 30 closed candles, variant B needs 50 (before, EMA started
   from the first price and was wrong for the first 30-50 minutes).
6. test_ping_feed.py: 24 checks incl. a fake WebSocket for radar and collector.

Not changed: Flutter app (no new APK needed), live bot, AI Vision, owl.db (read-only).
Not tested: real Binance connection, long run on the phone.
Score/Lead numbers saved before this fix came from a worker with no data - clear them once:
  bash ~/owl_auto.sh ping-reset

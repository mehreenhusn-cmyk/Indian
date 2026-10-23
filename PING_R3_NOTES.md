# Ping Lab round 3 (2026-10-23)

Checked on the phone after round 2: radar and kline streams work (34 coins, real pings).

Fixed:
1. ping-reset did not really reset: the worker reloads ping_lead.json.bak when the main file is
   missing, so old Score rows came back (3 old + 1 new). owl_auto.sh v4.1 now deletes the .bak too.
2. Lead tab counted every coin already in the top 10 at start as a new "entry" (29 entries, 0% ping).
   Now the first tick after a start only records who is already there.
3. Live tab / header: watchlist coins with no ping were added as fake BUY rows ("22 buy").
   Now only coins that really pinged are listed; the watchlist is a separate field in the snapshot.
4. Less writing to phone storage: the live snapshot is written without fsync/.bak, and the Ping Bot
   and Lead files are saved only when something changed (or once a minute), not every 2-5 seconds.
5. App: the latency badge next to CRYPTO / INDIA shows only the ms value, bigger and bold
   (frontend/lib/widgets/live_ticker_bar.dart, needs a new APK to be visible).

Tests: test_ping_r3.py (10 checks) + all earlier ping tests pass.
Not tested: Flutter build (no Flutter SDK here), long run on the phone.

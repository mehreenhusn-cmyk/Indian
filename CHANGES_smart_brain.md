# Latest files: Parts 2 + 3 + Smart Brain (ONE zip, only changed files, copy over the repo)

## Already in the earlier zip (Parts 2 + 3, included again so everything is the latest)
- Old labs lock (Strategy Lab / Scan Lab / old AI lab off), honest Dual Bot status, BTC tile opens chart,
  Signals/Alerts header cleanup, Yesterday shown once, P&L fits Dual Bot cards, tab swipe. See CHANGES_parts_2_3.md.

## NEW: Smart Brain (Dual Bot v2 side layer, paper only, analysis + scoring only)
- backend/smart_brain.py (new): reads dual_lab_data.json (READ ONLY), writes only smart_brain_view.json.
  divergence score, clean score 0-100, look-alike win probability ("not enough data" below 20 similar trades),
  time of day, fast vs slow, repeat-loss mixes, good mixes, band check of the score, opportunity watch list (no trades),
  trust meter (scores checked on trades it had not seen, vs "take every signal").
- backend/api_server.py: new route GET /api/smart_brain (?action=start|stop), worker starts 75 s after boot.
- backend/test_smart_brain.py (new): 29 checks. test_dual_lab.py still 67 checks.
- frontend/lib/widgets/smart_brain_view.dart (new) + dual_bot_screen.dart: "Dual Bot | Brain" switch at the top of Dual Bot.

## Part 2 of Smart Brain: the Brain's own paper book
- smart_brain.py: picks (enough look-alikes, >=55% won, clean >=60, Main/Z not disagreeing) are frozen at signal time, forward only,
  never changed afterwards. 'shadow' until the trust meter says EARNED, then 'paper'. Result = Dual Bot's own trade for that signal.
  Compared with ALL signals since the book started. Own file: smart_brain_book.json. Dual Bot data is still read-only.
- smart_brain_view.dart: new card "Brain's own paper book". test_smart_brain.py: 38 checks (test_dual_lab.py still 67).

## Not touched
Dual Bot v1 trading, exits and data files, Vision AI, Ping, Tag Lab.
Chart controls (measure tool, per-pane axis drag, crosshair across lower panes) were already in the repo.
Flutter was NOT compiled here (brackets only checked): build on the phone and tell me any error.

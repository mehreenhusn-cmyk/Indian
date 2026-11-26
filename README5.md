# README5 - BRAIN TRADER PLAN + HOW WE WORK (v28, 1 Nov 2026, after Parts N1 + N2 + Sniper S1 to S7)
When the owner says "read README5 and continue", read this file first, then README4 (build log, top note = newest).

## How we work (owner rules)
- Small parts, every NEW file under 350 lines. Old files over 350 are not split unless a part has to touch them (v2_data.py is 396, split later).
- ONE cumulative zip per part: it holds every file of the earlier parts of this chat, so only the newest zip is downloaded. Zip folder = Indian-main/.
- Owner reads Roman English / Hinglish. Say plainly what was NOT run (Dart is never compiled here, nothing runs on the phone, the APK build is the first real test).
- No Termux commands for the owner: the zip is applied by tools/owl_auto.sh (BUILD 44), which pushes to GitHub.
- README5.md and docs/mockups/ (jpg, png, md only) are on the push allowlist since BUILD 44. If they are missing on GitHub, run: bash ~/owl_auto.sh pushcheck and send the output.
- ZIP NAME + DOWNLOAD RULE (found 1 Nov 2026): never leave an Indian-main*.zip (the GitHub repo download) in Download that is NEWER than the owl zip. owl_auto.sh then calls the owl zip OLDER than the full zip and skips it (log: "zip skipped ... OLDER than the full zip deployed"), and it deploys the old repo as live code. Delete Indian-main*.zip first, then save the owl zip. If nothing was pushed: bash ~/owl_auto.sh pushcheck.
- README4 FIRST LINE: owl_auto.sh reads the version in the first 600 bytes of README4 ("(v191,"). Bump it in EVERY zip (it stayed at v169 until v190, so the stale-zip guard was blind).
- The Brain never trades live. LIVE is locked until the Graduation gate AND the owner's own OK.

## Parts (status)
| Part | What | Files | Status |
|---|---|---|---|
| 0 | Push fix (README5, mockups, other repo safe) | tools/owl_auto.sh | done |
| 88c | USE row holdout judged the right way round | v2_bt_playbook.py | done |
| 90a | Brain Health backend + route + 7 tests | v2_bt_health.py | done |
| 90b | Brain Health screen, part 1 | brain_health_screen.dart | done |
| 90c | Safety, graduation, missing cards | brain_health_cards.dart | done |
| 91a | Simple Results backend: verdict, equity, drawdown, losing streak, USE / STOP | v2_bt_verdict.py, route brain_verdict, test_v2_bt_verdict.py | done |
| 91b | Simple Results screen (one verdict card, USE / STOP lines, details behind a button) | simple_results_screen.dart (240), provider +3, More row +3 | done |
| X1 | 3-way comparison per day (Brain / Current Bot / Take-All simulation) + 30-day calendar, route brain_compare | v2_bt_compare.py (181), test (6) | done |
| X2 | Day calendar + comparison SCREEN (on brain_compare), provider + More row | day_compare_screen.dart (125), day_compare_cards.dart (104), widgets/equity_line.dart (51) | done |
| 87c | bot-vs-Brain card DONE (v2_bt_botcmp.py 107, bt_signal_screen.dart +16, 5 tests). TP2 and PAPER ENTER wait for the owner's OK (new rule version / a write route) | bt_signal_screen.dart, v2_bt_detail.py | half |
| 64-65 | Final check + README close | README4.md (v188) | done (sandbox only) |

## Owner wish (1 Nov 2026) in one paragraph
The Brain trades from the indicators by itself (paper), learns when the indicators make profit and loss, can close a trade by indicator so profit is not given back, and the screen shows: trades today, profit trades, loss trades, and over weeks fewer mistakes / more profit. Mock pictures 10 to 16 are IDEAS the owner liked, not designs to copy.
## NEW PARTS (order = what to build first). Lines = estimate, new code + tests
| Part | What | Files | Lines |
|---|---|---|---|
| L1 (DONE, v2_bt_progress.py 126 + test 155) | Learning Progress backend: per day (30 days) trades, profit / loss counts, net, loss per trade, older vs newer half trend (30+ trades rule), 'mistakes' = biggest losing groups in plain words, 'fixed' = groups that stopped losing | v2_bt_progress.py, route brain_progress, test | ~220 + ~110 |
| L2 (DONE, Dart NOT compiled) | Learning Progress screen on route brain_progress: PAPER / SHADOW / REPLAY tabs, Brain today (trades / profit / loss / net / decisions), is it getting better (older vs newer half), 5 weeks with a bar of losing trades per 10, Mistakes, Fixed, Got worse, What it learned, last days | learning_progress_screen.dart (94), learning_progress_cards.dart (168), provider fetchBrainProgress +3, More row +4 | ~270 |
| E1 (DONE, v2_bt_exitlab.py 167, route brain_exits, no test by owner rule) | Exit study: same old trades, other exits (TSI turns, half of the gain given back, break-even stop), net / give-back / worst dip / both halves | v2_bt_exitlab.py + test | ~250 + ~120 |
| E2 (DONE, Dart NOT compiled) | Exit Study screen | exit_study_screen.dart | ~230 |
| E3 (DONE, v2_bt_exit2.py = BT-02, SHADOW only; the Brain decides protect / close / TP2 by reading TSI + Z) | Exits that win run as BT-02 in SHADOW only (frozen version); owner OK only to move it to PAPER | v2_bt_sim.py edit, v2_bt_store version, test | ~120 + ~100 |
| E4 (DONE) | Active trade labels (HOLD / PROTECT / CLOSE) use the same exit rule | v2_bt_detail.py, bt_trade_screen | ~60 |
| E5 (DONE, fourth number brain_bt02) | BT-01 vs BT-02 in the X1 comparison | v2_bt_compare.py edit | ~150 |
| M1 (DONE: M1a v2_sys_health.py 189 + route sys_health, M1b system_health_screen.dart 132, Dart NOT compiled) | System Health screen (mock 10): only real facts, rest NOT AVAILABLE | v2_sys_health.py, system_health_screen.dart | ~200 + ~250 |
| M2 (DONE: month_view in v2_bt_compare.py, route brain_month, month_grid_screen.dart 215, Dart NOT compiled) | Month calendar like mock 16 on top of Day Compare | v2_bt_compare.py (+month), month_grid screen | ~40 + ~200 |
| M3 (DONE, Dart NOT compiled yet) | Brain Dashboard (mock 11 / 15 ideas, real numbers only): today net + gross / fees / slippage, Brain 30 days next to Current Bot 30 days (never added), open long / short, today signals, DAILY LOSS CAP bar (guard cap, used = today's net loss only), last 8 days strip, all-time Brain net, the Brain's own sentence. NO account balance (none is real). Route brain_dash. First row of More | v2_bt_dash.py (99), test_v2_bt_dash.py (9 tests), brain_dashboard_screen.dart (93), brain_dashboard_cards.dart (184), v2_data.py +8 (now 414), provider +3, More row +3 | ~390 |
| M4a + M4b (🟢 DONE, Dart NOT compiled) | Brain and Activity timeline (mock 13): one UTC day, Brain decisions / trades next to the Current Bot's closed trades, clock in IST, per-coin table with BOTH marked. Route brain_timeline | v2_bt_timeline.py (157), timeline_screen.dart (135), timeline_cards.dart (122), provider fetchBrainTimeline, More row "Brain and Activity" | ~320 |
| M4c (🟢 DONE, the split) | v2_data.py 431 -> 306 (Brain pages now in api/v2_brain_views.py 148, same code), app_provider_positions.dart 389 -> 341 (Brain fetches now in app_provider_brain.dart 73, same names). Also fixed: the router passes source / month / state / skip / only now | api/v2_brain_views.py, api/v2_data.py, providers/app_provider_brain.dart, providers/app_provider_positions.dart, providers/app_provider.dart (+1) | ~0 new |
| 🟢 FIX (build) | Flutter CI #188 red: bt_trade_screen.dart line 129 apostrophe, escaped | bt_trade_screen.dart | 1 |
| M5 (🟢 DONE, owner wish: the Brain manages the trade itself) | BT-03 = BT-02 exit + trailing stop after TP1 + early cut of a losing trade; runs in PAPER while v2_bt_manager_on = 1 (switched ON once at first start); Exit Study rule MANAGER judges it on the old trades; BT-02 stays in SHADOW | v2_bt_exit2.py, v2_bt_sim.py, v2_bt_detail.py, v2_bt_exitlab.py, v2_bt_wait.py, v2_bt_auto.py, v2_bt_compare.py, day_compare_cards.dart | ~110 |
| N1 (🟢 DONE, Python run on fake candles only) | Data-quality chip on Brain Health is a REAL check: newest 200 candles of up to 40 followed coins, stale / bad rows / gaps -> PASS / WARN / FAIL, NOT_CHECKED when no store | v2_bt_dataq.py (87), v2_bt_guard.py (edit, +_dq) | ~100 |
| N2 (🟢 DONE, Dart NOT compiled) | Brain Ready? screen on route brain_ready: what the Brain does by itself (find chances, paper trades, manage the trade) + 8 plain checks (runner, 30+ trades, 7+ days, PROFIT, holdout, 2+ states, data quality, kill switch). Live stays LOCKED even when all pass | v2_bt_ready.py (115), api/v2_brain_views.py, api/v2_data.py, brain_ready_screen.dart (166), app_provider_brain.dart, more_screen.dart | ~300 |
| owner OK | TP2 is DONE inside BT-02 / BT-03 (the Brain decides it). PAPER ENTER / Confirm Paper Order (need a WRITE route) | - | ~150 |
Total about 3,000 lines in 11 parts (without the owner-OK parts).
## Open points
- v200 = Parts N1 + N2 (ONE zip, only changed / new files). Check Flutter CI of the commit 'auto: owl_PartN2.zip' (brain_ready_screen.dart is new Dart) and send the error text if it is red. After this the BUILD LIST IS EMPTY: only the owner-OK items below and the weeks of paper data are left.
- OWNER OK LEFT: PAPER ENTER button (needs a write route; the Brain opens paper trades by itself, so it is only for hand-made paper trades) and moving BT-02 from SHADOW to PAPER (after weeks of data). LIVE needs the Graduation gate AND the owner's own OK.
- v198 = Parts M4a + M4b + M4c (ONE zip, only files not in the repo yet). Check Flutter CI of the commit 'auto: owl_PartM4.zip' (Dart of M3, E, M1, M2 and M4 was never compiled together) and send the error text if it is red. The SHADOW / REPLAY tabs now really work (router fix), so numbers may look different from before on those tabs.
- STILL LEFT (owner OK needed): TP2 (display-only second price, or a new rule version BT-03) and PAPER ENTER button (needs a WRITE route).
- OWNER RULE 1 Nov (E1): NO tests are written or run any more; files are written directly and the owner checks when the app is built. Python is only syntax-checked.
- v197 = owl_PartM2 (CUMULATIVE with E1 to E5 + M1). v196 = owl_PartM1b (CUMULATIVE with E1 to E5 + M1a). v195 = owl_PartM1a (CUMULATIVE with E1 to E5). v194 = owl_PartE5 (CUMULATIVE with E1 + E2; E3 BT-02 SHADOW tick, E4 labels, E5 compare). Moving BT-02 from SHADOW to PAPER needs the owner's OK after the Exit Study BRAIN row and weeks of SHADOW trades. v193 = owl_PartE2 (E1 backend + E2 screen). Check Flutter CI of the commit 'auto: owl_PartE2.zip' and send the error text if it is red.
- v191 = owl_PartL2 pushed (Flutter CI #186 green). From v192 on a zip holds ONLY the files that are not in the repo yet (new or changed since the last pushed zip), owner wish 1 Nov.
- Why X1 / X2 / L1 were not pushed on 1 Nov: Termux was killed by Android (watcher last alive 14:07, restarted 15:06), the owner's Indian-main (63).zip then counted as the newest full zip and the owl zips were 'OLDER'. Keep Termux battery on 'Unrestricted', run: bash ~/owl_auto.sh install-bashrc, and never leave a newer Indian-main*.zip in Download.
- OWNER DECISION: 87c TP2 (real second target = new rule version BT-02, or a display-only price) and the PAPER ENTER button (needs a write route). Not built.
- 9 old test failures (test_v2_api 2, brain_ab 1, brain_cards 1, graduation 3, positions_ui 1, reports_route 1) fail the same on the owner's uploaded repo 61.
- v2_data.py (306) and app_provider_positions.dart (341) are under 350 lines since M4c.
- Dart: GitHub Flutter CI (release APK build) was GREEN for #184 (Part 90c), #185 (Part 91b) and #186 (Part L2, which also carried X1 / X2 / L1), so that Dart compiles. The Dart of M3 (brain_dashboard_*.dart) is new: check Flutter CI of the commit 'auto: owl_PartM3.zip' and send the error text if it is red.
- Data quality chip is real since Part N1 (v2_bt_dataq.py). It says NOT_CHECKED only when there is no candle store or no followed coin.
- Old failing tests (not ours): test_v2_api 2, test_v2_brain_cards 1, test_v2_positions_ui 1.
- A COPY of README5 and of ALL 9 mock pictures lives in tools/notes/ (tools/notes/mockups/) (that folder passes every push filter). Keep both copies equal.
- Mock screens: 9 pictures in docs/mockups/ (restored from owl_Part90c.zip + 09) belong in docs/mockups/. If this folder is empty, the pictures must be put back from an older zip.
- OWL SNIPER (1 Nov, idea from a Google prompt, owner approved plan): standalone WATCHER, pure python (no numpy/pandas/sklearn/optuna), population SD like Pine, no CHoCH/BOS, no old file edited, no trade touched, no tests (owner rule E1). Parts S1-S7: S1 backend/owl_sniper_engine.py core (DONE, 238 lines: sma/ema/pstdev/TSI/Z/EMA30-50 cloud/regime guard/raw signal) | S2 same file (DONE, file now 486 lines): USDT-fee simulator (fee 0.05% + slip 0.02% per side), train/test split by whole UTC days (newest 30% = TEST), seeded random search of SD length / EMA / stop / sideways ratio on TRAIN only, 200 called wrong ONLY if the winner also wins on TEST (>=15 trades, t-stat >=2), else NOT PROVEN and settings stay; calibrate() + collect_trades() ready for S3 | S3 (DONE, NEW file backend/owl_sniper_prob.py 253 lines, because the engine file is already 487 > 350; engine file unchanged): pure-python logistic win-chance learned on TRAIN trades, 85% floor judged on TEST trades only (15+ signals at 85%+, win rate 85%+, profit after fees, else FLOOR NOT PROVEN and no signal passes), OwlSniperLive.run_all() / evaluate_live() / insight_report() / export_model() / load_model(); actions STANDBY / SCANNING_MARKET / BLOCK_TRADE / SNIPER_LONG / SNIPER_SHORT (watch only); run on made-up candles only, not on real candles or the phone | S4 (DONE, NEW backend/owl_sniper_feed.py 347 lines, Python only syntax-checked, NOT run): reads the newest gap-free 5m run of up to 40 coins from v2_market.db READ-ONLY, calibrate() (SD search + win-chance model + floor proof + TEST-day equity curve) saves v2_sniper_model.json (again after 24 h; 6 h if not trained; 30 min if no candles), scan() saves v2_sniper_live.json (headline, Safe / Sideways banner, order cards newest first with no repeats), refresh() = both with a lock file, kick() starts refresh as its OWN low-priority process when the live file is older than 4.5 min = AUTO START WITHOUT Termux commands; switch file v2_sniper_off stops it | S5 (DONE, NEW backend/api/sniper.py 81 lines, NOT mounted): read-only route GET /api/v2/sniper (same v2_api_enabled switch), it only reads the two result files and calls kick(); NO test file by owner rule. api_server.py mount WAITS for the owner "mount ok" (4 lines are written at the top of api/sniper.py) | S6 (DONE, Dart NOT compiled, the APK build is the proof): NEW frontend/lib/screens/sniper_panels.dart (278: Trending / Sideways banner, TEST-day equity lines after fees, 85% floor PROVEN / NOT PROVEN card, order cards green = passes / amber = blocked with the plain reason, insight report lines) + NEW sniper_screen.dart (90: fetch every 30 s while open, off / old / error texts, pull to refresh); small edits: providers/app_provider_brain.dart +3 (fetchSniper, now 79), screens/more_screen.dart +3 (import + row 'OwlSniper' after Brain Ready?, now 255); day_compare_screen.dart untouched. The page shows the 'old' text until the owner says "mount ok" | S7 (DONE): this README5 + README4 v203 + the OWL SNIPER FILE LIST below. Zip names owl_PartS1.zip, owl_PartS2.zip, owl_PartS3.zip, owl_PartS5.zip (S4 + S5), owl_PartS7.zip (S6 + S7; CUMULATIVE with S1 to S5, so it is the ONE zip to push).

## OWL SNIPER FILE LIST (final, Parts S1 to S7, 1 Nov 2026)
| File | Lines | Part | What |
|---|---|---|---|
| backend/owl_sniper_engine.py | 487 | S1 + S2 | indicators (population SD like Pine), sideways guard, USDT-fee simulator, train / test days, SD-length search. Over 350: not split, nothing touches it any more |
| backend/owl_sniper_prob.py | 253 | S3 | win-chance model (plain python), 85% floor proof on TEST days, evaluate_live(), insight report |
| backend/owl_sniper_feed.py | 347 | S4 | reads v2_market.db read-only, calibrate / scan / refresh / kick, saves v2_sniper_model.json + v2_sniper_live.json. Full: do not add to it |
| backend/api/sniper.py | 81 | S5 | read-only route GET /api/v2/sniper (NOT mounted yet) |
| frontend/lib/screens/sniper_panels.dart | 278 | S6 | the panels |
| frontend/lib/screens/sniper_screen.dart | 90 | S6 | the screen |
| providers/app_provider_brain.dart (+3), screens/more_screen.dart (+3) | | S6 | fetchSniper + the More row |
How it starts without Termux: the page calls the route, the route calls kick(), kick() starts `owl_sniper_feed.py refresh` as its own low-priority process. Switch off: make the file v2_sniper_off in the data folder (delete it to switch on).
STILL OPEN for OwlSniper: (1) owner says "mount ok" -> 4 lines in api_server.py (they are in the header of backend/api/sniper.py); (2) NOTHING of S4 / S5 / S6 was ever run (owner rule: no test run), so the first real run is on the phone: check Flutter CI of the commit 'auto: owl_PartS7.zip' and send the error text if it is red; (3) the first calibration needs 6+ whole days of 5m candles and takes minutes on a phone; (4) on real candles the 85% floor may stay NOT PROVEN for a long time: that is the honest answer, the floor is never lowered; (5) OwlSniper never trades: it has no order code at all.

## PHONE LITE (25 Nov 2026) - backend back on the phone, only the current bot, everything else OFF
Owner (Hussain) wish, his words short: (1) shift the backend from the VPS to his phone Termux, faster and light; (2) keep ONLY the current bot (crypto + India market data as it is) and its scanner (OwlSniper is OFF too since 25 Nov 01:50, see 'UPDATE' below); (3) disable Vision AI, Dual Bot, Smart Brain, Price Action, Volume layer, V2 collectors (ticker every 5 min + candle stream), Ping Lab and the memory/load meters; also the B3 / fake-signal (chop) tests; (4) signals only in the APP, NOT on Telegram; (5) hide the extra screens (the app has about 80), no background data; (6) his Download must auto-update the repo again like before (owl_auto.sh), and the app must stop talking to the VPS.
STATUS (read the UPDATE section at the end of this part first, it replaces the plan table above): PLAN ONLY. README written 25 Nov 2026, NO code built yet. Build starts only after the owner says "ok". Nothing was run (Python / Dart not compiled).

### What the repo does today (found in Indian-main (41).zip)
- backend/api_server.py on_startup launches: Vision AI (setting vision_enabled, default True), dual_lab.ensure_running (8 s), smart_brain (15 s), pa_layer (25 s), vol_layer (35 s), v2_runner.start_watchdog (45 s; ticker every 5 min, candles + websocket, paper Brain tick, labs every 6 h), loop_watch + load_report + memwatch (meters). ping_worker.py is a SEPARATE process started by tools/owl_auto.sh. Worker switch files exist (dual_lab_ctl.json, smart_brain_ctl.json, v2 switch files) but nothing sets them all off at once.
- Telegram senders: recovered_bot/telegram.py, india_telegram.py (own watcher thread started by india_runtime.py), india_shot.py. backend/main.py is the OLD Kivy app (not the live backend) but it holds a Telegram bot token in plain text in a PUBLIC repo: owner must revoke it in BotFather and make a new one; Round 1 moves it out.
- App: frontend/lib/navigation/app_routes.dart (11 screens in main.dart _screens list, bar = Home, Positions, Sniper, Study Lab, More), screens/ has about 80 files / 30k lines, 66 Timer.periodic in lib. frontend/lib/config_flags.dart already has one flag (kShowStrategyDoctor). providers/app_provider.dart line 81 default Backend URL = http://100.85.188.83:8000 (the VPS over Tailscale).
- backend/start.py binds 0.0.0.0:8000 (on Wi-Fi other devices could reach the bot API; API_TOKEN is off). On the phone the app uses 127.0.0.1, so LITE binds 127.0.0.1.
- PUSH ALLOWLIST TRAP: tools/owl_auto.sh does NOT list README_VPS.md and owl_push_only.sh does NOT list README_PHONE.md, so a new top-level README is silently skipped. That is why the phone docs live in README4 / README5 / README_VPS.md / CLAUDE_HANDOFF.md only. Round 3 also adds README_VPS.md to the owl_auto.sh list.

### Plan (3 rounds, ONE cumulative zip, about 445 lines; every NEW file under 350 lines)
| Round | File | Lines | Job |
|---|---|---|---|
| 1 Backend | backend/lite.py (NEW) | ~70 | one switch lite_mode (default ON, env OWL_LITE=0 turns it off) + helper skip(name) |
| 1 | backend/api_server.py | ~60 | skip Vision AI, dual_lab, smart_brain, pa_layer, vol_layer, v2_runner, memwatch, load_report, loop_watch when lite |
| 1 | backend/ping_worker.py | ~15 | exits at once when lite |
| 1 | recovered_bot/telegram.py, india_telegram.py, india_shot.py | ~40 | no Telegram send when lite (signal still goes to the app feed); token read from env, not from code |
| 1 | backend/start.py | ~6 | host 127.0.0.1 when lite |
| 2 App | frontend/lib/config_flags.dart | ~30 | kLiteMode flag |
| 2 | navigation/app_routes.dart + main.dart | ~80 | bar = Home, Positions, Sniper, More (4 tabs); Brain, Dual, AI, Study Lab, Diagnostics hidden |
| 2 | screens/more_screen.dart | ~60 | remove rows of hidden features |
| 2 | providers/app_provider.dart | ~40 | default URL http://127.0.0.1:8000, stop timers/polls of hidden screens |
| 3 Phone | tools/owl_auto.sh | ~45 | BUILD 49 (self-update), do not start ping, OWL_LITE=1, MALLOC_ARENA_MAX=2, README_VPS.md on the push list |
| 3 | README4 / README5 / README_VPS / CLAUDE_HANDOFF | docs | commands: README4 > MERGE-TIME COMMANDS > PHONE MOVE (already written 25 Nov) |

### Rules for the build
- Do NOT delete files or trade data; LITE only switches things off (the owner can turn them back with OWL_LITE=0 and kLiteMode=false).
- The crypto bot, paper_trader / binance_trader, India runtime and OwlSniper stay unchanged.
- Order at merge time: stop VPS -> copy data -> start phone (PHONE MOVE block). Never both backends together.
- After the move owl_auto.sh replaces owl_push_only.sh (do not run both: double push).
- Honest limit: the phone got hot before; LITE should cut a lot but the bot + India feed still run.
- Owner rules still apply: simple English, ONE question at a time, plan with files + lines first, commands only in the README (README4 MERGE-TIME COMMANDS).

### UPDATE 25 Nov 2026 (01:50 IST) - owner decisions that REPLACE the plan table above
1. The VPS is OFFLINE and the owner said: leave it, forget the old VPS-only trades. No copy / merge is planned. Live data = the phone folder ~/storage/shared/owl_data. (Details: README4 > MERGE-TIME COMMANDS > PHONE MOVE.)
2. Sniper (OwlSniper: routes, autopilot, paper / LEARN loop, feed) is ALSO OFF now. KEEP only: the current crypto bot (bot + its scanner, paper_trader / binance_trader, signals, positions, Today P&L) and the Indian market runtime (india_runtime and friends). "UI later": no UI redesign in this work.
3. ~~Signals only in the app. No Telegram.~~ CHANGED 26 Nov 2026: the CURRENT bot and India send to Telegram exactly as before (the Round 1 guard was removed). Only the NEW Pump / Dump scanner is app-only.
4. Readers: the dashboard rows Dual Bot / Brain / Sniper (LEARN) and their numbers disappear with LITE. The daily target / loss pause then counts the main bot book only (Sniper trades no longer exist).

### REVISED PLAN (3 rounds, ONE cumulative zip, about 570 lines; every NEW file under 350 lines). Nothing is built yet: wait for the owner's "ok".
| Round | File | Lines | Job |
|---|---|---|---|
| 1 Backend | backend/lite.py (NEW) | ~70 | one switch lite_mode (default ON, env OWL_LITE=0 turns it off) + helper skip(name) |
| 1 | backend/api_server.py | ~90 | skip at boot: Vision AI, dual_lab, smart_brain, pa_layer, vol_layer, v2_runner, memwatch, load_report, loop_watch, AND the Sniper mount block (lines ~800-820: api.sniper, sniper_paper, sniper_mount = routes + autopilot + paper loop) |
| 1 | backend/ping_worker.py | ~15 | exits at once when lite |
| 1 | recovered_bot/telegram.py, india_telegram.py, india_shot.py | ~40 | no Telegram send when lite (signal stays in the app feed); bot token read from env, not from code |
| 1 | backend/start.py | ~6 | host 127.0.0.1 when lite |
| 2 App | frontend/lib/config_flags.dart | ~30 | kLiteMode flag |
| 2 | navigation/app_routes.dart + main.dart | ~90 | bar = Home, Positions, Signals, More; Sniper, Study Lab, Brain, Dual, AI, Diagnostics hidden |
| 2 | screens/dashboard_screen.dart | ~60 | remove the Dual / Brain / Sniper rows, Diagnostics section, books strip |
| 2 | screens/more_screen.dart | ~70 | remove rows of hidden features |
| 2 | providers/app_provider.dart | ~50 | default URL http://127.0.0.1:8000; stop timers / polls of hidden screens |
| 3 Phone | tools/owl_auto.sh | ~50 | BUILD 49 (self-update), do not start ping, OWL_LITE=1, MALLOC_ARENA_MAX=2, fix the harmless 'line 816 /proc/<pid>/cmdline' message, README_VPS.md on the push list |
| 3 | README4 / README5 / README_VPS / CLAUDE_HANDOFF | docs | already written 25 Nov (this section + PHONE MOVE block) |
Total about 570 lines, 3 rounds. After the build the Python and Dart are NOT compiled / run here: first real test = the phone.

### DISABLED - DO NOT TOUCH (any Claude: read this before you change anything)
Everything in this table is switched OFF on purpose by LITE mode (backend/lite.py + kLiteMode in frontend/lib/config_flags.dart). The code stays in the repo, nothing was deleted, no trade data was deleted.
| Feature | Starts from | LITE switches it off by | Rule |
|---|---|---|---|
| Vision AI | api_server on_startup (setting vision_enabled) | skip at boot | do not re-enable |
| Dual Bot | dual_lab.ensure_running (dual_lab_ctl.json) | skip at boot | do not re-enable |
| Smart Brain (+ B3 / G1 / G2, Brain screens, Brain chat) | smart_brain.ensure_running | skip at boot | do not re-enable |
| Price Action layer | pa_layer.ensure_running | skip at boot | do not re-enable |
| Volume layer | vol_layer.ensure_running | skip at boot | do not re-enable |
| V2 collectors (ticker every 5 min, candles + websocket, paper Brain tick, labs every 6 h) | v2_runner.start_watchdog | skip at boot | do not re-enable |
| Ping Lab | tools/owl_auto.sh start_ping + backend/ping_worker.py | no start + worker exits | do not re-enable |
| Memory / load meters | memwatch, load_report, loop_watch | skip at boot | do not re-enable |
| OwlSniper (feed, paper / LEARN loop, autopilot, routes) | api_server Sniper mount block | block skipped | do not re-enable |
| Study Lab, Radar, Ledger, Scalp Lab, Filter / Chop (fake-signal) labs, Data Explorer, Diagnostics screens | App screens + read-only routes | hidden in the app, no timers | do not unhide |
| ~~Telegram sending (bot + India signals)~~ | recovered_bot/telegram.py, india_telegram.py, india_shot.py | **BACK ON since 26 Nov 2026 (owner's words: the current bot's Telegram must go as before). Do NOT switch it off again.** | the Round 1 guards in telegram.py / india_telegram.py were removed |
KEPT and running: the current crypto bot with its scanner (paper_trader / binance_trader, signals, positions, Today P&L), the Indian market runtime, Settings. App tabs: Home, Positions, Signals, More.
RULES: (1) Do NOT re-enable, unhide, repair or extend a disabled feature unless the owner says so in plain words. (2) Do NOT delete files or data; only the small LITE guards may be added to the disabled files. (3) A new feature must NOT add a background thread, process, timer or poll without the owner's ok (the phone got hot and the app heavy before). (4) If something in a hidden area looks broken, leave it. (5) To turn LITE off for a test: env OWL_LITE=0 and kLiteMode=false, never by deleting guards. (6) Owner rules still apply: simple English, ONE question at a time, plan with files + lines first, commands only in README4 MERGE-TIME COMMANDS.

### BUILD LOG - PHONE LITE (newest at the bottom)
**Round 1 (backend) BUILT 25 Nov 2026 - owner said "round 1 kr".** Round 2 (app) BUILT 26 Nov 2026 (see below). Round 3 (tools/owl_auto.sh, BUILD 49) BUILT 26 Nov 2026 (see below).
| File | Changed / new lines | What |
|---|---|---|
| backend/lite.py (NEW) | 41 | the ONE switch: lite.is_lite() (default ON, env OWL_LITE=0 turns it off), lite.off(name) (True = do NOT start, one log line per name), lite.summary() |
| backend/api_server.py | ~116 (most are the Sniper block indented under one guard) | `import lite`; guards: vision_ai, dual_lab, smart_brain, pa_layer, vol_layer, v2_runner, load_meters (loop_watch + load_report), memwatch, swr_prewarm (AI-tab pre-build), and ONE guard "sniper" around the whole OwlSniper / lab / chop mount block (routes AND their background loops, which start when a router is made); new read-only route GET /api/lite |
| backend/ping_worker.py | 7 | main() returns at once in LITE |
| backend/start.py | 7 | host 127.0.0.1 in LITE (only this phone can reach the bot API; Wi-Fi / Tailscale access to port 8000 is gone) |
| backend/recovered_bot/telegram.py | 9 | _creds() returns empty in LITE, so every send returns early; the status card says "Telegram is OFF (LITE mode)" |
| backend/recovered_bot/india_telegram.py | 10 | no watcher thread in LITE + _creds() empty. india_shot.py needs NO change (only called after a card was sent). India signals in the app come from india_runtime, not from this Telegram class |
Tested here: py_compile of all 6 files OK; lite switch + TelegramNotifier._creds() run OK (LITE on -> empty, OWL_LITE=0 -> normal). NOT tested here: the backend itself was NOT started (fastapi is not installed in the build sandbox). First real test = the phone: `owlcheck`, then open `http://127.0.0.1:8000/api/lite` (must show "lite": true and a kept_off list).
Known effects until Round 2: the app's Dual / Brain / Sniper / Study Lab / AI screens call routes that now answer 404 or are empty; Round 2 hides those screens and rows. The Telegram bot token in the OLD Kivy file backend/main.py is still there (it is NOT used by the live backend): the owner must revoke it in BotFather; removing it from the file is a separate small job.
Not changed on purpose: the crypto bot, paper_trader / binance_trader, its scanner, india_runtime, status / settings routes, telemetry, the status broadcaster.

**Round 2 (app) BUILT 26 Nov 2026 - owner said "Karo".** ONE flag does it all: `kLite = true` in frontend/lib/config_flags.dart (set false = old app back; the backend then needs OWL_LITE=0 too). Dart was NOT compiled here (no Flutter in the build sandbox): bracket balance checked only. The GitHub APK build is the first real compile; if it fails, read the build log and fix the named line only.
| File | What |
|---|---|
| frontend/lib/config_flags.dart | `kLite` (true) and `kLiteBackendUrl` = http://127.0.0.1:8000 |
| navigation/app_routes.dart | bar = Home, Positions, Signals, More. New `AppRoutes.hidden` (dualBot, ai, brain, sniper, studyLab, diagnostics) + `isHidden()`. gearPages / underGear = Market only. orderProblems() skips hidden pages. The enum and screen numbers are NOT changed, so main.dart's _screens list is untouched |
| widgets/bottom_nav_bar.dart, owl_nav_icons.dart | 4 labels (Home, Positions, Signals, More); tab 3 icon = sensors; More = dots |
| providers/app_provider.dart | default URL = 127.0.0.1:8000; a saved 100.x (Tailscale / VPS) URL is replaced by it at start; goToTab() ignores hidden pages; warmAi() and fetchAiAdvice() do nothing; error text points to `owlon` |
| screens/dashboard_screen.dart | no Brain strip, no Sniper table, no Study Lab verdict line, no load row, no Tag Lab, no Diagnostics section, no "Sniper / Dual / Brain are separate" note |
| screens/more_screen.dart | tiles removed: Chop Bot, Brain Dashboard, Brain, Dual Bot, Signals (it is a tab now), AI, Ask the Brain, Data Health, Data and Learning, Screenshot Check, Brain Today, Brain and Activity, Dual Bot report, Diagnostics, Ping Lab. Kept: Market, Trades, Month Calendar, Simple Results, AI Report, Fees and tax, App report, Trades CSV, App Problems, Settings |
| widgets/owl_drawer.dart | AI Assistant tile always hidden |
Hidden screens are never built, so their timers and fetches do not run. No file was deleted. Not changed on purpose: positions, signals, India screens, settings, websocket service.
Still to do: Round 3 (tools/owl_auto.sh starts only the backend, lite on) and the first phone test: `owlon`, then http://127.0.0.1:8000/api/lite must say "lite": true, then install the new APK and check the 4 tabs.


## PUMP DUMP SCANNER (built 26 Nov 2026, owner said "ab vo kaam chalu karo")
What the owner asked (PDF "Claude10", his words short): catch a coin BEFORE / AT THE START of a pump or a dump, for ALL Binance USDT-M futures coins (top 10 or not). Signals ONLY in the app (NO Telegram for this scanner), in its OWN TAB: pump coins on one side (left, green), dump coins on the other (right, red), clearly, day by day with the time, organised. It must learn by itself (fake alerts get a penalty, thresholds move slowly, a daily report). The current bot's Telegram stays exactly as before.
**This is the ONE new background job allowed in LITE.** Rule for every Claude: do not add other jobs; do not make it send to Telegram; do not delete its files.
### How it works (all offline-tested; see test/test_pd_scanner.py)
- ONE thread (backend/pd_runner.py), started by api_server.py at boot. Every 20 s ONE call GET fapi.binance.com/fapi/v1/ticker/24hr (all coins, gzip, about 150-250 MB a day on mobile data; poll_sec in pd_config.py). No key, no order, never touches the bot.
- Volume of a short window = difference of the 24h turnover between two samples (approximate, under-counts; the spike is always against the coin's own last hour). No Open Interest (needs one call per coin: too heavy for a phone). 12 min of warm-up after every start (history is kept in memory only).
- Stages (pump side; dump is the mirror): WATCH (volume 2x+, 0.5% in 5 min, silent) -> START (volume 5x+, 1% in 5 min or 0.7% in 1 min, score 55+; the main alert, sound in the app) -> RUNNING (+3% since START, volume 1.5x+, one update per further +3%) -> WEAK (volume under 1x or 1.2% given back) -> END (weak 10 min, or no follow-through 45 min). One event per stage change, max 5 coins per side, one WATCH / START per coin per 30 min.
- Files: pd_config.py (settings, data folder), pd_store.py (day files), pd_feed.py (Binance poll + history), pd_scorer.py (numbers, score, stage candidate), pd_tracker.py (stages + events), pd_learn.py (outcomes, missed moves, daily tuner), pd_runner.py (the thread + live view), api/pd_route.py (routes), test/test_pd_scanner.py. Data: <data folder>/pumpdump/ (events/ outcomes/ missed/ reports/ tuner.json enabled.json pending.json), 60 days kept.
- Routes (token like the others): GET /api/pd/live, GET /api/pd/day?day=YYYY-MM-DD (IST day), GET /api/pd/learning, POST /api/pd/toggle {"enabled","auto_tune"}. Mounted in api_server.py unless env OWL_PUMPDUMP=0.
- SELF-LEARNING (simple rules, not AI): every START is checked after 15 / 30 / 60 min (REAL = moved 2%+ the right way inside 60 min). Coins with 3+ checked alerts and under 30% real get a score penalty (up to -15, 5 points a day), 70%+ real a bonus (+5). Once a day after 00:10 IST a report is written (reports/<day>.json). The start_vol threshold (default 5x, bounds 3-8, step 0.5) changes ONLY after 100+ checked alerts in 14 days, with the reason written in tuner.json; auto_tune can be switched off in the app. Missed moves (5%+ in 30 min, no alert) are saved in missed/.
### App (frontend)
- New tab "Pump/Dump" (AppRoute.pumpDump = screen 11; the bar in LITE is Home, Positions, Signals, Pump/Dump, More). screens/pump_dump_screen.dart, widgets/pd_widgets.dart, widgets/pd_learning_card.dart, providers/app_provider_pd.dart (fetches + pdPoll).
- The screen: status card with the on / off switch (off = no data is used) -> "Right now" two columns -> "Day by day" (day chips with up / down counts, "Main alerts only" filter, two columns of events, newest first, each START shows REAL / FAKE after the check, tap = every number) -> "What the scanner learned" (closed until opened).
- Alert in the app: main.dart's EXISTING 15 s tick calls provider.pdPoll() (one tiny call to this phone): a new START plays the order sound and puts a red dot on the Pump/Dump tab. It works only while the app is open (a notification while the app is closed needs a notification plugin = new APK dependency; not built).
### Honest limits
Nobody catches every pump; some alerts are fake. First days have more fake alerts (it needs about 100 checked alerts to learn). Dart was NOT compiled in the sandbox: the GitHub APK build is the first compile. Python parts were run offline with a synthetic market (pump + dump + quiet coins, spam check, outcome check, tuner check).

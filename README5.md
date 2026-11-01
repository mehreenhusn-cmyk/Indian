# README5 - BRAIN TRADER PLAN + HOW WE WORK (v24, 1 Nov 2026, after Part M5 + build fix)
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
| owner OK | TP2 is DONE inside BT-02 / BT-03 (the Brain decides it). PAPER ENTER / Confirm Paper Order (need a WRITE route) | - | ~150 |
Total about 3,000 lines in 11 parts (without the owner-OK parts).
## Open points
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
- Data quality chip on Brain Health says NOT CHECKED until the Part 85 data check exists.
- Old failing tests (not ours): test_v2_api 2, test_v2_brain_cards 1, test_v2_positions_ui 1.
- A COPY of README5 and of ALL 9 mock pictures lives in tools/notes/ (tools/notes/mockups/) (that folder passes every push filter). Keep both copies equal.
- Mock screens: 9 pictures in docs/mockups/ (restored from owl_Part90c.zip + 09) belong in docs/mockups/. If this folder is empty, the pictures must be put back from an older zip.

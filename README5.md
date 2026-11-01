# README5 - BRAIN TRADER PLAN + HOW WE WORK (v16, 1 Nov 2026, after Part L2)
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
| E1 | Exit study: same old trades, other exits (TSI turns, half of the gain given back, break-even stop), net / give-back / worst dip / both halves | v2_bt_exitlab.py + test | ~250 + ~120 |
| E2 | Exit Study screen | exit_study_screen.dart | ~230 |
| E3 | Exits that win run as BT-02 in SHADOW only (frozen version); owner OK only to move it to PAPER | v2_bt_sim.py edit, v2_bt_store version, test | ~120 + ~100 |
| E4 | Active trade labels (HOLD / PROTECT / CLOSE) use the same exit rule | v2_bt_detail.py, bt_trade_screen | ~60 |
| E5 | BT-01 vs BT-02 in the X1 comparison | v2_bt_compare.py edit | ~150 |
| M1 | System Health screen (mock 10): only real facts, rest NOT AVAILABLE | v2_sys_health.py, system_health_screen.dart | ~200 + ~250 |
| M2 | Month calendar like mock 16 on top of Day Compare | v2_bt_compare.py (+month), month_grid screen | ~40 + ~200 |
| M3 | Dashboard in the mock 11 / 15 style (Brain vs Bot 30 days, risk limit, recent strip) | dashboard screen | ~300 |
| M4 | Brain and Activity timeline (mock 13): bot trades next to Brain decisions | v2_bt_timeline.py, screen | ~120 + ~200 |
| owner OK | TP2, PAPER ENTER / Confirm Paper Order (need a WRITE route) | - | ~150 |
| later | split v2_data.py (402) and app_provider_positions.dart (379) | - | ~100 |
Total about 3,000 lines in 11 parts (without the owner-OK parts).
## Open points
- v191 = ONE zip (owl_PartL2) with the repo Indian-main (63) (README4 v186) + X1 + X2 + L1 + L2 merged: the newest file of each name wins. L2 Dart is new and has never been compiled: send the APK build error text if it fails.
- OWNER DECISION: 87c TP2 (real second target = new rule version BT-02, or a display-only price) and the PAPER ENTER button (needs a write route). Not built.
- 9 old test failures (test_v2_api 2, brain_ab 1, brain_cards 1, graduation 3, positions_ui 1, reports_route 1) fail the same on the owner's uploaded repo 61.
- v2_data.py (402) and app_provider_positions.dart (379) are over 350 lines: split later.
- Dart of Parts 86 to 90c has never been compiled. First real test: APK build. Send the error text if it fails.
- Data quality chip on Brain Health says NOT CHECKED until the Part 85 data check exists.
- Old failing tests (not ours): test_v2_api 2, test_v2_brain_cards 1, test_v2_positions_ui 1.
- A COPY of README5 and of ALL 9 mock pictures lives in tools/notes/ (tools/notes/mockups/) (that folder passes every push filter). Keep both copies equal.
- Mock screens: 9 pictures in docs/mockups/ (restored from owl_Part90c.zip + 09) belong in docs/mockups/. If this folder is empty, the pictures must be put back from an older zip.

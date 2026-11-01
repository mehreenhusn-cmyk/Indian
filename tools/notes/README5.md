# README5 - BRAIN TRADER PLAN + HOW WE WORK (v11, 1 Nov 2026, after Part 91b)
When the owner says "read README5 and continue", read this file first, then README4 (build log, top note = newest).

## How we work (owner rules)
- Small parts, every NEW file under 350 lines. Old files over 350 are not split unless a part has to touch them (v2_data.py is 396, split later).
- ONE cumulative zip per part: it holds every file of the earlier parts of this chat, so only the newest zip is downloaded. Zip folder = Indian-main/.
- Owner reads Roman English / Hinglish. Say plainly what was NOT run (Dart is never compiled here, nothing runs on the phone, the APK build is the first real test).
- No Termux commands for the owner: the zip is applied by tools/owl_auto.sh (BUILD 44), which pushes to GitHub.
- README5.md and docs/mockups/ (jpg, png, md only) are on the push allowlist since BUILD 44. If they are missing on GitHub, run: bash ~/owl_auto.sh pushcheck and send the output.
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
| X1 | 3-bot comparison + Take-All baseline (also the 'Current Bot vs Brain, same signals' box of mock 09) | v2_bt_compare.py | next |
| X2 | Day calendar + comparison screen | day_compare_screen.dart | todo |
| 87c | PAPER ENTER button, TP2, bot-vs-Brain | bt_signal_screen.dart, v2_bt_detail.py | todo |
| 64-65 | Final check + README close | README4.md | last |

## Open points
- Dart of Parts 86 to 90c has never been compiled. First real test: APK build. Send the error text if it fails.
- Data quality chip on Brain Health says NOT CHECKED until the Part 85 data check exists.
- Old failing tests (not ours): test_v2_api 2, test_v2_brain_cards 1, test_v2_positions_ui 1.
- A COPY of README5 and of the newest mock picture lives in tools/notes/ (that folder passes every push filter). Keep both copies equal.
- Mock screens: 9 pictures (8 old + 09 daily P&L) belong in docs/mockups/. If this folder is empty, the pictures must be put back from an older zip.

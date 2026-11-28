# README_PUMPDUMP - Pump / Dump + whole-app redesign (rebuilt 29 Nov 2026)

> The old README_PUMPDUMP.md was NOT in the owner's repo (zip 51), so this file is rebuilt from the chat history. Read it first when the owner says "pump dump ka kaam karo" or "redesign".
> Owner = Hussain. Reply in ROMAN script (simple English / Roman Hinglish), never Devanagari. Files + lines first, code only after "ok". MAX 400 LINES PER PART. ONE cumulative zip, paths start with `Indian-main/`. Tests: Not Run (owner rule), only syntax / bracket check. Never delete, only move to `frontend/no_use/`.

## 1. RESUME BOX
| Item | State |
|---|---|
| Last zip | owl_Part22.zip (29 Nov 2026, cumulative: Part A + 20 + 21 + 22) |
| Last Part done | Part 22 (design kit: OwlStatusTag, OwlEvidenceTag, OwlCheckRow, OwlScreenIntro; hero card gets unit + delta + tabular big number). Before: 21, 20, A |
| Applied by owner? | Part 21 files are in the phone repo (86 in the list, dry run ok on 29 Nov 2026). The real move command is NOT run yet. |
| Next | Part 23 (top bar + nav), after the owner's "ok" |
| Dart compile | NOT done (the GitHub build is the first compile). Python: py_compile only |

## 2. What the owner actually uses (his words, short)
1. ONLY the current crypto bot (its strategy) + the Pump / Dump tab. Everything else (Brain, AI, Dual Bot, Sniper, Vision, Study Lab, Diagnostics) is OFF and must not be on screen.
2. Pump / Dump exists to catch the coin BEFORE it pumps and BEFORE it dumps, with the indicators read the right way (TSI, Z, EMA, SD bands).
3. The whole front end must be clear at first sight: result cards, user friendly, easy words. How many tabs, what each shows, what a signal / alert says and what happens after it. Claude may plan it freely.
4. Use the files already in the repo, beautify them. The 12 reference images are ideas only, NOT to be copied one to one. Brain screens in them are NOT wanted.
5. Idea for later: help the strategy learn in a self-learning way (sideways / no-trade state). Report only, never changes live trading.

## 3. Part A (BUILT 29 Nov 2026): the PORTAL bug
Symptom (owner screenshots): PORTAL showed "CHAL RAHA / Abhi bhi upar chal raha hai, 15 min me -1.8%" while its 15m chart had already crashed from about 0.0576 to 0.01615.
Causes found in the code:
| # | Cause | File |
|---|---|---|
| 1 | "Pehle se chal rahe" = coin sits in the Binance 24h top-10 (or was there in the last 180 min). The 24h % stays big after a dump, so the card stayed. The live trend was never checked | backend/pd_rank.py `_running` |
| 2 | Only 2 tags existed: CHAL RAHA, THAK RAHA. No "ended" tag. THAK needs 2 of 4 weak signs | pd_rank.py, pd_movers_widgets.dart |
| 3 | The app sentence did not look at the sign of the 15 min move | pd_movers_widgets.dart |
Fix: ONE place decides the tag, `Rank._state()` in pd_rank.py, result in `card["state"]` = new | running | tiring | ended. The app only reads `state` (function `pdMoverState`), it never builds a tag itself, so a card and its chart cannot disagree any more.
Rule for ENDED (all numbers in pd_config.py, change them there):
| Setting | Value | Meaning |
|---|---|---|
| end_min_move | 5.0 | the last-hours move (base to peak) must be at least 5% before "give back" counts |
| end_giveback | 0.5 | ended when 50% of that move is given back (GUESS of Claude, not proven, tune from the study) |
| end_against15 | 3.0 | also ended when the coin moves 3% against the side in 15 min AND already gave back 25% |
| ended_keep_min | 360 | an ended coin stays in the folded list "Khatam ho gaye" for 6 h, then disappears from the app (nothing is deleted from files) |
Peak / base = kline 15m last 24 closed candles (6 h), else 1h (24 h), joined with the feed's own 95 min (`hi24` / `lo24` added in pd_tsi.analyse). Hysteresis: once ended, a coin stays ended until it gets back under 60% of the give-back limit.
Ended coins are NOT added to the chance statistics (they would pollute "how often a running coin works"). NOT built in Part A: writing ended coins to the study log (do it in Part 34).
Arithmetic check on the PORTAL numbers (not a test run): move about 264%, give-back about 98% -> ended.

### Part A files
| File | Edit / New | Lines changed (diff, exact) |
|---|---|---|
| backend/pd_rank.py (212 -> 258) | edit | 58 |
| backend/pd_tsi.py | edit | 2 |
| backend/pd_config.py | edit | 4 |
| frontend/lib/widgets/pd_movers_widgets.dart (233 -> 267) | edit | 50 |
| README_PUMPDUMP.md, CLAUDE_HANDOFF.md, README4.md | docs | - |

## 3b. Part 20 (BUILT 29 Nov 2026): dead files to `frontend/no_use/`
How the 38 were found: every Dart file reachable from `frontend/lib/main.dart` through import / export / part was followed. 299 of 337 are reachable, 38 are not = 11,711 lines (ai_* screens and cards, dashboard_cockpit, system_header, owl_metric, owl_badge, owl_terminal_logo and more; full list in `tools/no_use_list.txt`). Checked after a move on a copy: 299 files left in lib, 0 broken imports.
The 94 files that only the 6 hidden tabs (Brain, Vision, Dual Bot, Sniper, Study Lab, Diagnostics) use are NOT moved yet: that is Part 21 (it needs 3 link edits).
IMPORTANT: the auto-deploy watcher (tools/owl_auto.sh, sync_repo) only adds files from a zip and runs `git add -A`, it never removes old files. So a zip cannot move a file. `tools/owl_no_use_move.sh` does `git mv` in `~/Indian-main` on the phone and pushes. `dry` as first word = only show.
| File | Edit / New | Lines |
|---|---|---|
| tools/owl_no_use_move.sh | new | 38 |
| tools/no_use_list.txt | new | 38 (paths under frontend/lib/) |
| frontend/no_use/README.md | new | 5 |
| analysis_options.yaml | edit | +2 (exclude `frontend/no_use/**`) |
| 38 Dart files | moved by the script, content unchanged | 0 |
Not verified: the script ran on a fake git repo only (move + second run ok, push failed there on purpose because it had no origin). It was not run on the phone.

## 3c. Part 21 (BUILT 29 Nov 2026): the 6 hidden screens unlinked, 48 more files for `no_use`
The old plan said "94 files, 3 edits". The import graph says otherwise: unlinking the 6 screens in main.dart makes 47 files dead (+ tab_page.dart = 48, 10,732 lines: brain_* screens, vision_*, study / lab / filter / indicator / radar / wickstudy / setup screens, ai_chat_popup, verdict_carousel ...). The other ~58 (dual_bot, sniper_*, diagnostics, brain widgets) stay alive because `dashboard_screen.dart` and `owl_status_header.dart` still import brain_strip, tag_lab_tile and diag_section (hidden by kLite but still imported). Cutting those needs edits in the dashboard, which Part 24 rewrites anyway, so they move there.
app_routes.dart needs NO edit: it is pure Dart (no screen import) and the screen numbers must stay. more_screen.dart needs no edit now (it imports none of the 6); its tiles are Part 32.
| File | Edit / New | Lines |
|---|---|---|
| frontend/lib/main.dart | edit: 6 imports + tab_page import out, 6 `_screens` slots = `SizedBox.shrink()` | 634 -> 627 |
| tools/no_use_list.txt | +48 paths (now 86) | +48 |
| 48 Dart files | moved by the same script, content unchanged | 0 |
After the move: 251 Dart files in lib, all reachable from main.dart, 0 broken imports (checked with an import-graph script, not a compiler).

## 3d. Part 22 (BUILT 29 Nov 2026): design kit, only what was missing
The kit from Parts 8 to 19 already has hero card, stat tile, section header, chips, empty state, shimmer. Part 22 adds only what the new mockups need and the kit lacked. Use these in Parts 23 to 35, do NOT write a new tag / checklist / heading in a screen.
| Widget (file) | Use it for | Lines |
|---|---|---|
| OwlStatusTag (owl_status_tag.dart) | every state word: CHAL RAHA, ULTA HO GAYA, PAPER ... 11 px, pill, tone good / bad / warn / muted or an exact colour | NEW 124 (all 4 widgets) |
| OwlEvidenceTag (same) | how much proof stands behind a number, from the SAMPLE COUNT only: Unavailable / Not enough data / Early look / Enough samples, shows "7 of 30". It never says "works" | |
| OwlCheckRow (same) | one checklist line (yes / no / Unavailable) for the alert detail and Home status | |
| OwlScreenIntro (same) | screen title + ONE plain line "what this screen shows" + optional (i) (glossary = Part 33) | |
| OwlHeroCard (owl_hero_card.dart) | new `unit` (small USDT), `delta` + `deltaTone` (one small coloured line), big number = AppTypography.heroXL (tabular mono, 34 px) | 106 -> 123 |
| OwlStatTile (owl_kit_parts.dart) | number now AppTypography.number (tabular) | +1 |
| PdMoverCard (pd_movers_widgets.dart) | the tag was 9 px, now OwlStatusTag 11 px | |
Visible change on the phone: the big number on Home, Results and India is now the tabular mono style with a unit, and the Pump / Dump card tag is readable. Everything else comes with Parts 23 to 35.
Not verified: Dart not compiled; brackets and imports checked by script only; how it looks on the phone is not seen.

## 4. PLAN (owner asked a plain table: file | what | lines). Lines = estimate until the file is read.
| Part | File(s) | Edit / New | What | ~Lines |
|---|---|---|---|---|
| 20 | 38 dead files (not reachable from main.dart) + tools/owl_no_use_move.sh + tools/no_use_list.txt + analysis_options.yaml | move only + 2 new tools files, 1 edit | BUILT. Watcher cannot delete, so a script does `git mv` on the phone (nothing deleted) | 0 Dart lines |
| 21 | main.dart (634) + tools/no_use_list.txt | 1 edit (main.dart ~13 lines), list +48 | BUILT. 6 imports out, the 6 slots in `_screens` became `SizedBox.shrink()` (screen numbers stay, app_routes.dart needs NO edit), 48 files (10,732 lines) listed for no_use | 13 |
| 22 | widgets/owl_status_tag.dart (NEW 124), owl_hero_card.dart (106 -> 123), owl_kit_parts.dart (92 -> 93), pd_movers_widgets.dart (tag now OwlStatusTag, 9 px -> 11 px) | 1 new, 3 edit | BUILT. app_theme.dart, owl_card.dart, owl_empty_state.dart need NO edit: palette, OwlChip, OwlEmptyState, OwlShimmer already do the job (kit existed since Parts 8 to 19) | 170 |
| 23 | main.dart + nav file | 2 edit | top bar covers the page title, bottom label "Pump/" cut, plain status words | 300 |
| 24 | dashboard_screen.dart (424), owl_status_header.dart, NEW home_status_section.dart | 2 edit, 1 new | Home: Status + Money (today net, gross, fees). ALSO drop brain_strip / tag_lab_tile / diag_section from the dashboard: then ~58 more files (dual_bot, sniper_*, diagnostics_*, brain widgets) become dead -> `no_use` (system_health_screen.dart and what it needs STAY for Part 32) | 380 |
| 25 | dashboard_screen.dart, NEW home_risk_section.dart | 1 edit, 1 new | Home: Risk, Market, Quick links, "next action" | 350 |
| 26 | pd_movers_widgets.dart, pd_cool_widgets.dart (268) | 2 edit | alert card: strength, age, evidence, not an order | 380 |
| 27 | pd_movers_widgets.dart, pd_widgets.dart (340) | 2 edit | alert detail: indicator checklist, time stamps | 380 |
| 28 | widgets/candle_chart.dart (2545) | 1 edit, small | candles big, SD bands light, scale follows candles | 200 |
| 29 | signals_screen.dart (610), signals_alerts_screen.dart (96) | 2 edit | Signals: one card = one clear sentence | 380 |
| 30 | positions_screen.dart (143) + detail | 2 edit | Positions | 300 |
| 31 | results_screen.dart (248) | 1 edit | Results + month calendar | 350 |
| 32 | more_screen.dart, system_health_screen.dart (121) | 2 edit | More hub + System Health, real numbers only | 300 |
| 33 | NEW glossary.dart, NEW how_to_read_screen.dart + 3 edit | 2 new, 3 edit | one line "what this screen shows" + (i) meaning of EMA / SD / TSI / strength + "How to read this app" page | 400 |
| 34 | pd_study.py (edit), NEW pd_state.py | 1 edit, 1 new | sideways / no-trade label, observe only; log ended coins | 350 |
| 35 | 2 files | 1 edit, 1 new | Learning report screen: Not enough data / Early look / Could be luck | 380 |
Total about 5,300 lines, 17 Parts incl. A. Brain screens (old plan Part 28) are DROPPED: Brain goes to `no_use/`.

## 5. Open questions for the owner
| # | Question | Now |
|---|---|---|
| 1 | "Ended" limit 50% give-back OK, or 30% / 70%? | 50% (guess) |
| 2 | Taiyari me counts as "worked" when? | guess: 3% move in 2 h |
| 3 | Cooling WARNING counts as "worked" when? | guess: 10% fall in 48 h |
| 4 | App words: plain English or Roman Hinglish? | mockups were English; old screens are Hinglish |
| 5 | Old README_PUMPDUMP.md is missing in the repo; old README to `docs_old/` (move, not delete) | not done |

## 6. Owner to-do
1. Push owl_Part22.zip (delete every older owl_Part*.zip from Download first: the watcher applies zips in NAME order; Part 22 holds A, 20 and 21 too). BEFORE that, run the real move once: `bash ~/Indian-main/tools/owl_no_use_move.sh` and wait for "pushed".
2. After the push: `bash ~/Indian-main/tools/owl_no_use_move.sh dry` (shows 86 lines), then `bash ~/Indian-main/tools/owl_no_use_move.sh` (moves + pushes). Then restart (`owloff`, `owlon`), open Pump / Dump: a coin that already reversed must sit in "Khatam ho gaye", not in "Pehle se chal rahe hain".
3. If the GitHub build fails, send only the line the log names.
4. Revoke the old Telegram bot token in @BotFather (still in backend/main.py line 22).

## 7. Not verified (honest)
Dart not compiled. The Python was only syntax-checked. The 50% / 3% limits are guesses. How the card looks on the phone is not seen yet.

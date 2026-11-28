# README_PUMPDUMP - Pump / Dump + whole-app redesign (rebuilt 29 Nov 2026)

> The old README_PUMPDUMP.md was NOT in the owner's repo (zip 51), so this file is rebuilt from the chat history. Read it first when the owner says "pump dump ka kaam karo" or "redesign".
> Owner = Hussain. Reply in ROMAN script (simple English / Roman Hinglish), never Devanagari. Files + lines first, code only after "ok". MAX 400 LINES PER PART. ONE cumulative zip, paths start with `Indian-main/`. Tests: Not Run (owner rule), only syntax / bracket check. Never delete, only move to `frontend/no_use/`.

## 1. RESUME BOX
| Item | State |
|---|---|
| Last zip | owl_PartA.zip (29 Nov 2026) |
| Last Part done | Part A (PORTAL bug: pump that already reversed was shown as "CHAL RAHA") |
| Applied by owner? | no, waiting for the push |
| Next | Part 20 (move 38 dead files to `frontend/no_use/`), after the owner's "ok" |
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

## 4. PLAN (owner asked a plain table: file | what | lines). Lines = estimate until the file is read.
| Part | File(s) | Edit / New | What | ~Lines |
|---|---|---|---|---|
| 20 | 38 dead files (no import anywhere) | move only | to `frontend/no_use/` (outside lib, not compiled) | 0 |
| 21 | main.dart, app_routes.dart, more_screen.dart (175) | 3 edit | move the 94 files of the 6 hidden tabs (Brain, Vision, Dual Bot, Sniper, Study Lab, Diagnostics), remove links | 60 |
| 22 | theme/app_theme.dart (281), owl_metric, owl_hero_card, owl_badge, NEW owl_status_tag.dart | 4 edit, 1 new | colours, big-number style, card, chips, status tag | 260 |
| 23 | main.dart + nav file | 2 edit | top bar covers the page title, bottom label "Pump/" cut, plain status words | 300 |
| 24 | dashboard_screen.dart (424), NEW home_status_section.dart | 1 edit, 1 new | Home: Status + Money (today net, gross, fees) | 380 |
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
1. Push owl_PartA.zip (delete the older owl_Part*.zip from Download first: the watcher applies zips in NAME order).
2. Restart (`owloff`, `owlon`), open Pump / Dump: a coin that already reversed must sit in "Khatam ho gaye", not in "Pehle se chal rahe hain".
3. If the GitHub build fails, send only the line the log names.
4. Revoke the old Telegram bot token in @BotFather (still in backend/main.py line 22).

## 7. Not verified (honest)
Dart not compiled. The Python was only syntax-checked. The 50% / 3% limits are guesses. How the card looks on the phone is not seen yet.

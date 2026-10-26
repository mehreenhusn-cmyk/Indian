# Owl Terminal - MASTER NOTES (the ONLY notes file in this repo)

OWL MASTER NOTES v17 - last updated: 27 Oct 2026

Crypto paper-trading app (Flutter) + Python backend. Dual Bot v1 collects trades. Smart Brain learns on the side, paper only.

## 0. FOR EVERY CLAUDE / READER - do this every time
1. Read this whole file first. It is the single source of truth. Do NOT create other README / NOTES / CHANGES / status files.
2. Check section 4 (ROAD AHEAD). If a "start when" data condition is reached, tell the owner plainly: "Data is ready for step X. Shall I build it?" Build only after his "ok".
3. Owner way of working: tell number of files + lines first, start only after "ok", build in parts, ONE zip with only changed files. He updates from Termux in one shot. Simple English or Hinglish, short replies.
4. After ANY work: update this file in the same zip: tick the step in section 4, add a row to section 3 (DONE) and section 10 (change log), change the date above. Never leave this file stale.
5. Flutter cannot be compiled in Claude's sandbox. Say so, and ask the owner to send any build error.
6. NAMING (owner asked, so he never gets confused): "Round 1" = old Parts 1, 2, 3 (finished and already pushed by the owner). All new work is Part A, Part B, Part C ... and steps inside a part are A1, A2, A3 / B1, B2 ... Never reuse old numbers. Name the zip after the part, e.g. owl_A1.zip.
6b. HOW TO TALK TO THE OWNER (he said it all bounces off his head otherwise): at the end of EVERY reply give 2-4 numbered steps in very simple Hinglish: (1) what to download, (2) what to paste in Termux, (3) what he should see, (4) what to send back if it looks different. Never ask him to run something that is not in those steps. Explain any new word in one line. If nothing is needed from him, say "abhi kuch nahi karna".
7. EVERY TIME a zip is delivered, end the reply with the ONE copy-paste Termux command from section 11 (with the right zip name and commit message filled in). The owner just copies, pastes, done.
8. SAVE EFFORT: do NOT scan the whole repo. Open section 12 (CODE MAP), go straight to the files listed for the feature, read only the function you need. Line numbers there are approximate (they drift): search by function name.
9. KEEP FILES SMALL: new backend modules under ~250 lines, one job each; never add big blocks into api_server.py, main.py or smart_brain.py if a new small file can hold it (smart_brain.py only gets a thin hook, like the other brain_*.py files). Small files = small zips = small cost to read next time. If you add or move a feature, update section 12 in the same zip.
10. OWNER ORDER (27 Oct): N2, Parts A, B, C, D, E (E1-E5), F1, F2, F3 are DONE (owner applied up to F2 on 27 Oct; F3 is the newest zip). Next, one at a time and only when the owner says: G1, G2 (they wait for data, see section 4). F/G wait for data. B3 waits for data (see section 4). READY CHECK on 27 Oct (live): 1 of 4 true (only "what if the bot had listened" is true; exit hit-rate 50% < 60%; trust not earned; luck untestable; own book 0 finished trades) = do NOT build G1/G2 yet. B3: Timing Sync best = same candle (+1.33 USDT/trade, 61 trades), worst = Z first then Main 1-2 candles (-4.98, 27 trades); compare again about 30 Oct (needs 3+ days stable). If own book still shows 0 finished trades on 28 Oct, find out why before anything else.
11c. DEPLOY RULE (27 Oct): the owner NEVER kills processes by hand. Phone side is tools/owl_auto.sh v5, see section 13. If you change how the backend starts workers, change owl_auto.sh in the same zip.
11b. ZIP RULE: each new zip is CUMULATIVE for the files changed since the owner last confirmed applying (the owner often applies several zips at once), always with README.md. Say in the reply which earlier zips it already contains.

## 1. OWNER RULES (strict)
- Do NOT touch: dual_lab.py, tag_lab.py, dual_lab_data.json, Dual Bot trading / exits. Dual Bot v1 stays in full explore mode (no filter, no skip, no block). Brain only READS its data (read-only) and writes only its own json files.
- Only two indicator families: Main chart (EMA50 + SD bands) and Z pane + TSI. No third indicator (no ADX, no Hurst).
- Paper only. New behaviour is OFF, report-only or "Brain own trades only" until the owner enables it. No torch / heavy RL. SQLite / WebSocket not yet (section 7).
- Trading day everywhere = 5:30 AM IST (00:00 UTC). BTC has its own margin and totals, never added to the alt coins.

## 2. WHAT THE SYSTEM IS
- Dual Bot v1 = paper bot reading both indicators, taking every signal (500-600 trades a day), saving trades, tags and a setup book in dual_lab_data.json.
- Smart Brain = side layer. Scores setups (clean score, Main-vs-Z divergence, look-alike win %), trust meter, luck test, risk numbers, exit advice (shadow), "what if the bot had listened", sideways report, retest report, and its OWN paper trades (smart_brain_own.json).
- Brain own trades: scans TODAY's top-10 gainers + top-10 losers (20 coins, no BTC) on 15m every 5 min. Stage by finished own trades: learning (0-99, loose) -> medium (100+) -> quality (300+, strict). Max 40 new own trades a day, max 20 open. Learns lessons from its own results: a setup mix that lost is not repeated, one that worked is repeated, newest trades weigh more.
- Owner's big goal: make the Brain so strong that it can trade a small real amount ($10-20) by itself and make profit, using only the two indicators. Section 5 says when that can even be considered.

## 3. DONE (in the repo; rows R1-1 to R1-3 below are Round 1 = old Parts 1-3, applied by the owner on 27 Oct)
| # | What | Main files |
|---|---|---|
| 1-3 | Brain "what it thinks now", Dual Bot screen tabs, luck test, risk numbers, rolling memory | smart_brain.py, smart_brain_view.dart, dual_bot_screen.dart |
| 4-6 | Shared card design, Dashboard, Signals and Alerts look | owl_card.dart, dashboard_screen.dart, signals_screen.dart |
| 7, 13 | Brain learns exits (FULL TP / HALF TP / HOLD), advice only | brain_exit.py, brain_exit_pick.py |
| 9 | "What if the bot had listened?" report | brain_follow.py |
| 10 | Brain skip gate: built, app switch REMOVED on purpose, default OFF | smart_brain.py, test_brain_gate.py |
| 11 | Tab keeps last reply, fast start, trust needs 100 judged trades | dual_bot_screen.dart, smart_brain.py |
| 12 | Brain own paper trades (separate book) | brain_own.py |
| A | Sideways report (Trending / Mixed / Sideways, cost in USDT) | smart_brain.py |
| 14-17 | Now / Opportunities / Performance / Simple tabs | dual_summary_strip.dart, opportunities_tab.dart, performance_tab.dart, simple_tab.dart |
| V2-1..3 | Price Action layer, Volume layer, join report (report only; join needs 100 trades + 10 days) | pa_layer.py, vol_layer.py, layers_join.py |
| R1-1 | Brain own trades now loose + today's coins + auto-learning lessons + stages + daily limit (27 Oct) | smart_brain.py, brain_own.py |
| R1-2 | Retest report: two numbers apart (came back / never came back) + Trending / Mixed / Sideways split (27 Oct) | smart_brain.py, smart_brain_view.dart |
| R1-3 | Simple tab: LOCKED / FLOATING / NET boxes + Brain dislike %; "Old setups read" bar can no longer say "5000 of 60" (27 Oct) | simple_tab.dart, smart_brain_view.dart |
| A1-A3 | Honest trust bar (never 150 of 100), header says MAIN bot P&L, Performance tab without BTC (BTC own line), Simple tab 'which signal type pays' card + open rows say 'opened 5m ago' | smart_brain_view.dart, live_ticker_bar.dart, performance_tab.dart, simple_tab.dart, dual_bot_screen.dart, smart_brain.py |
| N1 | This single notes file; old notes removed with tools/clean_old_notes.sh (27 Oct) | README.md |
| D1-D2 | Exit style + hold time per setup mix (same Timing Sync mixes): best of the 9 exit rules vs the bot's own exit, winners vs losers minutes, share of fast winners, older-vs-newer half check, up to 3 'clearly better' lines (needs +3 points). Brain tab card 'EXIT STYLE AND HOLD TIME'. Report only (27 Oct, zip owl_D = cumulative: also contains N2, B, C) | brain_tp_hold.py, test_brain_tp_hold.py, smart_brain.py (hook), smart_brain_view.dart |
| C1-C2 | READY CHECK card on top of the Brain tab (trust, luck, what-if, exit hit-rate = the 4 gates; retest, timing sync, own stage = info rows; headline says if Brain skip / exit trail can be asked about). Retest card headline 'WAITING IS BETTER/WORSE BY X USDT' + total of waiting vs total at the signal + honest note about skipped signals (27 Oct, zip owl_C = also contains N2 and B) | brain_ready.py, test_brain_ready.py, smart_brain.py (hook), smart_brain_view.dart |
| F3 | Week report card + time-of-day cap (27 Oct, zip owl_F3): brain_week.report(own) = last 7 trading days (trades, win %, USDT, best/worst day) + 4 UTC blocks of 6 hours (same blocks as the tag lab); blocked(own, now_ms, opened) caps new own trades per day in a block that loses in both halves (needs 7 days + 300 own trades). Hooks: brain_own.open_from, summary key 'week'. Brain tab card 'WEEK REPORT CARD' inside 'More reports' (now 18). Own book only | brain_week.py, test_brain_week.py, brain_own.py, smart_brain_view.dart |
| F2 | Retest own book (27 Oct, zip owl_EFG): when an own trade finishes, brain_own.settle asks brain_retest.twin() what waiting for the EMA50 retest would have made (same fill rule and waits 3/6/12/24 as Dual Bot, same exit). Stored as t['rt']. brain_retest.report(own) compares retest book vs normal own book in USDT, best wait, older vs newer half. Brain own card shows WAITING IS BETTER / WORSE / EARLY HINT / NOT STEADY. Measure only: opens nothing. Old own trades have no t['rt'] and are not counted; a twin still open at that moment is skipped, not retried | brain_retest.py, test_brain_retest.py, brain_own.py, smart_brain_view.dart |
| E5 | One look for every screen: spacing tokens cardGap 12 to 10 and cardPad 14 to 12 (Dashboard, Positions, Signals, Alerts, Dual Bot all read them), AppButtons (shape, 40px height, label) applied to Elevated / Filled / Outlined / Text buttons in both themes. Screens themselves untouched, nothing removed (27 Oct, zip owl_EF) | app_spacing.dart, app_theme.dart |
| F1 | Sideways self-rule for the Brain's OWN trades only (27 Oct, zip owl_EF): brain_side.state() / blocked(); open_from hook; summary key side_rule; Brain own card shows 'SIDEWAYS LIMIT ON/OFF' + plain sentence + skipped today. Dual Bot and main bot untouched | brain_side.py, test_brain_side.py, brain_own.py, smart_brain_view.dart |
| E3-E4 | E3: one-line badges on every trade row (clean / unclear / dislike + agree / mixed / disagree, REAL / FAKE once finished) via DualTradeCard.badgeRow, used in the Simple tab rows and the Dual trade card; tighter rows and card. E4: OwlDensity(compact) wraps the Dual Bot tab body so every OwlSectionCard gets smaller padding/gap; Brain tab shows Ready, Now, Timing, Exit style, Trust, Own trades and folds the other 17 reports behind 'More reports' (27 Oct, zip owl_E = cumulative E1-E4, 7 files) | dual_trade_card.dart, simple_tab.dart, owl_card.dart, dual_bot_screen.dart, smart_brain_view.dart |
| E1-E2 | Header bar 40px to 36px, tighter gaps, flatter pills, smaller latency number (no item removed). Dual Bot tabs: boxed chips replaced by underline pills; tab body fades between tabs via _segBody() + AnimatedSwitcher (27 Oct, zip owl_E12, only 3 files, owl_D already applied) | live_ticker_bar.dart, dual_bot_screen.dart |
| N2 | Section 12 CODE MAP (which feature lives in which file) + rules 8-10 (27 Oct) | README.md |
| B1-B2 | Timing Sync report (Same candle / Z first / Main first 1-2 and 3-5 candles / Z only / Main only / opposite: count, win %, USDT, TSI with/against, sideways, older-vs-newer half check, BTC left out), a 'deep clean candidate' measure, up to 10 plain lessons. Brain tab card 'TIMING SYNC - WHO SPOKE FIRST' (27 Oct, zip owl_B) | brain_lessons.py, test_brain_lessons.py, smart_brain.py (hook), smart_brain_view.dart |

## 4. ROAD AHEAD (Part A, B, C ... in this order; start a part only when its "start when" is true AND the owner says ok)
OWNER ORDER NOW: Parts A, B, C, D, E (all 5), F1, F2, F3 are DONE. F1, F2 and F3 are built with a data gate (no limit or verdict until their numbers are reached). Next G1 / G2, only when READY CHECK says so (section 6) and the owner says ok. Still open from B: B3 (Brain own trades prefer deep clean setups) needs the Timing Sync numbers to stay stable for 3+ days; nothing else of B is missing.
Sources: owner's 3 prompt files (Brain strong modules, Owl FINAL master, FINAL FORM all problems) and his phone screenshots of 27 Oct.
| Part | What | Files | Lines | Start when | Status |
|---|---|---|---|---|---|
| A1 | Honest numbers: trust bar shows "100 of 100, earned check pending" (never 150 of 100); top header label says it is the MAIN bot's P&L (it showed -139 while Dual Bot locked was -744 = confusing) | smart_brain_view.dart, live_ticker_bar.dart | ~35 | NOW | DONE 27 Oct (zip owl_A) |
| A2 | Performance tab: BTC left out of the alt curve (it is now mixed in: 479 trades vs 464 on the Today card, equity -892 = -744 alts + -148 BTC). BTC shown as its own line | smart_brain.py, test_brain_perf.py, performance_tab.dart | ~40 | NOW | DONE 27 Oct (zip owl_A) |
| A3 | Simple tab: always-visible mini summary "Both same candle / Z only / Main only" (data shows Both = green, Main only = worst) + check every open-trade row shows age (5m / 1h) | simple_tab.dart, dual_bot_screen.dart | ~65 | NOW | DONE 27 Oct (zip owl_A) |
| B1 | Indicator Timing Sync report: SAME candle / Z first then Main (1-2 or 3-5 candles) / Main first then Z / Z only / Main only, with count, win %, USDT, TSI state, sideways; plus 5-10 plain "how to use both indicators" lessons; defines "deep clean setup" from data. Uses the existing "order" tag, Dual Bot untouched | brain_lessons.py (new), test_brain_lessons.py (new), smart_brain.py | ~230 | NOW (Dual data is enough) | DONE 27 Oct (zip owl_B) |
| B2 | Brain tab card for B1 (one strong block, plain words) | smart_brain_view.dart | ~110 | after B1 | DONE 27 Oct (zip owl_B) |
| B3 | Brain OWN trades softly prefer "deep clean" setups | brain_own.py, smart_brain.py, test | ~50 | B1 numbers stable for 3+ days | WAIT FOR DATA |
| C1 | READY CHECK card on top of Brain tab: trust, luck, what-if, exit hit-rate, retest, timing sync, own stage + trades to next stage | smart_brain_view.dart, smart_brain.py | ~110 | after A | DONE 27 Oct (zip owl_C) |
| C2 | Retest card headline: "Waiting is better by +X USDT" with best wait, and the honest note that part of it is skipping signals | smart_brain_view.dart | ~30 | with C1 | DONE 27 Oct (zip owl_C) |
| D1 | TP + hold time per setup mix (best exit, bars held in wins vs losses, fast vs slow). Report only | brain_tp_hold.py (new), test_brain_tp_hold.py (new), smart_brain.py | ~200 | NOW | DONE 27 Oct (zip owl_D) |
| D2 | Brain tab card for D1 | smart_brain_view.dart | ~75 | after D1 | DONE 27 Oct (zip owl_D) |
| E1 | Modern look 1: one compact header row (CRYPTO/INDIA, latency, PAPER, TF, P&L, power), less padding | live_ticker_bar.dart | ~80 | after A, B | DONE 27 Oct (zip owl_E12) |
| E2 | Modern look 2: Dual Bot tabs as clean segmented / underline pills, smooth switch | dual_bot_screen.dart | ~100 | after E1 | DONE 27 Oct (zip owl_E12) |
| E3 | Modern look 3: Simple tab polish, tighter trade rows with one-line badges (clean / agree / dislike / FAKE) | simple_tab.dart, dual_trade_card.dart | ~150 | after E2 | DONE 27 Oct (zip owl_E) |
| E4 | Modern look 4: Now / Opportunities / Learned density, no tall empty padding, secondary Brain cards collapsible | dual_bot_screen.dart, smart_brain_view.dart, owl_card.dart (OwlDensity) | ~200 | after E3 | DONE 27 Oct (zip owl_E) |
| E5 | Modern look 5: same tokens and buttons on Dashboard, Positions, Signals, Alerts (nothing removed) | app_spacing.dart, app_theme.dart (shared tokens + button theme; the 4 screens use them) | ~250 | after E4 | DONE 27 Oct (zip owl_EF) |
| F1 | Sideways self-rule: Brain OWN trades only, fewer own trades in sideways when own book loses there | brain_side.py (new), brain_own.py (hook), smart_brain_view.dart, test_brain_side.py (new) | ~110 | 100+ own finished trades AND 30+ in sideways (about 4-7 days) | DONE 27 Oct (zip owl_EF), built with a gate: the rule stays OFF until 100+ own finished AND 30+ sideways AND sideways lost in both halves; then max 5 new sideways own trades a day |
| F2 | Retest own book (separate file, compared with normal own book) | brain_retest.py (new), brain_own.py (hook in settle + summary), smart_brain_view.dart, test_brain_retest.py (new) | ~200 | 100+ signals that came back AND same sign in older and newer half (about 7-10 days) | DONE 27 Oct (zip owl_EFG), built as a paper twin with a gate: shows numbers from 10 trades, gives a verdict only after 100+ came back AND both halves agree |
| F3 | Weekly report card + time-of-day cap for own book | brain_week.py (new), brain_own.py (hook), smart_brain_view.dart, test_brain_week.py (new) | ~190 | 7+ days of own trading and 300+ own finished trades | DONE 27 Oct (zip owl_F3), built with a gate: report card shows from day 1, the time-of-day limit switches on only after 7+ days AND 300+ own finished trades AND a 6-hour UTC block with 30+ trades that lost in both halves; then max 3 new own trades a day in that block |
| G1 | Brain skips bad signals in the main bot (Step C of section 8) | 2-3 files | ~100 | READY CHECK 1+2+3 true (section 6) | WAIT FOR DATA |
| G2 | Brain exit advice trails the stop (Step D of section 8) | 2 files | ~120 | READY CHECK 4 true | WAIT FOR DATA |
| - | Per-coin memory | - | - | NOT PLANNED: top-10 coins change every day, so it would be noise | DROPPED |
Totals: A ~125 lines, B ~390, C ~140, D ~275, E ~780 (5 small zips, because Flutter cannot be compiled here), F ~500 later.
Recommended order: A, B, C, D, E, then F and G as data arrives.

## 5. WHAT THE LIVE NUMBERS SAY (27 Oct screenshots - keep visible, do not hide)
- Closed trades lose, open trades float high: about -744 locked vs +3,600 floating, 18% win, 121 open. Floating is NOT money. Judge the system by LOCKED over many days, not by the floating number.
- By signal type: Both indicators on the SAME candle = positive (+81, 65 trades). Z only = -224 (197 trades). Main only = -601 (202 trades, the worst). This is the strongest clue for the Brain: learn to wait for both. Part B measures it properly.
- Sideways cost about 955 USDT. Retest wait beats entering at the signal in every TSI split, but the waiting totals are still negative; part of the gain is only from skipping signals that never came back.
- Brain dislikes 55% of the latest 40 trades; 0% "good", clean score about 36. That is the data (many dirty / sideways setups), not a bug.
- Known confusion: the top header "TODAY P&L" is the main bot, not Dual Bot (fixed in A1). Performance tab includes BTC, Today card does not (fixed in A2).
- PATH TO REAL MONEY ($10-20), gates proposed by Claude, owner decides. Paper profit does not promise live profit (fees, slippage). First: (1) Brain stage "quality" and its OWN book has 300+ finished trades, positive after fee, positive in both the older and newer half; (2) trust "earned" and luck "Looks real" for 7+ days; (3) weekly cards positive 2 weeks in a row and worst-case drop acceptable for $10-20; (4) only then a SEPARATE decision. Live-order code does not exist in this repo; it would be built last, tiny size, hard daily loss stop, off switch.

## 6. READY CHECK (Brain tab)
1. TRUST METER says "earned" (needs 100 judged trades).
2. Luck test says "Looks real".
3. "What if the bot had listened?" has 30+ judged trades and SKIP DISLIKED beats TAKE ALL.
4. Exit advice card: 10+ checked opinions and hit-rate above 60%.
1+2+3 true = ask the owner about Brain skip (S-C). 4 true = ask about S-D.
Note: "0% good, clean score 30, 12-18% win" on the phone is DATA (many dirty / sideways setups), not a display bug. Dual Bot is meant to collect everything.

## 7. DECISIONS ON HOLD
- Dual Bot stays in full explore mode for 2-3 weeks (decided 26 Oct 2026). Do not touch dual_lab.py. Decide about a "never skip" switch after that.
- SQLite and WebSocket NOT yet: changing how Dual Bot saves while it runs can lose or double data, and the backend once froze on heavy file reads. First collect clean data 2-3 weeks. Check size: `ls -lh $(find ~ -name dual_lab_data.json 2>/dev/null)`. Under about 20 MB = keep waiting. When big or slow: move to SQLite in a copy, compare numbers with the JSON, then switch. Never change Dual Bot saving and the app in the same step.
- Gold / multi-asset and live mode: last.

## 8. PHASE 4 PLAN (how Brain lessons could reach the main bot)
A: Brain only watches (now). B: shadow "would take / would skip" - DONE as the "What if the bot had listened?" card. C: Brain skips only clearly bad signals, paper, switch default OFF, only after the READY CHECK. D: exit advice used to trail the stop, default OFF. Safety: if trust falls back to "learning" or luck says "Could be luck", any filter turns itself off. A sudden drop in the newest 100 trades vs older ones shows a warning.

## 9. BACKEND CLEANUP MAP (read-only audit, nothing deleted)
- Looks dead: backend/main.py (2,964 lines, old Kivy screen), backend/config.py. Check first: search Termux scripts (owl_auto.sh etc.) for "main.py". Use `bash tools/old_check.sh` (report only; `move` puts them in backend/_old/, never deletes). Run the app one day, then delete _old/.
- Run by hand, keep: z_scenarios.py, india_demo.py, tradebulls_probe*.py, test_*.py.
- recovered_bot/ai_*.py (about 30 files): used by older AI tabs (Pick, Desk, Trail, Coach, Vision). Dead or not depends on which AI tabs the app still shows: check screen by screen first. ai_backup.py is used, keep.
- Big files to split later: api_server.py (~2,500 lines), recovered_bot/india_runtime.py, ai_selfsignal.py. Only after the cleanup above.
- Not seen: Claude never ran the app; a file started by a Termux script outside the repo would look dead.

## 10. CHANGE LOG (newest first)
- 27 Oct 2026 (v17): owl_v5e = owl_auto.sh v5e, BUILD=40. Phone log after v5d showed "BUILD 25 -> 35": the v5c/v5d compare read every digit of the BUILD line including its comment (v5c in the comment). It worked by luck. v5e reads only the whole number after BUILD= . BUILD jumped to 40 so the installed (old) parser still sees a bigger number. Self-update worked by itself on the phone (v5c -> v5d, no manual step, zip pushed to GitHub). Owner works with CHANGED-FILES-ONLY zips (not the whole repo): that is the normal case and is fully supported (see section 13).
- 27 Oct 2026 (v16): owl_v5d = owl_auto.sh v5d (BUILD 3). The owner downloads zips of OTHER repos into the same Download folder; v5c would have used any zip with backend/ or README.md (overlay on the live code, push to this GitHub repo). v5d uses a zip ONLY if every file sits in the top folder Indian-main/ (Claude zips and the GitHub zip of this repo); all others are ignored and logged once as "zip ignored". Found in the log: owl_v5c.zip was seen at 04:49:34 but the push never ran because the owner stopped the old watcher at that moment (he pushed README v15 + BUILD 2 by hand, DONE). v5d reaches the phone by itself through the v5c self-update: the owner only downloads the zip.
- 27 Oct 2026 (v15): owl_v5c = owl_auto.sh v5c (BUILD 2). Bug found by the owner: v5 pushed release-apk (6).zip, so a 66 MB app-release.apk landed in the repo (commit 0a9aca3). v5c pushes ONLY code zips (backend/, frontend/, tools/, test/, scanner/, android/, .github/, README.md, pubspec*), never apk/aab/zip/keystore, and skips any file over 20 MB. v5c also updates itself: a zip or repo zip holding tools/owl_auto.sh with a higher BUILD= number replaces ~/owl_auto.sh and the watcher restarts itself. Owner copies owl_auto.sh by hand ONE last time (v5 has no self-update). Cumulative: README.md + tools/owl_auto.sh.
- 27 Oct 2026 (v14): owl_v5b = v13 content + section 14 (owner flow for backend + app build) + rule 6b (how to talk to the owner). Owner installed owl_auto.sh v5 on his phone (status showed v5, watcher RUNNING). Zip is cumulative: README.md + tools/owl_auto.sh.
- 27 Oct 2026 (v13): owl_v5 = deploy fix. tools/owl_auto.sh v5 + this README (section 13). Cause found: the Brain, Dual Bot, PA and Vol workers are separate python processes started by the backend; owl_auto.sh restarts did not stop them, so an old Brain kept running after a new zip (Ready Check / Timing / Week keys were missing). v5 stops every python process in the OWL code folders on each deploy/restart and checks every ~5 min for workers older than the code. One-time owner step: copy owl_auto.sh to ~ (see section 13). No app or backend code changed.
- 27 Oct 2026 (v12): F3 done. zip owl_F3 has only the F3 files (README, brain_week.py, test_brain_week.py, brain_own.py, smart_brain_view.dart) because the owner applied owl_EFG. Backend changed: restart the backend after the push. Flutter not built here. Next: G1 / G2 only when READY CHECK allows and the owner says.
- 27 Oct 2026 (v11): F2 done. zip owl_EFG is cumulative: it also holds E1-E5 and F1 (owner had applied none yet). 14 files. Backend changed (brain_retest.py new, brain_own.py): restart the backend after the push. Flutter not built here. Next: F3 only when data is ready and the owner says.
- 27 Oct 2026 (v10): E5 + F1 done. zip owl_EF is cumulative: it also holds E1-E4 (owner had applied none of E). 12 files. Backend changed (brain_side.py, brain_own.py): restart the backend after the push. Flutter not built here. Next: F2 only when data is ready and the owner says.
- 27 Oct 2026 (v9): E3 + E4 done. zip owl_E is cumulative: it also holds E1 + E2 (owner had not applied owl_E12). 7 files. Opportunities tab itself was not edited: OwlDensity already tightens it. Flutter not built here. Next: E5 when the owner says.
- 27 Oct 2026 (v8): E1 + E2 done (compact header, underline tab pills, fade switch). zip owl_E12 has 3 files (README, live_ticker_bar.dart, dual_bot_screen.dart); owner had already applied owl_D. Flutter not built here. Next: E3 when the owner says.
- 27 Oct 2026 (v7): Part D done: D1 brain_tp_hold.py (best exit + hold time per mix) + D2 Brain card. zip owl_D is cumulative (contains N2, B, C too) because the owner had applied none of them yet. Next: E when the owner says.
- 27 Oct 2026 (v6): Part C done: C1 READY CHECK card (brain_ready.py) + C2 retest headline. zip owl_C is cumulative: it also contains N2 (README map) and Part B, because the owner had not applied owl_B yet. Next: D when the owner says.
- 27 Oct 2026 (v5): Part B done: B1 brain_lessons.py (Timing Sync + lessons) + B2 Brain tab card. Owner had not applied the N2 zip, so owl_B also carries the README. Next: Part C only when the owner says.
- 27 Oct 2026 (v4): N2 code map (section 12) + rules 8-10. Next: Part B (Timing Sync + lessons), then C only when owner says.
- 27 Oct 2026 (v3): Part A done (A1 honest numbers + header label, A2 BTC out of the alt curve, A3 signal-type card + open age). Next: Part B (Timing Sync + lessons).
- 27 Oct 2026 (v2): lettered Parts A-G plan from the 3 prompts + screenshots, data truth section, Termux paste command, naming rule. Round 1 (old Parts 1-3: Brain learning, retest report, Simple tab boxes) confirmed applied by owner.
- 27 Oct 2026 (v1): N1 single notes file.
- 26 Oct 2026: Brain own trades, exit learning, observation layers, Simple tab, performance tab, trust 100 trades.
- 25 Oct 2026: Brain exit advice, what-if report, fixes (Connecting, labels), docs, ideas from links (FreqAI rolling memory used, Jesse luck test used, vectorbt/TradeMaster/TensorTrade not used: licence or heavy).
- Before: Smart Brain parts 1-3, Dual Bot screen, Signals/Alerts look, old labs locked.

## 11. HOW THE OWNER APPLIES A ZIP (Termux, copy-paste, one shot)
Owner facts: updates from Termux, repo is ~/Indian-main (GitHub mehreenhusn-cmyk/Indian, branch main), already logged in, downloads zips to ~/storage/downloads/. Every zip has the top folder Indian-main/ and contains ONLY changed files (README.md included when it changed).
Command template (Claude fills in NAME and MESSAGE every time; this discards any uncommitted local edits, the repo is a mirror):
```
cd ~/Indian-main && git fetch origin && git reset --hard origin/main && rm -rf ~/up && mkdir -p ~/up && unzip -oq ~/storage/downloads/NAME.zip -d ~/up && cp -r ~/up/Indian-main/. . && git add -A && git commit -m "MESSAGE" && git push origin main
```
Only the FIRST time (old notes cleanup), add `bash tools/clean_old_notes.sh &&` right before `git add -A`. The script deletes old notes files (docs/PROJECT_STATUS.md, BACKEND_AUDIT.md, PHASE4_DESIGN.md, CHANGES*.md) only if README.md is this file, and never touches code. After a push, GitHub builds the app (flutter-build.yml); backend files need the usual restart.

## 12. CODE MAP (open ONLY what the feature needs; line numbers approximate - search the function name)
Data dir: dual_lab._dir() (phone: ~/owl_data). Backend tests: `cd backend && python3 test_X.py` (no network). Flutter is not compiled by Claude.

HOW BRAIN DATA REACHES THE APP (the one road every Brain feature uses)
1. smart_brain.worker() (~L1023) loops, reads Dual Bot data (read_v1 ~L89 reads dual_lab_data.json, read-only), calls build_view() (~L967) and saves smart_brain_view.json.
2. api_server.py route GET /api/smart_brain (~L1746) returns smart_brain.status() (~L1175), which includes that view.
3. dual_bot_screen.dart _pollBrain() (~L89) stores it in `_brain` (a Map). Tabs get slices: SimpleTab, OpportunitiesTab(brain), PerformanceTab(brain), SmartBrainView.
NEW BRAIN REPORT = (a) new small backend file with one function returning a plain dict, (b) one hook line in build_view() under a new key, (c) one card in smart_brain_view.dart reading brain['key'], (d) one small test, (e) tick section 4 + update this map.

BACKEND (backend/)
| File | Job | Notes |
|---|---|---|
| dual_lab.py (1234) | Dual Bot v1: paper bot, takes every signal, saves dual_lab_data.json | DO NOT TOUCH. make_view ~L816, status ~L1191, day_review ~L733, retest_summary ~L447 |
| tag_lab.py (675) | Builds the setup TAGS for each entry (DIMS ~L47). "order" tag = who came first: _order ~L111 (values: both on the same candle / main chart came first (1-2 or 3-5 candles before) / Z candle came first ... / gave the OPPOSITE signal / gave nothing) | DO NOT TOUCH. make_tags ~L124 |
| smart_brain.py (1184) | The Brain core: clean_score ~L152, divergence ~L110, probability ~L202, trust ~L352, scan ~L464, luck_test ~L640, risk_stats ~L666, sideways_report ~L758, retest_report ~L803, performance ~L871, build_view ~L967, worker ~L1023, gate ~L1120-1154, status ~L1175 | Big file: add only thin hooks here. Constants at top (MIN_N, TRUST_MIN=100, ROLL_HALF=400, KEY_DIMS) |
| brain_week.py (~100) | F3 weekly report card + time-of-day cap for own trades: block_of(ms), report(own, now_ms), blocked(own, now_ms, opened). Hooks: brain_own.open_from, summary key 'week' | own book only. test_brain_week.py |
| brain_retest.py (~85) | F2 retest own book: twin(S,Z,i,d,sl,tps,rule,TL,lev,fee) -> (net, bars) / (None,None) / None; report(own) -> status collecting/early/unsteady/better/worse. Hooks: brain_own.settle (stores t['rt']), brain_own.summary key 'retest_book' | measure only. test_brain_retest.py |
| brain_side.py (~75) | F1 sideways self-rule for own trades: state(own) -> dict, blocked(own, tg, now_ms, opened_side), is_side(tg). Hook: brain_own.open_from; summary key 'side_rule' | own book only. test_brain_side.py |
| brain_own.py (~205) | Brain OWN paper trades: stage_for ~L24 (learning 0-99 / medium 100+ / quality 300+), open_from ~L60, settle ~L102, summary ~L155 | file smart_brain_own.json |
| brain_lessons.py (153) | B1 Timing Sync: classify() reads the 'order' tag, timing_report(trades) -> groups, deep clean candidate, lessons(). Hook: smart_brain._timing_view -> view key "timing" | report only, BTC left out. test_brain_lessons.py |
| brain_ready.py (53) | C1 READY CHECK: ready_check(view) -> 7 rows (4 gates + retest, timing, own book) + headline. Hook: smart_brain._ready_view, runs last in build_view -> view key "ready" | report only. test_brain_ready.py |
| brain_tp_hold.py (83) | D1 exit style + hold time: report(rows) -> all + per-mix best exit vs bot exit, hold minutes, steady check, lines. Hook: smart_brain._tphold_view -> view key "tp_hold" | report only, BTC left out. test_brain_tp_hold.py |
| brain_exit.py (126) / brain_exit_pick.py (79) | Exit learning (FULL TP / HALF TP / HOLD), advice only | smart_brain_exit.json |
| brain_follow.py (64) | "What if the bot had listened?" report | |
| pa_layer.py (332) / vol_layer.py (248) / layers_join.py (77) | Price Action + Volume observation layers and their join report (report only) | own *_log.json, *_view.json; routes /api/layers/pa, /api/layers/vol |
| api_server.py (2560) | All routes. Brain: ~L1746. Dual Bot: ~L1708. Startup timers that launch dual_lab/smart_brain/pa/vol: ~L277-303 | Never add logic here, only routes |
| recovered_bot/ | Main (crypto) bot, strategy, India terminal, old AI tabs | Not needed for Brain work. Section 9 for cleanup |
| filter_lab / variant_lab / scan_lab / doctor_extra | Old labs (locked off) | ignore |
Data files (all in the data dir): dual_lab_data.json (Dual Bot, READ ONLY for Brain), smart_brain_view.json, smart_brain_book.json, smart_brain_own.json, smart_brain_exit.json, smart_brain_ctl.json, pa_layer_*.json, vol_layer_*.json.
Tests that matter: test_brain_tp_hold.py, test_brain_ready.py, test_brain_lessons.py, test_smart_brain.py, test_brain_own.py, test_brain_exit*.py, test_brain_follow.py, test_brain_gate.py, test_brain_perf.py, test_sideways_report.py, test_pa_layer.py, test_vol_layer.py, test_layers_join.py, test_dual_lab.py, test_btc.py.

FLUTTER (frontend/lib/)
| File | Job | Notes |
|---|---|---|
| screens/dual_bot_screen.dart (~920) | Dual Bot screen. 6 underline pills (E2): 0 Simple, 1 Now, 2 Opportunities, 3 Learned, 4 Performance, 5 Brain (_segRow ~L776, tab bodies in _segBody(), shown through AnimatedSwitcher). _poll ~L61 (/api/dual_lab), _pollBrain ~L89 (/api/smart_brain) | Tab 3 "Learned" cards (_reviewCard, _setupCard, _retestCard, _scenCard, _lessonsCard, _modelCard) are inside this file |
| widgets/smart_brain_view.dart (~900) | Brain tab (chip 5; build() shows 6 cards, 'More reports' toggle _moreToggle folds the other 18, _weekCard is the first of them): one card method per report: _nowCard ~L124, _trustCard ~L219, _luckCard ~L247, _exitCard ~L269, _followCard ~L311, _riskCard ~L352, _readyCard ~L610 (Ready Check, key 'ready', top of tab), _tpHoldCard ~L641 (Exit style + hold, key 'tp_hold'), _timingCard ~L683 (Timing Sync, key 'timing'), _sidewaysCard ~L746, _retestCard ~L796 (has the C2 headline), _layersCard ~L921, _ownCard ~L942 | New Brain cards go here (use _card(), _chip(), _bar() helpers at the top) |
| widgets/simple_tab.dart (299) | Simple tab: LOCKED / FLOATING / NET, signal-type card, recent trades | |
| widgets/performance_tab.dart (128) / opportunities_tab.dart (113) / dual_summary_strip.dart (166) | Performance, Opportunities, summary strip | |
| widgets/dual_trade_card.dart / dual_trade_chart.dart | One Dual Bot trade row / its chart | |
| widgets/live_ticker_bar.dart (547) | Top header row (MAIN bot P&L etc.) | |
| widgets/owl_card.dart (OwlSectionCard, OwlChip, OwlDensity), theme/app_theme.dart, app_colors/typography/spacing | Shared look (cards, chips, colors) | Part E works here. DualTradeCard.badgeRow (dual_trade_card.dart) = the one-line trade badges |
| providers/app_provider.dart (2020), screens/*, other widgets | Main app, positions, signals, alerts, India, AI tabs | Not needed for Brain work |
Other: tools/owl_auto.sh (phone watcher v5, section 13), tools/clean_old_notes.sh (one-time notes cleanup), tools/old_check.sh (dead-file report), .github/workflows/flutter-build.yml (builds the app after push).

## 13. PHONE DEPLOY (how the owner's phone picks up a new zip - owl_auto.sh v5)
Owner facts: browser/GitHub downloads land in ~/storage/downloads. The watcher ~/owl_auto.sh (started by Termux:Boot too) looks there every 10 s. Data lives OUTSIDE the code (~/storage/shared/owl_data), so a deploy never touches trades or settings. The owner does not want to kill or restart anything by hand.
- LIVE CODE = ~/owl_code (backend + frontend). NOT ~/Indian-main (that folder is only for git push). Check: `ls ~/owl_code/backend/brain_ready.py`.
- Zip named Indian-main*.zip (full repo from GitHub) = FULL deploy: swapped in as ~/owl_code (old one kept as ~/owl_code_prev), everything restarted.
- Any other zip (owl_X.zip) = OVERLAY: only its backend/ files are copied on top, and only if the zip is NEWER than the full zip in use; python files are compile-checked and rolled back if bad. A zip without backend/ files (README, tools, Flutter only) is skipped for the backend and just pushed to GitHub.
- v5 fix: workers (smart_brain.py, dual_lab.py, pa_layer.py, vol_layer.py, ping_worker.py) are separate python processes started by api_server.py timers (8/15/25/35 s after boot) and by the API calls. On every deploy/restart the script now stops every python process whose folder is inside ~/owl_code, ~/Indian-main or ~/Indian-cleanup (by folder, not by name), then starts the backend. Every ~5 min stale_check stops any worker that started before the newest backend .py file; the backend starts it again by itself (a worker only restarts when its heartbeat is older than 3 min, so allow up to ~3 min).
- Git sync (owl_auto.sh -> GitHub) now uses ~/Indian-main when it has .git, else ~/Indian-cleanup. If the owner also pushes by hand with the section 11 command, the second push finds nothing new and simply stops; that is fine.
- CHANGED-FILES ZIPS (the owner NEVER downloads the whole repo): a zip with only the changed files, all inside Indian-main/, is the normal input. Backend files are copied on top of ~/owl_code, everything is pushed to GitHub. A full Indian-main*.zip is needed only if the live folder ~/owl_code is lost. Send the same file again in a later zip if you are unsure: copying a file twice does no harm. Parts work as before (README rule: ONE latest cumulative zip per round).
- v5d: ONE REPO RULE. Every zip you give the owner MUST have all its files inside the single top folder Indian-main/ (never loose files, never another folder name), otherwise the phone ignores it. The owner keeps other repos' zips in the same Download folder; they are never touched.
- v5c: ONLY code zips are pushed to GitHub (APK / release-apk zips are skipped, log "github sync skipped"). SELF-UPDATE: when you change tools/owl_auto.sh you MUST raise the BUILD= number at the top of it (v5c = 2, v5d = 3, v5e = 40; always use the next whole number, nothing but the number and a comment after it); the phone then replaces itself from any zip that contains it, no manual copy. A lower or equal BUILD is ignored; a file with a syntax error is refused.
- Quick truth check after any deploy (wait ~4 min): `curl -s localhost:8000/api/smart_brain | python3 -c "import sys,json;v=json.load(sys.stdin);print(sorted(v.keys()))"` must list the keys of the newest Brain features (ready, timing, retest, tp_hold, week). Missing = an old worker is alive: `bash ~/owl_auto.sh restart`, wait 4 min, check again.
- Logs: `bash ~/owl_auto.sh status` (also saved to Download/owl_status.txt), `bash ~/owl_auto.sh logs`. Look for "DEPLOYED", "OVERLAY applied", "stopped N old python process(es)", "stale check".
- Not tested by Claude: the script ran only in a sandbox with fake processes (kill by folder and stale check both worked), never on the phone.

## 14. OWNER FLOW IN SIMPLE STEPS (what the owner really does - keep this true)
BACKEND (runs by itself on the phone):
1. Claude gives a zip (owl_X.zip) or the owner downloads the repo zip from GitHub (Indian-main*.zip). It lands in ~/storage/downloads.
2. The watcher (owl_auto.sh v5, started by Termux:Boot) sees it within about 10 s, puts the backend files in ~/owl_code, stops every old python process, starts the backend + workers. Nothing to type.
3. About 4 min later all Brain workers run the new code. The owner can check with the truth-check command in section 13.
APP (Flutter, built by GitHub, never on the phone):
1. The same zip is pushed to GitHub, either by the watcher itself (log line "github sync: pushed", see `bash ~/owl_auto.sh logs`) or by the section 11 command.
2. A push to main makes GitHub Actions (.github/workflows/flutter-build.yml) build the app; the browser version is downloaded by the watcher about 10 min later into ~/owl_web (just refresh). Claude cannot compile Flutter: a build error from the owner is the only test.
3. A Flutter-only change needs no backend restart. A backend change needs nothing by hand: the watcher restarts it.
WHEN SOMETHING LOOKS OLD: (1) `bash ~/owl_auto.sh status` (2) `bash ~/owl_auto.sh restart`, wait 4 min (3) send Claude the output. Normal noise, ignore: "Terminated ... nohup python ping_worker.py" and "/proc/NNN/cmdline: No such file" printed during stop = old processes ending.
APP ON THE PHONE (decided 27 Oct): Android never installs an APK from outside by itself, so the owner taps "Install" once per build; installs over the old app (no uninstall) as long as it is the same package and signing key. If Android says "App not installed", ask the owner (key changed). The browser app updates itself (refresh). An in-app "Update" button (app downloads the newest APK from GitHub, owner taps Install) is possible, about 150 lines Flutter + one GitHub setting: NOT built, only when the owner asks. Backend never needs the app update: it updates from the zip alone.

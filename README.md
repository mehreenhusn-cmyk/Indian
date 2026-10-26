# Owl Terminal - MASTER NOTES (the ONLY notes file in this repo)

OWL MASTER NOTES v3 - last updated: 27 Oct 2026

Crypto paper-trading app (Flutter) + Python backend. Dual Bot v1 collects trades. Smart Brain learns on the side, paper only.

## 0. FOR EVERY CLAUDE / READER - do this every time
1. Read this whole file first. It is the single source of truth. Do NOT create other README / NOTES / CHANGES / status files.
2. Check section 4 (ROAD AHEAD). If a "start when" data condition is reached, tell the owner plainly: "Data is ready for step X. Shall I build it?" Build only after his "ok".
3. Owner way of working: tell number of files + lines first, start only after "ok", build in parts, ONE zip with only changed files. He updates from Termux in one shot. Simple English or Hinglish, short replies.
4. After ANY work: update this file in the same zip: tick the step in section 4, add a row to section 3 (DONE) and section 10 (change log), change the date above. Never leave this file stale.
5. Flutter cannot be compiled in Claude's sandbox. Say so, and ask the owner to send any build error.
6. NAMING (owner asked, so he never gets confused): "Round 1" = old Parts 1, 2, 3 (finished and already pushed by the owner). All new work is Part A, Part B, Part C ... and steps inside a part are A1, A2, A3 / B1, B2 ... Never reuse old numbers. Name the zip after the part, e.g. owl_A1.zip.
7. EVERY TIME a zip is delivered, end the reply with the ONE copy-paste Termux command from section 11 (with the right zip name and commit message filled in). The owner just copies, pastes, done.

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

## 4. ROAD AHEAD (Part A, B, C ... in this order; start a part only when its "start when" is true AND the owner says ok)
Sources: owner's 3 prompt files (Brain strong modules, Owl FINAL master, FINAL FORM all problems) and his phone screenshots of 27 Oct.
| Part | What | Files | Lines | Start when | Status |
|---|---|---|---|---|---|
| A1 | Honest numbers: trust bar shows "100 of 100, earned check pending" (never 150 of 100); top header label says it is the MAIN bot's P&L (it showed -139 while Dual Bot locked was -744 = confusing) | smart_brain_view.dart, live_ticker_bar.dart | ~35 | NOW | DONE 27 Oct (zip owl_A) |
| A2 | Performance tab: BTC left out of the alt curve (it is now mixed in: 479 trades vs 464 on the Today card, equity -892 = -744 alts + -148 BTC). BTC shown as its own line | smart_brain.py, test_brain_perf.py, performance_tab.dart | ~40 | NOW | DONE 27 Oct (zip owl_A) |
| A3 | Simple tab: always-visible mini summary "Both same candle / Z only / Main only" (data shows Both = green, Main only = worst) + check every open-trade row shows age (5m / 1h) | simple_tab.dart, dual_bot_screen.dart | ~65 | NOW | DONE 27 Oct (zip owl_A) |
| B1 | Indicator Timing Sync report: SAME candle / Z first then Main (1-2 or 3-5 candles) / Main first then Z / Z only / Main only, with count, win %, USDT, TSI state, sideways; plus 5-10 plain "how to use both indicators" lessons; defines "deep clean setup" from data. Uses the existing "order" tag, Dual Bot untouched | brain_lessons.py (new), test_brain_lessons.py (new), smart_brain.py | ~230 | NOW (Dual data is enough) | TODO |
| B2 | Brain tab card for B1 (one strong block, plain words) | smart_brain_view.dart | ~110 | after B1 | TODO |
| B3 | Brain OWN trades softly prefer "deep clean" setups | brain_own.py, smart_brain.py, test | ~50 | B1 numbers stable for 3+ days | WAIT FOR DATA |
| C1 | READY CHECK card on top of Brain tab: trust, luck, what-if, exit hit-rate, retest, timing sync, own stage + trades to next stage | smart_brain_view.dart, smart_brain.py | ~110 | after A | TODO |
| C2 | Retest card headline: "Waiting is better by +X USDT" with best wait, and the honest note that part of it is skipping signals | smart_brain_view.dart | ~30 | with C1 | TODO |
| D1 | TP + hold time per setup mix (best exit, bars held in wins vs losses, fast vs slow). Report only | brain_tp_hold.py (new), test_brain_tp_hold.py (new), smart_brain.py | ~200 | NOW | TODO |
| D2 | Brain tab card for D1 | smart_brain_view.dart | ~75 | after D1 | TODO |
| E1 | Modern look 1: one compact header row (CRYPTO/INDIA, latency, PAPER, TF, P&L, power), less padding | live_ticker_bar.dart, app_theme.dart | ~80 | after A, B | TODO |
| E2 | Modern look 2: Dual Bot tabs as clean segmented / underline pills, smooth switch | dual_bot_screen.dart, owl_card.dart | ~100 | after E1 | TODO |
| E3 | Modern look 3: Simple tab polish, tighter trade rows with one-line badges (clean / agree / dislike / FAKE) | simple_tab.dart, dual_trade_card.dart | ~150 | after E2 | TODO |
| E4 | Modern look 4: Now / Opportunities / Learned density, no tall empty padding, secondary Brain cards collapsible | dual_bot_screen.dart, smart_brain_view.dart, opportunities_tab.dart | ~200 | after E3 | TODO |
| E5 | Modern look 5: same tokens and buttons on Dashboard, Positions, Signals, Alerts (nothing removed) | owl_card.dart, app_theme.dart, 4 screens | ~250 | after E4 | TODO |
| F1 | Sideways self-rule: Brain OWN trades only, fewer own trades in sideways when own book loses there | brain_own.py, smart_brain_view.dart, test_brain_own.py | ~110 | 100+ own finished trades AND 30+ in sideways (about 4-7 days) | WAIT FOR DATA |
| F2 | Retest own book (separate file, compared with normal own book) | brain_retest.py, view, test | ~200 | 100+ signals that came back AND same sign in older and newer half (about 7-10 days) | WAIT FOR DATA |
| F3 | Weekly report card + time-of-day cap for own book | 4 files | ~190 | 7+ days of own trading and 300+ own finished trades | WAIT FOR DATA |
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

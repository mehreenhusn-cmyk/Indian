# Owl Terminal - Project Status (read this first)

Last updated: 25 Oct 2026. Written in simple words on purpose.
Rule for anyone working on this repo: do NOT break the running bot, Dual Bot v1 (`dual_lab.py`, `tag_lab.py`, `dual_lab_data.json`) or paper mode. Only two indicators are used (Main EMA50/SD chart and the Z/TSI pane). No third indicator (no ADX, no Hurst). Trading day = 5:30 AM IST (00:00 UTC). Owner wants: tell number of files and lines first, start only after "ok", build in parts, give ONE latest zip with changed files only.

## What is the system
- Dual Bot v1 = paper bot that reads both indicators and collects trades, tags and a setup book.
- Smart Brain = side layer. It only READS Dual Bot data. It scores setups, gives a clean score, a win chance, a trust meter, a luck test and its own paper book. It does not trade.

## DONE (all in the repo)
| Part | What | Where |
|---|---|---|
| 1 | Brain "what it thinks now", best/worst setup, badge on trade card | smart_brain.py, smart_brain_view.dart, dual_trade_card.dart |
| 2 | Dual Bot screen in 4 parts: Now / Learned / History / Brain | dual_bot_screen.dart |
| 3 | Luck test, risk numbers, worst-case range, rolling memory | smart_brain.py, smart_brain_view.dart |
| 4 | Shared card, chip, number, filter chip, tabs, side badge | owl_card.dart |
| 5 | Dashboard banners and gaps | dashboard_screen.dart |
| 6 | Signals and Alerts new look (shared pieces, bigger P&L, LONG/SHORT badge) | signals_screen.dart, signal_tile.dart, alerts_screen.dart, trade_row.dart |
| 7 | Brain learns when to exit (shadow only, advice only) | brain_exit.py |
| 8 | Backend audit + Phase 4 design docs | docs/ |
| 9 | "What if the bot had listened?" report (read-only) | brain_follow.py |
| 10 | Brain "skip bad signals" gate: built, then the app switch was REMOVED on purpose. Brain cannot skip any trade. Default OFF in backend. | smart_brain.py, test_brain_gate.py |

| 11 | Fixes 25 Oct: tab keeps last reply (no "Connecting..."), TP ladder labels no longer overlap, workers start earlier (Dual Bot 8 s, Brain 15 s) and Brain's first round skips the slow coin scan, trust needs 100 judged trades with a progress line on the Brain tab | dual_bot_screen.dart, smart_brain_view.dart, dual_trade_card.dart, api_server.py, smart_brain.py |
| 12 | Brain's OWN paper trades, separate book (`smart_brain_own.json`). When the 5-minute scan finds a setup it likes it opens a pretend trade (same stop, targets and exit rule as Dual Bot), follows it to the end, shows open / finished trades and USDT on the Brain tab. Max 20 open. Never touches Dual Bot or the main bot. | brain_own.py, smart_brain.py, smart_brain_view.dart, test_brain_own.py |
| 13 | Brain learns WHICH EXIT works (FULL TP / HALF TP / HOLD) from old setups (their results for every exit style are already in Dual Bot's memory). Its own pretend trades use the style that was clearly best among look-alikes, else the bot's exit. Shown on the Brain tab with results by exit style. Advice for the Brain's own pretend trades only. | brain_exit_pick.py, brain_own.py, smart_brain.py, smart_brain_view.dart, test_brain_exit_pick.py |
| A | Sideways report card on the Brain tab: Trending / Mixed / Sideways, trades, win%, real USDT, "sideways cost you X USDT", "what if skipped" story, hold-off table, older/newer half check. REPORT ONLY, nothing is skipped. | smart_brain.py, smart_brain_view.dart, test_sideways_report.py |
| 14 | Dual Bot Now tab: status bar (bot state, today P&L, trust, open count), 3 summary cards (Today / Quality / Open Risk), filter All / Good only / Long / Short, trade cards with left colour accent (Brain clean 70+ green, under 40 red, else grey), "open 42m" chip and Brain one-line reason. Flutter, not built here. | dual_summary_strip.dart (new), dual_trade_card.dart, dual_bot_screen.dart |
| 15a | Dual Bot tab "Opportunities": Brain watch list (best first) + Brain's own pretend trades (open, last finished). | opportunities_tab.dart (new), dual_bot_screen.dart |
| 15b | Dual Bot tab "Performance": equity curve, win-rate trend (last 20 trades), daily results; old History cards sit below. Tabs are now Now / Opportunities / Learned / Performance / Brain. | performance_tab.dart (new), smart_brain.py (performance()), test_brain_perf.py, dual_bot_screen.dart |
| 16 | Signals and Alerts: smaller top gap, smaller TODAY number. | signals_screen.dart, alerts_screen.dart |
| V2-1 | Price Action Light (observation layer, version 2). Watches every Dual Bot trade: signal candle strength, rejection wicks, break of previous high/low, candle size, retest of EMA50 in the next 6 candles. Gives ONE verdict per trade (supports / unclear / against) and later compares it with what the trade really earned. Own process, own log `pa_layer_log.json`, only READS Dual Bot data, never trades or skips. App card comes in V2-2. | pa_layer.py, test_pa_layer.py, api_server.py (start + /api/layers/pa) |
| V2-2 | Volume Context layer (version 2): relative volume of the signal candle (low / normal / high / climax), volume trend, candle direction, follow-through of the next 3 candles. Verdict supports / unclear / against, checked later against real results. Own process and log `vol_layer_log.json`, reads Dual Bot only. Brain tab gets one card "OBSERVATION LAYERS" showing both layers (data via smart_brain.status()["layers"]). | vol_layer.py, test_vol_layer.py, smart_brain.py, smart_brain_view.dart, api_server.py (start + /api/layers/vol) |
| V2-3 | Join report: Price Action + Volume + Brain clean score on the SAME finished trades ("both layers support", "a layer is against", and the same split among trades the Brain already likes). Stays "collecting" until 100 finished trades read by both layers AND 10 days of data; only calls the layers useful if the gain shows in both halves of the data. Made by the Brain worker at most every 10 minutes, shown inside the OBSERVATION LAYERS card. Report only. | layers_join.py, test_layers_join.py, smart_brain.py (worker), smart_brain_view.dart |
| 17 | Dual Bot "Simple" tab (now the FIRST tab, opens by default): one colour + sentence "Is the bot OK?" (separates locked closed P&L from floating open P&L), open trades one line each (best first, Brain dot, tap = chart), best/worst finished trades, sideways cost line. Also fixed a layout bug in the Now tab strip (3 cards broke the layout and hid the open list) and the strip now shows locked P&L big, floating small. Tabs: Simple / Now / Opportunities / Learned / Performance / Brain. Frontend only. | simple_tab.dart (new), dual_bot_screen.dart, dual_summary_strip.dart |
| - | tools/old_check.sh restored (report only; `move` puts old main.py / config.py in backend/_old/, never deletes) | tools/old_check.sh |

## NOT DONE - waiting for DATA (do not build early)
| Work | Files / lines | Start only when ALL of these are true |
|---|---|---|
| Step D: use Brain exit advice to trail the stop | 2 files, ~120 lines | Exit advice has 10+ checked opinions AND hit-rate is above 60% |
| Step C live: let Brain skip bad signals in the main bot | 2-3 files, ~100 lines | Trust meter says "earned" AND luck test says "Looks real" AND the "What if the bot had listened?" card shows SKIP DISLIKED clearly better than TAKE ALL (30+ judged trades) |

## NEXT (owner agreed 26 Oct 2026)
- After 10+ days of data: read the joined view. If it says the layers add value, the owner decides about a switch (default OFF). Do not join into trading earlier.

## NOT DONE - on hold
- Dual Bot stays in full explore mode for the next 2-3 weeks (owner decision 26 Oct 2026). Do NOT touch dual_lab.py. Decide on a 'never skip' switch after that.
- SQLite and WebSocket: on hold (check the size of dual_lab_data.json first, wait if under about 20 MB).

## NOT DONE - later
- Break up `api_server.py` and `backend/main.py` (old Kivy app, looks dead). First run the check in docs/BACKEND_AUDIT.md. Move to `_old/`, never delete.
- Gold / multi-asset, then live mode (last).

## Ideas taken from the links (checked 25 Oct 2026)
| Link | Used? | How |
|---|---|---|
| FreqAI RL docs | Idea only | Brain exit advice in plain Python, no torch (Part 7) |
| FreqAI adaptive retrain | Yes | Rolling memory: old trades count less (Part 3) |
| Jesse | Yes | Luck test, risk numbers, worst-case range (Part 3) |
| vectorbt | No | Licence (Apache + Commons Clause), idea of fast backtest only |
| TradeMaster | No | Heavy RL platform (DQN, DeepScalper), needs torch and big data |
| TensorTrade, OctoBot, awesome list, NVIDIA | Not opened yet | Heavy or GPU. Open later only if the owner asks |

## READY CHECK (what to look at on the phone, Brain tab)
1. TRUST METER says "earned" (not "Still learning").
2. Luck test says "Looks real".
3. Card "What if the bot had listened?" has 30+ judged trades and SKIP DISLIKED is better than TAKE ALL.
4. Exit advice card has 10+ checked opinions and hit-rate above 60%.
- Trust needs 100 judged trades (was 30, raised 25 Oct 2026 so luck cannot pass it).
- 1 + 2 + 3 true = ask the owner about Brain skip.
- 4 true = ask the owner about Step D.

## Owner's vision (told 25 Oct 2026, NOT built yet - no live, no India)
Dual Bot learns the two indicators. Smart Brain is the upgrade: it should find opportunities itself, take its own PAPER trades, learn from new data and explore new scenarios (sideways, time, speed), and learn when to book full TP, half TP or hold. Maybe later he gives it $10 to trade for real. Also: data must load fast after the backend starts.
Brain own paper trades (Part 12), exit learning (Part 13) and fast load (Part 11) are DONE. Still waiting for data: Step D and Brain skip (see above). Always tell files and lines first.

## For the next Claude
When the owner starts a new chat, first read this file. If the numbers above look reached (Brain tab: TRUST METER, "What if the bot had listened?", exit hit-rate), ASK the owner: "Data is ready for Step D / Brain skip. Do you want me to build it?" Do not build without his ok.

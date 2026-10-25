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

## NOT DONE - waiting for DATA (do not build early)
| Work | Files / lines | Start only when ALL of these are true |
|---|---|---|
| Step D: use Brain exit advice to trail the stop | 2 files, ~120 lines | Exit advice has 10+ checked opinions AND hit-rate is above 60% |
| Step C live: let Brain skip bad signals in the main bot | 2-3 files, ~100 lines | Trust meter says "earned" AND luck test says "Looks real" AND the "What if the bot had listened?" card shows SKIP DISLIKED clearly better than TAKE ALL (30+ judged trades) |

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
Next steps when he says ok: (1) Brain own paper trades in a separate book, (2) exit learning for full / half TP and hold. (Fast load after start is done, see Part 11.) Always tell files and lines first.

## For the next Claude
When the owner starts a new chat, first read this file. If the numbers above look reached (Brain tab: TRUST METER, "What if the bot had listened?", exit hit-rate), ASK the owner: "Data is ready for Step D / Brain skip. Do you want me to build it?" Do not build without his ok.

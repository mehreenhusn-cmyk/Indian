# Backend audit (read-only, nothing deleted)
Checked on repo Indian-main (16). Method: for every .py file in backend/ and backend/recovered_bot/, I searched who imports or runs it.
This is a map, not an order. Delete nothing until you have seen the "check first" column.

## 1. Looks dead (no other file uses it)
| File | Lines | Why I think so | Check first |
|---|---|---|---|
| backend/main.py | 2,964 | Old Kivy phone-app screen. Nothing imports it. The live app starts from start.py -> api_server.py. | Search your Termux scripts (owl_auto.sh etc.) for "main.py". If none, it can go. Biggest win. |
| backend/config.py | 33 | `Config` class, never imported anywhere. | Safe to remove after the same search. |
| recovered_bot/ai_backup.py | 193 | NOT dead. api_server.py uses it (apply_pending / init). Listed only because its name looks old. | Keep. |

## 2. Run by hand (not dead, but not part of the running app)
| File | Lines | What it is |
|---|---|---|
| backend/z_scenarios.py | 159 | One-shot "which indicator mix gives real signals" test. Output z_scenarios_5m.txt. |
| backend/india_demo.py | 22 | Demo of the India mode with no account. |
| backend/tradebulls_probe.py, tradebulls_feed_probe.py (+ _output.txt) | 30 / 35 | Login and feed test tools. Keep until the broker question is settled. |
| backend/test_*.py | 28 files | Test files. Only run by you or me, the app never loads them. Keep. |

## 3. Used, but only through one path (do not touch without a reason)
recovered_bot/ai_*.py (about 30 files) are mostly used by one or two other files each. Many belong to the older AI tabs (Pick, Desk, Trail, Coach, Vision). Dead or not depends on which AI tabs you still show in the app. Needs a screen-by-screen check (see step 3 below).
Dual Bot files (dual_lab.py, tag_lab.py, filter_lab.py, dual_memory.py) and smart_brain.py are in use. Do not touch.

## 4. Big files to split later (not now)
- api_server.py 2,520 lines: one file with every endpoint. Split by area (market, positions, ai, india, dual/brain).
- recovered_bot/india_runtime.py 1,172 lines, ai_selfsignal.py 925 lines.
- Old docs: CHANGES_smart_brain.md and any README/NOTES files you already planned to delete.

## 5. Safe order for cleanup (one step, then test the app)
1. Search Termux scripts and workflows for main.py and config.py. Nothing found = move both into a folder `_old/` (move, not delete). Run the app one day.
2. If all is fine, delete `_old/`. Saves ~3,000 lines.
3. List which AI tabs the app still shows. Tabs hidden = their ai_*.py and widgets go to `_old/` the same way.
4. Only after that, split api_server.py.

## 6. What I could not see
I did not run the app. "Dead" means "no file refers to it". A file started by a Termux script outside the repo would look dead here.

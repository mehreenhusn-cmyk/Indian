# README_CHOP - Both-Indicator Bot (b3): problems, solutions, plan (v2, 6 Nov 2026)
Say "read README_CHOP and continue" and any Claude can pick this up. Status: C1, C2, C3, C4a and C4b CODE WRITTEN (ALL PARTS WRITTEN) (chop_filter.py, chop_score.py, chop_bot.py, chop_ledger.py, chop_filter_lab.py, api/chop.py + 2 lines in api/sniper_mount.py, and for the app frontend/lib/providers/app_provider_chop.dart, screens/chop_screen.dart, screens/chop_why_tab.dart + 1 line in app_provider.dart + 1 row in more_screen.dart), checked only for matching brackets (no Dart compiler here), NOT RUN. C4 was split in 2: C4a DONE (Today tab), C4b DONE (Why tab). Nothing is pushed to the repo; the owner pushes once at the end.

## 1. Owner problems and the solution for each
| # | Problem the owner faces | Solution | Part |
|---|---|---|---|
| P1 | EMA flat / sideways: top indicator gives many fake BUY/SELL, bot trades them all (Oct: 2,962 trades, ~13% win, loss after fee) | CHOP GATE first: flat EMAs, 3+ EMA50 crosses in 20 candles, or price stuck near the SD middle = BLOCK, even if the bottom matches | C1 |
| P2 | Top and bottom indicator disagree (one signals, other quiet) | Top EMA cross = trigger. Bottom (Z + TSI) = a STATE check, not a second signal | C1 |
| P3 | Bottom gives many signals but price keeps running (SOXS) | Bottom never triggers alone. Late entry allowed if a blocked trigger gets Z + TSI agreement within 3 candles (and chop gate is clear) | C1 |
| P4 | Must not miss rallies (rallies often start inside chop) | BREAKOUT KEY: in chop, allow entry when price closes outside the 1 SD band with TSI + Z agreeing. Missed Rally alarm + Skip Ledger | C1, C3 |
| P5 | Too many small trades, fees eat profit | FEE CHECK: skip if SD target distance is under ~2x round-trip cost (0.14% in the replay engine) | C1 |
| P6 | Quality over quantity (2 clean trades beat 10) | QUALITY SCORE 0-100 per signal: high = full size, medium = half size, low = skip. Judge by net per trade + rally capture, not trade count | C1, C2 |
| P7 | A hard pause after 3 losses would stop the whole bot | NO pause. Soft brake: after 3 losses on one coin, only that coin needs a higher score | C1 |
| P8 | Cannot see what a bot does or why it skipped | b3 decision log (TAKE / SKIP + score + short reason) + Skip Ledger (what each skip would have made) | C3, C4 |
| P9 | Not sure the new rule beats the current bot | Day-by-day REPLAY of stored candles on 5m and 15m: today / month / all, current rule vs filtered variants | C2 | REPLAY from the 5m candles already saved in v2_market.db (no download): current rule vs filter 70/50, 60/40, 80/60 and + bigger-timeframe block, on 5m and 15m (15m built from 5m), today / month / all, train / test split, rally capture, loss avoided, net per trade. Reports only, applies nothing | chop_filter_lab.py (303), api/chop.py (+29), chop_filter.py / chop_score.py (+1 each: optional full_cut / half_cut) | est ~330, actual ~335 | DONE, syntax-checked, NOT RUN |
| P10 | Repo is big, hard to know what works | Section 6 below: one map of which file does what for this feature | C1 |
| P11 | How much profit was missed from rallies, how many losses the filter saved in a day | `skip_outcome()` (C1) says what each SKIP would have made, net of fee: label RALLY_MISSED or LOSS_AVOIDED. C3 sums it per day (5m and 15m apart), C4 shows it at the top of the tab | C1, C3, C4 |
| P12 | Self-learning: decisions must improve, not just be logged | Every decision keeps its 9 score parts + the verdict (TAKE result or SKIP outcome). `suggest_weights()` (C1) PROPOSES new weights only when train (first 60%) and test (last 40%) agree, max 15% change each, needs 60+ judged rows. Weights live in one json file (`load_weights` / `save_weights`). The bot never changes itself: the owner says ok, then the file is written | C1, C3, C4 |

## 2. The two indicators (checked in the Pine files)
- Special 13 (main chart): BUY/SELL label when price crosses EMA50. Also SD bands (TP levels), TSI "I" labels.
- Special Master new (bottom pane): Z-score candle; BUY/SELL when the Z close crosses EMA (30/50). Plus TSI histogram, value line, signal line. BOS/CHoCH and reversal arrows are ignored.
- They use different data (price vs Z candle), so crosses come at different times. That is normal.

## 3. Decision order (always the same)
1. Chop gate (hard block, first). Breakout key may override it.
2. Top trigger: EMA50 cross on a CLOSED candle.
3. Z state and TSI state agree? (Z vs Z-SMA, TSI vs signal line, histogram direction)
4. Bigger timeframe agrees? (5m with 15m / 1h EMA50 side) - tested with and without in the replay.
5. Fee check and "not already stretched" (price past 2 SD in the signal direction = skip).
6. Cooldown per coin, then Quality Score decides size.
TP and stop: same as the current bot (SD levels, shifting). Only the ENTRY changes.

## 4. Quality Score points (starting guesses, tuned by the replay)
Clean market, bigger timeframe agrees, Z agrees, TSI line + signal + histogram agree, squeeze then breakout, volume rising, enough room to target (about 2x fee and more than the stop), not stretched. BTC moving sharply in the same direction gives alts a bonus.

## 5. Scenarios
| # | Situation | Decision |
|---|---|---|
| 1 | Trigger + Z + TSI agree | TAKE, full |
| 2 | Trigger + TSI agree, Z neutral | TAKE, half |
| 3 | Trigger, Z and TSI both against | BLOCK |
| 4 | Chop | BLOCK (unless breakout key) |
| 5 | Blocked trigger, then Z + TSI agree within 3 candles | TAKE late |
| 6 | Bottom busy, top quiet | IGNORE |
| 7 | Re-entry after stop-out | only if trend side is unchanged |
| 8 | Late chase (already past 2 SD) | SKIP |
| 9 | 3 losses on one coin | that coin needs a higher score (no pause) |

## 6. Repo map for this feature (found in Indian-main (77))
- backend/v2_scalp_ind.py: already computes EMA50, SD, Z, Z-SMA, TSI, signal, hist and the bot's EMA50 cross rule. REUSE it.
- backend/recovered_bot/app.py: entry gate `_extra_entry_block` (line ~473) and `_open_signal(..., bot_id=...)`. The hook goes here.
- backend/recovered_bot/strategy.py: Signal has `regime_cross_n` (EMA50 crosses in last 20 candles). Measured, not yet used as a block.
- Dual Bot (b2): dual_lab.py, dual_live.py, dual_bot_screen.dart. Pattern for a second paper bot with its own P&L. To be confirmed in C3 how bot ids are stored.
- backend/v2_store.py: candle table is `candles(symbol, interval, open_ts, o, h, l, c, v)`.
- backend/owl_sniper_*.py (about 70 files): the Sniper set already exists (regime, zsma, sdbands, mtf, tpsl, scalp...). Check these before writing anything new.

## 7. Parts
| Part | What | Files | Lines | Status |
|---|---|---|---|---|
| C1 | Filter brain: chop gate, breakout key, fee check, quality score, soft brake, late entry, skip_outcome, suggest_weights | chop_filter.py (232), chop_score.py (161) | est ~340, actual 393 | DONE, syntax-checked, NOT RUN |
| C2 | Replay 5m / 15m, today / month / all, cut-off sweep with train / test split, rally capture, net per trade (uses the bot's TP1-4 engine, not the simple skip_outcome) | chop_filter_lab.py + route | ~330 | waiting |
| C3 | Live PAPER bot b3 on 5m (OFF until switched on) with its OWN database chop_b3.db, decision log, Skip Ledger, verdict tracker, rule report, learning suggestion + OK route. The current bot and paper_trader are NOT touched (paper_trader only knows b1 / b2) | chop_bot.py (343), chop_ledger.py (118), api/chop.py (132), api/sniper_mount.py (+2) | est ~390, actual 595 | DONE, syntax-checked, NOT RUN |
| C4a | App tab part 1: FIRST row of More > Trading tools opens "Chop Bot (b3)". Header with ON/OFF switch (paper), tabs Today / Why. Today tab: day profit 5m (b3 live) and 15m (C2 replay of today, with a Run button) apart + rally missed / loss avoided; open b3 trades; closed trades; decision list (signal, TAKE/SKIP, score, rule, why, verdict) | frontend/lib/providers/app_provider_chop.dart (39), screens/chop_screen.dart (427), app_provider.dart (+1 part line), more_screen.dart (+2: import, row) | est ~230, actual 466 | DONE, brackets checked, NOT compiled, NOT RUN |
| C4b | App tab part 2: the Why tab (replaces the placeholder in chop_screen.dart): Skip Ledger + Missed Rally alarm, rule report, weight suggestions with the OK button (POST chop_apply, provider already has it), b3 vs current bot (needs the current bot's 15m trades from the existing trade routes), replay sweep table + Run buttons for 5m / month / all | screens/chop_why_tab.dart (384), chop_screen.dart (Why tab now `ChopWhyTab(main: _main)`, 1 import), app_provider_chop.dart (+3: fetchChopCurrentBot) | est ~250, actual 384 + 3 | DONE, brackets checked, NOT compiled, NOT RUN |

## 8. Review of the code the owner pasted (OwlSniper engine, study lab, tests)
Verdict: do NOT use as it is. Reasons:
1. Engine entry needs price ABOVE both EMAs and Z that was under -2 one candle ago. Those two almost never happen together, so it would almost never trade. It is a mean-reversion idea, not the owner's real signals (EMA50 cross, Z cross).
2. `execute_order` only prints and writes a text file. It opens no trade, has no exit and no position state.
3. The 85% accuracy gate is a number passed in from nowhere. 85% is not realistic for trading and would block everything (or be faked).
4. SQL reads columns `timestamp, open, high, low, close, volume` with no interval. The repo table is `open_ts, o, h, l, c, v` with an `interval` column. It would crash.
5. Study lab: Optuna tunes 8 numbers on 2000 candles of ONE coin with no train / test split, so it overfits. It scores the sum of 1-candle returns: no stop, no TP, no fee. That is not how the bot trades. The engine also ignores the tuned `z_bound`.
6. pandas, numpy and optuna are not in the repo requirements. They are heavy on Termux.
7. The tests import `backend.api.sniper` but never test the engine. They compare numpy with numpy, check 10/price*price, and compare two constants. They cannot catch a bug.
Worth keeping as ideas only: trend as the "boss", tuning numbers from data (done in C2 with a plain sweep and a train / test split, no new library), the short insight-card text.

## 9. Merge-time commands (Termux)
C3: nothing to edit by hand - api/sniper_mount.py already mounts api/chop.py (try / except, a failure only skips b3). The loop starts with the backend. b3 is OFF by default: turn it ON with POST /api/v2/chop_switch {"on": true} (the C4 tab will have the switch). It needs v2_candles_ws.py to be saving 5m candles and the file v2_api_enabled in the data folder. A coin needs about 400 saved 5m candles before b3 can decide on it.
None for C1 and C2 (no wiring; api/chop.py gets the lab routes by itself). Optional read-only replay in Termux: `python3 backend/chop_filter_lab.py --interval 5m --period month` (prints the result and saves chop_b3_lab_5m_month.json). It can take minutes. Optional read-only check after merge: `python3 backend/chop_filter.py --symbol BTCUSDT --interval 5m` prints the newest candle's decision.
C4a: nothing to run. Copy the 4 frontend files in place (the zip has them in the right folders; C4b adds screens/chop_why_tab.dart), build the APK as usual (the APK build is the first compile of the Dart). Open More, the FIRST row is Chop Bot (b3). The switch there is the only way b3 turns ON; it is OFF by default.
Each later Part adds its commands here. The owner runs them once at the end.

## 10. How we work (owner rules)
- Reply in plain English, short, like WhatsApp. ONE question at a time.
- Plan with files, lines and rounds in a table first. Code only after the owner says ok. When the owner names a part, build it right away.
- ONE cumulative zip with every file. README updated inside it each Part. Push nothing until the owner pushes once at the end.
- No tests between Parts. Python is only syntax-checked. Say plainly what was NOT run.
- Before any work say first: with tests or without tests, and why tests exist (catch bugs before they hit the app or paper money). Tell everything in Roman English.
- ONE zip per Part named owl_C<N>.zip, one Indian-main/ folder, with every file changed in earlier C Parts too (cumulative) + this README_CHOP.

## 11. C1 interface (what C2, C3, C4 call)
- `chop_filter.decide(candles, ind, i, htf_side=None, btc_move_pct=None, coin_losses=0, weights=None, p=None, late_from=None)` -> action TAKE / SKIP / NONE, size FULL / HALF / NONE, score, scenario (section 5 number), why, late_candidate, side, parts (9 fractions), states. `ind = v2_scalp_ind.compute(candles)` of ONE gap-free run; i = a CLOSED candle.
- A SKIP with late_candidate = True: keep {i, side} for 3 candles and call `decide(..., late_from={"i": j, "side": side})` on each next candle (scenario 5).
- `chop_filter.skip_outcome(candles, ind, i, side)` -> net_pct, exit, mfe_pct, final, label. final = False: ask again later.
- `chop_score.suggest_weights(rows)` rows = judged decisions in time order (`parts`, `net_pct`). `load_weights(path)` / `save_weights(path, w)`.
- Starting values (NV): chop = EMA50 moved < 0.25 SD in 10 candles, or 3+ crosses in 20, or last 8 closes within 0.5 SD of the SD middle; fee check = target >= 2 x 0.14%; stretched = zone >= 2 SD; FULL >= 70, HALF >= 50; brake +10 after 3 losses on one coin; late window 3 candles.
- NOT RUN: every function above. Only `py_compile` passed. The first real run is in C2.

## 12. C3 interface (what C4 reads)
- Database `chop_b3.db` (data folder, WAL) tables: meta (on), cursor, late, decisions, trades. b3 never writes the trading databases or v2_market.db (that one is opened read only).
- `GET /api/v2/chop` -> on, today / all {closed, wins, profit_usdt, taken, skipped, rally_missed_n / usdt, loss_avoided_n / usdt, skips_waiting}, open_trades (with last_px, upnl_pct, upnl_usdt), loop {last, turns}.
- `GET /api/v2/chop_log?limit=50` -> decisions (symbol, side, action, size, score, rule, why, parts, v_net, v_exit, v_label, verdict right / wrong) + closed_trades.
- `GET /api/v2/chop_report` -> rules (per rule: judged, right, wrong, usdt saved / made), missed_rallies (net 1% or more), learning (enough, rows, changes, current_weights, new_weights).
- `POST /api/v2/chop_switch {"on": bool}`, `POST /api/v2/chop_apply` (the OK button; saves chop_b3_weights.json only when train and test agree).
- Rules of b3 (NV, same as the current bot where simple): entry at the signal candle close, FULL 10 USDT / HALF 5 USDT 1x, one open trade per coin, opposite TAKE = REVERSED, stop = signal candle extreme, target = TP4 of the SD bands, stop wins if one candle touches both, BTCUSDT never traded, 40 newest coins, starts from the newest candle (no history replay).
- SKIP money is a what-if at full size after cost (chop_filter.skip_outcome). A SKIP verdict is final when the stop or target is touched or after 24 candles.
- Open item for C4: the b3 vs current bot comparison needs the current bot's 15m trades; read them from the existing trade routes, do not change paper_trader.
- NOT RUN: all of C3. Only py_compile passed. First real run = the first live 5m candle after b3 is switched ON.

## 13. C2 interface (what C4 reads)
- `POST /api/v2/chop_lab {"interval": "5m"|"15m", "period": "today"|"month"|"all"}` starts ONE background replay (409 if one runs). `GET /api/v2/chop_lab?interval=5m&period=month` -> job {running, done, total, error} + the last saved result of that pair (or null).
- Result: coins, days, split_ts (null if under 5 days), variants[] each with name, cuts, htf_block, all / train / test {trades, win_pct, avg_net_pct, profit_usdt}, rally_capture_pct, loss_avoided_pct, rally_missed_usdt, loss_avoided_usdt, verdict; best (a name or null); applied = false.
- The replay is fair: every variant has the same exits as chop_bot (stop = signal candle extreme, target = TP4, stop wins on a double touch, REVERSED on an opposite trade). Only the entry differs. Late entries (scenario 5) are included.
- 15m has no bigger-timeframe data in the store, so the htf variant is left out there and the htf score part is neutral (0.5).
- The cut-offs are NOT changed by the replay. To use a better cut-off the owner says so and the constants FULL_CUT / HALF_CUT of chop_score.py are changed (or a later Part reads them from the weights file).
- NOT RUN: all of C2. Heavy CPU: 40 coins x 30 days x 5 variants; it sleeps between coins. If it is too slow on the phone, run it with period today first.

## 14. C4a interface (what C4b adds to)
- Provider `AppProviderChop` (app_provider_chop.dart, `part of app_provider.dart`): fetchChop(), fetchChopLog({limit}), fetchChopReport(), fetchChopLab(interval, period), postChopSwitch(bool), postChopLab(interval, period), postChopApply(). Same answer rules as the Sniper fetches: the map, or {state: off / old / error}. Never throws. fetchChopReport and postChopApply are written but NOT used yet: they are for C4b.
- `ChopScreen` (screens/chop_screen.dart): StatefulWidget, polls /chop and /chop_log every 10 s while open, the 15m replay result (chop_lab 15m today) once and then every 60 s or every 10 s while a replay job runs. Last good replies are kept in static maps. Pull down refreshes.
- Tabs: `OwlTextTabs ['Today', 'Why']`. The Why tab is `_whyTab()` = a placeholder notice. C4b writes `ChopWhyTab` in screens/chop_why_tab.dart and `_whyTab` returns `[const ChopWhyTab()]`.
- Top-level helpers in chop_screen.dart are private (`_m _ml _n _s _usdt _px _ist`); C4b copies the ones it needs into its own file.
- 15m numbers on the top card are the C2 REPLAY (b3 itself runs on 5m only): it shows `current` next to the `best` variant (or `filter 70/50` when no best), with that variant's rally missed / loss avoided. Day for 5m = UTC day (set by chop_ledger.overview), times shown in IST.
- Open item for C4b: b3 vs current bot. Find the current bot's closed trades (existing routes; do not change paper_trader).
- NOT RUN, NOT COMPILED: everything in C4a.

## 15. C4b interface (the Why tab)
- `ChopWhyTab(main: <last /chop answer>)` in screens/chop_why_tab.dart. Created only while the Why tab is open: polls /chop_report every 10 s, the current bot calendar every 30 s, the replay result every 60 s (every 10 s while a job runs).
- Sections: Missed Rally alarm (rows of /chop_report missed_rallies, 1% or more), Skip Ledger (all-time rally missed / loss avoided / filter effect from /chop all), Rule report, Learning (weights now, proposed changes with train / test edge, OK button with a confirm dialog -> POST chop_apply), b3 vs current bot, Replay table (5m / 15m x today / month / all, Run button).
- b3 vs current bot reads GET /api/calendar?bot=b1 (existing route, read only; day = 5:30 AM IST, month totals). Not the same clock or size as b3 (UTC day, 10 / 5 USDT): the fair test is the replay table. paper_trader untouched.
- The OK button never writes by itself: the backend refuses unless enough rows (60+) and train and test agree.
- NOT RUN, NOT COMPILED: everything in C4b. ALL PARTS (C1 to C4b) are written; the first compile is the APK build, the first run is after b3 is switched ON.

## 16. Push note (6 Nov 2026)
- The phone watcher (tools/owl_auto.sh) pushes only a fixed list of files. README_CHOP.md was NOT on it, so this zip carries owl_auto.sh BUILD 48 (one name added to ALLOWED, nothing else changed). The watcher self-updates from the zip, so README_CHOP.md may reach GitHub with this push or with the next zip (every zip carries it).
- The owner only downloads the zip (owl_C4c.zip is the newest, cumulative C1 to C4b + owl_auto.sh). No Termux command.

## 17. Part E1 (6 Nov 2026): plain English for the b3 screens
- Owner said the b3 page was hard to read (jargon: "chop gate: chop: EMA flat, 6 EMA crosses in 20", score on every skip, "LOSS AVOIDED -0.45%" looked like a loss).
- NEW frontend/lib/screens/chop_plain.dart (155): pure text helpers `chopRuleName`, `chopPlainWhy`, `chopHeadline`, `chopShowScore`, `chopVerdict`, `chopExitName`, `chopSummaryLine`. The backend texts (chop_filter.py why, chop_bot.rule_of) are NOT changed; unknown texts fall back to the raw backend text. If a rule or why text is added in the backend, add its words here.
- chop_screen.dart: decision rows = symbol + side + time, a headline ("Skipped: Sideways market" / "Taken, full size"), one plain sentence, the score only for a taken trade or a score-too-low skip, a verdict pill (GOOD SKIP "it would have lost 0.45%", MISSED "it would have made +1.20%", WON, LOST); a summary line over the list ("Last 50 signals: 0 taken, 50 skipped. Main reason: sideways market"); closed trade exits in words (Stop hit / Target hit).
- chop_why_tab.dart: Missed Rally alarm and Rule report use the same friendly names (Skipped: ... / Taken: ...).
- Still to do: E2 (b3 vs current bot card says "b3 took no trade yet" and shows the current bot on the same signals), E3 (Sniper cards in plain words: owl_sniper_opp.py text + sniper_trade_card.dart).
- NOT COMPILED, NOT RUN.

## 18. Parts E2, E3, E4 and the day line (6 Nov 2026)
- E2 (chop_why_tab.dart): the "b3 vs current bot" card says "b3 has not taken any trade yet" and shows "No trade" instead of +0.00. NOT done: "current bot on the same signals" (needs signal-by-signal matching, not in the backend); the card shows the current bot's normal numbers and points to the replay for a fair test.
- E3 (Sniper, plain English): backend/owl_sniper_opp.py and api/sniper_opp.py now write plain lines ("Nothing to do. Right now it is down 0.92 USDT...", "Wait...", "Good time to take the profit...", "Consider switching..."), no R / KEEP / STAY / ROTATE words. Decision codes in the JSON are unchanged. This file WAS run with sample numbers. Cards: widgets/sniper_positions.dart, screens/sniper_trade_card.dart, screens/sniper_position_chart.dart (Stop / Target words, "open for X, closed after Y at most", USDT instead of R).
- E4 NEW backend/owl_sniper_winners.py + api/sniper_winners.py (GET /api/v2/sniper_winners, read only, cached 10 min, mounted by api/sniper_mount.py): how the WINNING past trades (Dual / Brain / main bot, learn-bridge examples) differed from the losers on the 4 numbers the win-chance model reads. Needs 30+ trades and 8+ of each side, else state TOO_EARLY. Run with made-up examples and with an empty data folder only; NOT run on real trades yet.
- E4 NEW widgets/sniper_winners_card.dart, placed in sniper_screen.dart as the fold "WHAT SNIPER LEARNED AND READY FOR REAL MONEY?": the 7-check graduation list (existing /api/v2/sniper_grad) as OK / NO / WAIT plus the winners-vs-losers lines. It never says "safe" and never promises profit. Provider: fetchSniperWinners in app_provider_sniper.dart.
- Day line: chop_screen.dart shows "Today: N signals, T taken, S skipped. The filter avoided A USDT of losses and missed B USDT of gains..." above the day card.
- Words: sniper_state_banner.dart EXPLORE -> PRACTISING, NOT LEARNED YET -> STILL LEARNING; sniper_gates.dart lanes PRACTICE / REAL MONEY.
- After pushing: restart the backend once (bash ~/owl_auto.sh restart) so the new route and the new Sniper texts load.
- NOT COMPILED (Dart), so the first compile is the APK build.

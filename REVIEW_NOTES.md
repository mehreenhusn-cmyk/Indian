# Vision AI - Rounds A + Z + B + C, reviewed and fixed (ONE zip)

Copy these files over the repo (same paths). Nothing from the bot's strategy, paper trader, protection or real-order files is touched. Vision AI stays paper only.

## What Grok built (kept)
- A: swipe between the 6 Vision tabs, "What the AI did today" card, plain pump/dump sentences, Seed block.
- Z: Vision chart now fetches 600 candles (was 450), so the black Z-SMA 200 line covers the whole Z pane; honest note when history is short; guide text says the line can be support OR resistance and how the two scripts fit; new tags zsma_near, zsma_bounce_with; level-study headline peeked into the prompt; note on the app's Z pane when the line has too few candles.
- B: own scanner file (ai_vision_own.py), /api/vision/compare, /api/vision/own, compare cards in the Results tab.
- C: ai_vision_exits.py (peak / gave-back stats), partial-profit helper, /api/vision/exits.

## What was wrong in Grok's zip (fixed here)
1. DELETED the Pump endpoints /api/vision/pumpdump and /api/vision/pumpdump/seed from api_server.py (Pump tab would be dead). Restored.
2. DELETED fetchVisionPumpdump and seedVisionPumpdump from app_provider.dart (Pump tab would not compile). Restored, plus the 3 new methods.
3. DELETED the skip-hindsight feature from ai_vision_lessons.py (record_skip, check_skip_hindsight, skip_stats) while ai_vision.py still calls them. Restored.
4. Brought back the side-blind tags after_pump_top / after_dump_bottom (replacing chasing_move). Removed again.
5. Undid my earlier "NOT JUDGED" card fix in the tab and weakened/removed my regression tests. Restored.
6. Own scanner could never run: it read a module that does not exist (market_watch) and called a function that does not exist (_judge_one). Now uses the bot's cached watchlist (status.get_watchlist, the top-10 gainers + top-10 losers) and the real _process_signal. Timeframe now read from the bot's "timeframe" setting.
7. Round C was only half wired: the review prompt never offered PARTIAL / TRAIL. Now the AI can answer HOLD, PARTIAL (25-75%, once, only while in profit after fees), TRAIL (stop only tighter) or EXIT; the code refuses bad requests and writes it in the trade notes.
8. The "today" card also counted own-scan signals as bot signals. Now bot-only.
9. Rule evidence counted own-scan trades together with bot trades. Now rules are proven on bot-signal trades only; each lesson carries its source.
10. zsma_bounce_with was just a cross (same as z_cross_ok). Now: Z came onto the black line from the favourable side and moved back away (support / resistance held).
11. Added the missing "AI own scan" switch + one line on the Live tab; removed a refresh wrapper that could never fire.

## Tests run here (all pass)
test_vision_final_checks (new, strict: regression guards, partial P&L with planted numbers = 0.20 USDT, PARTIAL once and only in profit, TRAIL never loosens, every own-scanner cap and skip rule, bot-only card, bot-only rule evidence), test_vision_summary, test_vision_zsma, test_vision_own, test_vision_exits, test_vision_notebook, test_vision_indicator_use, test_vision_context, test_pumpdump, test_ai_isolation, test_variant_lab. 61 of 66 repo tests pass; the other 5 (daily_report, india_telegram, net_pnl, period_pnl, smooth) fail the same way on the untouched original repo (missing fastapi etc. in this sandbox), so they are not caused by these changes.

## NOT verified / known limits
- Flutter was NOT compiled here (no Dart SDK). Brackets balance and every name was checked by hand against the theme. Run the GitHub build; send the log if Dart shows an error.
- The own scanner and the PARTIAL path were tested with stubbed AI calls, not with a live key.
- Round C does not yet record the SD zone where a trade peaked (field stays empty); stats are: reached +1%, gave back, target touched, per source and side.
- Own-scan decisions also appear in the Signals tab list (no source label there yet).
- Own scan is OFF by default and uses AI quota (cap 12 calls/hour, daily own loss cap 15 USDT, max 3 open). Switch is on the Live tab.
- App chart Z-SMA: defaults are ON; if your saved gear setting is off, use gear > Z-score > "Show Z-score SMAs" + "Z-SMA 2", or Reset.

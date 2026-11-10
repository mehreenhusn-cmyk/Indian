# README_OWNER - owner problem + what is done (10 Nov 2026)
For any Claude that picks this up. Read this first. Owner = Hussain. Language: simple Roman-script English / Hinglish, WhatsApp style, short.

## Owner rules (also keep in README4)
- Short, simple replies. Next-work lists always as a TABLE. After each Part say how many files the NEXT Part needs.
- Big work: say files + lines first, start only after "ok". Part of ~1000 lines = two parts of ~500.
- Every zip is CUMULATIVE (all files changed so far in the chat). Zip paths must start with `Indian-main/` or the push script ignores it.
- Do NOT write or run tests. Compile check only. Durations over 60 min as "1 h 4 min". Trading day = 00:00 UTC (5:30 AM IST).
- Never delete trade data. Switching a worker off is fine (ctl file `enabled: false`), never delete.

## The owner problem (his words, short)
1. He reads the chart (SD bands + Z-score + EMA) and knows which signal is fake and which is real. The bot takes every signal. Teach the bot his "state" view: SIDEWAYS / UP / DOWN, and when a signal is real.
2. Do not miss big rallies (long from the bottom, short from the top). Fake signals in sideways must be cut.
3. His booking was always bad. He wants max profit on a rally AND money freed fast for the next trade.
4. Everything else (Brain, Dual Lab, Ping, PA/Volume layers) only eats RAM. Focus = main bot + Filter Lab study.

## Findings from old data (Filter Lab, MAIN bot, ~4300 trades, 7 Oct - 9 Nov)
- Win rate 13.5%, net about -7790 USDT. Avg best profit 18.8% ROI, avg give-back 20.7%.
- 1320 replayed trades: 1113 were in profit at some moment, 942 of those ended in loss. Bot kept only 27.8% of the profit.
- 499 trades touched TP1; 357 (71%) came back to zero or loss.
- No single exit rule was BETTER in both halves (trail hurts big runners).
- Part 5C (split booking, 1323 trades): **30% at TP1 + TRAIL_25 = BETTER in train AND test**, runners not hurt, money locked 1 h 4 min instead of 1 h 42 min, net -2940 -> -1840. 5m only: 30% at TP1 + EMA50 with stop to entry also BETTER. Still net negative: entries must improve. Replay = hindsight, so log mode first.
- Part 4: 112 single filters tried, 0 PASS (every one that helped also killed rallies). Part 6 state words: ENTER only 2.4% of trades, not enough proof.

## Ideas still NOT tested (owner + Claude)
| # | Idea | Status |
|---|---|---|
| 1 | Right after a rally, signals are mostly fake. Wait for a pullback to EMA50 / band, do not chase. | not tested |
| 2 | Slow climb from the bottom (EMA slope up, price touches EMA50 and goes on) = good phase. | not tested |
| 3 | Do not block when slope is strong and Z is above Z-SMA (protect runners). | not tested |
| 4 | Entry on the candle AFTER the signal: limit at EMA, or at the signal candle's entry price (maybe with a 1-3 candle timeout). Risk: fast rallies never fill. | not tested |
| 5 | Book 30% at TP1, rest trail 25% (from 5C). | tested on old data, next = log mode on the bot |
| 7 | Z lookback test: bot uses Z_LEN 200 and ZSMA 200 (copied from the video). On 5m crypto 200 candles = 16 h 40 min, so one pump stretches mean/SD for the whole next day (bands go wide, Z looks calm = fake "sideways"). Compare 50 / 100 / 200 / 300. | not tested |
| 8 | Video rule set (owner built the indicator from it): trend = Z above Z-SMA + price above EMA50; wait pullback to EMA50; entry on price-action close (AMD 3-candle, trendline break); SL swing low; 1:2 target, book 70%, trail 30%; Z spike beyond 3 bands = pullback trade, not a trend entry. | notes saved by owner, not tested |
| 9 | TradingView "Z-Score & Stats" (kingshukghosh71): mean reversion at Z beyond 3.5 + volume contraction, divergence. Different idea (reversal), risky on pumps. Only the volume-contraction filter looks worth testing. | not tested |
| 6 | Part 6B (v2_f6b_entry.py, built 10 Nov, not run yet): entry types B3 / C12 / D3 (limit at signal close or EMA50, with timeout) vs real entry, Z lookback 50/100/200/300, rally phase (run-up, distance from EMA50, Z spike). Runs last in the study. | built, waiting for VPS run |

## Done / closed in this chat
- App shows OFFLINE / delay: cause was VPS RAM (swap full) + Smart Brain worker. Brain, Dual Lab, PA, Volume layer, Ping switched OFF on the VPS. RAM used went 1556 -> 442 MB.
- App backend URL = VPS Tailscale IP, port 8000 (not the public IP). Phone VPN on = app offline.
- Part 5B crashed on a `%` in a format string (v2_f5b_exits.py): fixed. Report cap raised to 120000 chars per Part.
- Filter Lab tab has a "Filter Lab report" card (Share / Copy) = one text file with every saved Part. Send it to any AI.
- F5c (v2_f5c_booking.py) added to the study run (runs last).

## How the owner's indicator was made (important for any Claude)
The owner built his indicator (SD bands + Z-score + Z-SMA + EMA50, the "Special 13" / Trading Combine) after watching a YouTube video, "This Indicator tells you EXACTLY when to BUY and SELL" (Z-Score Probability Indicator, Hindi), and a YouTube Short (link not readable by Claude). The video's own settings were Z lookback 200 and Z-SMA 200 (chosen there "for clarity"), not tuned on crypto 5m. So the lookback and the 70/30 booking come from a video, not from data. Test them, do not trust them.
The owner's video notes are in the .md files he gave (Z-Score Probability Indicator notes, AMD pattern notes). The prompt that summarises the video strategy (copied as the owner gave it):

> Create a detailed educational trading video explaining the Z-Score Probability Indicator on TradingView. Show how to add the indicator, set Lookback Length to 200, set SMA Length to 200, hide unnecessary labels, and change the Z-SMA color. Explain the Z-score formula using current price, average, and standard deviation. Show red, yellow, and green bands from +3 to -3 and explain that the green zone may indicate sideways movement while values outside it may indicate a trend. Explain that histogram above the Z-SMA shows stronger momentum and histogram below the Z-SMA shows weakening momentum.
> Add a 50 EMA and demonstrate the strategy: first identify a clear trend using the Z-score and 50 EMA; then wait for price action near the 50 EMA, such as a trendline breakout, strong candlestick formation, or AMD pattern consisting of Accumulation, Manipulation, and Distribution. Enter after confirmation, place the stop-loss below the previous swing low for a long trade or above the previous swing high for a short trade, target at least 1:2 risk-reward, book 70 percent at 1:2, and trail the remaining 30 percent.
> Include examples of long trades, short trades, Fibonacci 0.618 confirmation, Type-1 AMD patterns, double tops, trendline breakouts, Z-score spikes, and short-term pullback trades. Demonstrate the secret Plot Type setting by changing the Z-score display from Area to Candles. End by explaining why 200 is preferred for clarity and by adding a strong educational disclaimer that the content is not financial advice and trading involves substantial risk.

AMD = 3-candle pattern (Accumulation, Manipulation, Distribution). Bullish: candle 1 red, candle 2 sweeps the low, candle 3 green; bullish rule = candle 1 open higher than candle 2 open. Entry at the close of candle 3, stop below the lowest wick of the 3 candles, 1:2 target.

## Existing facts from Part 2 (no new run needed)
- Sessions (UTC): ASIA 00-08 net -870 (win 15.6%), EUROPE 08-16 net -2179 (14.7%), US 16-24 (= 21:30 to 05:30 IST) net -4769 (win 11.4%, fake 24.9%). The US session is the worst.
- Top-10 list / rank could not be matched for most trades (3039 of 4362 had no list data), so a rank test is not possible yet.
- LONG net -5192, SHORT net -2625 (both win about 13.5%).

## Source notes the owner gave
- Z-Score Probability video notes (Roman English .md), AMD pattern notes (.md), TradingView Z-Score & Stats page. The Shorts video the indicator came from could not be opened (YouTube blocked); owner should write its steps as a .md.

## Build progress (green circle = done)
| Part | What | Status |
|---|---|---|
| F5c | split booking study (30% at TP1 + trail 25%) | 🟢 done |
| 6B | entry lab (lookback, B3/C12/D3 entries, rally phase) | 🟢 done, ran 10 Nov. Its entry result (+17,000 USDT) looks too good = replay bias, do NOT trust it |
| Bot Part 4 | US-session gate, backend/v2_f9_session.py, setting f9_session_mode (default log = writes only, stops nothing), hours f9_session_utc "16-24" UTC = 21:30-05:30 IST. Hook in recovered_bot/app.py | 🟢 done (10 Nov), log mode |
| Bot Part 5 | split booking INSIDE the paper bot (paper_trader.py pays 100% at one target today, no partials; needs careful PnL change, default OFF) | ⚪ next |
| Bot Part 6 | daily bot report: trades, win %, net, new vs old | ⚪ planned |
| Bot Part 7 | 7 days paper, change nothing | ⚪ planned |
| Bot Part 8 | AMD / video rules test (only if still minus after 7 days) | ⚪ optional |

Owner wants (10 Nov): bot runs continuously, skips useless trades, takes good ones and books profit. Fake entries and no profit booking are the problems. Build in Parts. After each Part list the next 4-5 Parts (files + lines).

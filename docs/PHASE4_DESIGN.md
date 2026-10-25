# Phase 4 design: how Brain lessons reach the main bot (design only, no code)
Rule for everything below: the main bot and Dual Bot v1 keep working as they are until the Brain has earned trust. Paper only. Only your two indicators (main chart EMA50 + SD bands, Z/TSI pane). Nothing else is added.

## Where we are
Brain reads Dual Bot data and gives: clean score, agree/disagree, look-alike win %, trust meter, luck test, risk numbers, exit opinion (shadow).

## Step A: Brain only watches (now)
No change to the main bot. Wait until the app shows all of these:
- Trust meter: 30+ judged trades and a positive edge
- Luck test: "Looks real" (not "Could be luck"), and it stays that way for a few days
- Risk card: worst-case drop is something you can live with
- Exit opinion hit-rate above 60% on 30+ checked opinions
Why: one lucky week must not change a working bot.

## Step B: Brain advises on main-bot signals (shadow) - DONE as "What if the bot had listened?" card (Part 9)
For each main-bot signal the Brain writes "would take / would skip" next to it. The bot still takes everything. The app shows, after 2 weeks, bot result vs bot-if-it-had-listened. Same idea as Bot vs AI, but with measured numbers.
Needs: ~1 small file (a read-only hook), 1 card. About 150 lines.

## Step C: Brain skips only the clearly bad ones (paper) - code is in the backend but there is NO switch in the app (removed, so it cannot be turned on by mistake)
Only when Step B shows the filtered version earned more AND had a smaller worst drop. The Brain may skip signals it scores as clean score low + win % low. It never opens its own trades here.
A switch in Settings, default OFF, so you can turn it off in one tap.
About 3 files, 200 lines.

## Step D: Exit advice used on trailing (paper)
If exit opinion keeps being right, the main bot may use "HOLD / EXIT IS FINE" to decide when to trail the stop. Same switch style, default OFF.

## Trust rules (when to stop trusting)
- Trust meter falls back to "learning" or luck test says "Could be luck" -> filter turns itself off, bot goes back to normal.
- New data: the Brain keeps using the rolling memory, so it follows the market, but a sudden drop in the newest 100 vs older trades shows a warning.

## Later (not planned now)
- Gold / other assets: only after Step C runs stably for weeks. Needs its own data collection first. Same two indicators.
- Live mode: last. Needs Step C and D proven on paper, then small size, then a separate decision from you.

## Estimates
Step B: 2 files / ~150 lines. Step C: 3 files / ~200 lines. Step D: 2 files / ~120 lines.
Total after this plan: about 7 files, ~470 lines. Each step is its own zip, started only on your OK.

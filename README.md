# Owl Terminal

Crypto paper-trading app (Flutter) + Python backend. Dual Bot v1 collects trades, Smart Brain learns on the side.

**Claude / anyone reading this repo: open `docs/PROJECT_STATUS.md` first.**
It lists what is done, what waits for data, and the READY CHECK numbers.
If those numbers are reached, tell the owner plainly: "Enough data is collected. Step D (exit advice trail) / Brain skip can start now. Shall I build it?" Build only after his ok.

## Why SQLite and WebSocket are NOT done yet (decision 26 Oct 2026)
- Dual Bot v1 is the running data collector (500-600 paper trades a day). It saves everything in `dual_lab_data.json`. Smart Brain and every report read that file.
- Moving to SQLite changes HOW Dual Bot saves data. If it is done while the bot runs, data can get lost, doubled or mixed up, and the Brain would learn from broken numbers.
- WebSocket for open trades / Brain changes how the app gets data. The backend froze once when heavy file reads ran on its main loop, so it must be done slowly, after the screens are good.
- So: first collect clean data for 2-3 weeks, keep Dual Bot untouched. Then check the file size (`ls -lh $(find ~ -name dual_lab_data.json 2>/dev/null)`). If it is under about 20 MB, keep waiting.
- When the file gets big or slow: move to SQLite in a copy first, compare the numbers with the JSON, and only then switch. Never change Dual Bot saving and the app in the same step.

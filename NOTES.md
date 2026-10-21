# Round E + Round F merged (reviewed and fixed)
Copy over your repo (Indian-main (7) with A/Z/B/C). Only changed files are in this zip.

## Round E - Vision Days (Grok, reviewed: clean)
Today first on Live tab (day resets 5:30 AM IST), Yesterday/older day chips, signal timeline, 14-day history table.
Files: backend/api_server.py, backend/recovered_bot/{ai_vision.py, ai_guard.py (my fix: Grok said it added ai_vision_days.py to the guard list but did not), ai_vision_days.py (new)}, frontend/lib/{screens/vision_tab_screen.dart, providers/app_provider.dart}, test/test_vision_days.py

## Round F - India live data speed (Grok + my fixes)
Fast option prices, chain/paper live LTP, speed line under chart, lock-free candles.
My fixes (Dart build-breakers): added _onTickPrices, _onPosTicks, _showSpeed; chain _load used wrong variable (d -> ch); chain and paper now show live option price.
Files: backend/{india_api.py, test_india_speed.py}, backend/recovered_bot/{india_runtime.py, fyers_provider.py}, frontend/lib/{services/india_ticks.dart, screens/india_chart_screen.dart, screens/india_option_chain_screen.dart, screens/india_paper_screen.dart}

## Tested
Merged on your repo: 64 tests pass; the same 5 fail on your original repo too. Python compiles.
## Not tested
Flutter was NOT compiled. Run the GitHub build and send the log if Dart shows an error.

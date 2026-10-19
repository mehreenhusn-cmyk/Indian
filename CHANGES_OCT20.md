# Oct 20 update on top of repo (26): India part 1 (fast data) + free keys (4 slots)
Copy over your repo (same paths). Strategy, paper trader, real orders are NOT touched.

## India fast data (from india_part1_fast_data.zip, unchanged)
/api/india/ticks, lock-free candles, chart moves with every tick, wrong-index spinner fixed, one line under the chart says where prices come from.

## Free keys: 4 slots, shared load
- Settings > AI Assistant: main key + Backup key 1, 2, 3 (provider: mistral / groq / gemini / openrouter). Empty key = slot unused.
- Calls are shared (round-robin) between ready keys instead of emptying the first key first. A key with a quota answer pauses by itself.
- "AI Calls" card lists every key (Main, Backup key, Backup key 2, Backup key 3).
- Limits are per account/project at the provider, so 3 keys from the SAME account do not add quota. Use different providers.
- openrouter default model is a guess (free names change): if it says 404, type a model name in the model setting.

## Backend start
backend/start_forever.sh v2: waits longer after repeated fast crashes and writes CRASH LOOP + reason to ~/owl_backend.log.

Files: backend/{api_server.py, start_forever.sh, india_api.py, test_india_ticks.py}, backend/recovered_bot/{ai_vision.py, settings_store.py, india_runtime.py},
frontend/lib/{screens/settings_screen.dart, screens/vision_tab_screen.dart, screens/india_chart_screen.dart, services/india_api.dart, services/india_ticks.dart (new)}, test/test_vision_notebook.py
Tests: python3 test/test_vision_notebook.py ; python3 test/test_variant_lab.py ; python3 backend/test_india_ticks.py
Flutter was NOT compiled here. Run the GitHub build and send the log if Dart shows an error.

## Round 2 (Oct 20): Backend panel, light by default, compact Settings, settings backup
- Swipe from the LEFT edge: new BACKEND panel (replaces the locked "Exchange" box): running/not answering, uptime, which zip is live and when it was deployed, restarts today, crash loops, speed (SLOW if ping > 800 ms), last problems from the backend log. "COPY" puts a text report on the clipboard.
- Backend: GET /api/ops (new recovered_bot/ops_status.py), GET/POST /api/app_prefs.
- New app installs start in LIGHT theme (dark only if you chose it).
- Theme + sound choices are copied to the backend (owl_data/app_prefs.json). A freshly installed app restores them by itself (never overwrites a choice made on that phone). Trade settings were already kept by the backend.
- Settings page is more compact: smaller cards, smaller top box (no extra title line), less empty space.
Files added/changed: backend/{api_server.py, recovered_bot/ops_status.py (new)}, frontend/lib/{widgets/backend_status_panel.dart (new), widgets/owl_drawer.dart, widgets/settings_group.dart, screens/settings_screen.dart, providers/app_provider.dart}, test/test_ops_status.py (new)

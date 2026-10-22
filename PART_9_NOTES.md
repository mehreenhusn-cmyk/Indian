# Part 9 (build 2026-10-22-part9). Only changed files. Put them over your Part 6-8 repo.
1. Welcome screen: the time of the last welcome is now saved in a FILE in the app folder (the phone's settings storage fails on your phone, which is why
   it repeated and why my earlier fix hid it completely). Shows: on a fresh install, on the first start of every new build (buildId in
   owl_welcome_overlay.dart - change it when you ship a new build), and then once every 12 hours.
2. AI Own tab: new top card "what is it doing?" - ON/OFF/paused, coins checked, AI asked, taken, AI said skip, no setup, open/closed/profit,
   AI calls this hour with next slot, and the most common reasons it did not trade. Data: own.summary in /api/vision/day_view (ai_vision_own.py).
3. AI keys: the automatic switch already exists (main > backup > backup2 > backup3, a key that hits its quota is paused and the next one answers;
   if all are out, signals wait and stop-loss keeps working). Nothing to change; add keys in Settings > AI Assistant.
Tests: test_part6/7/8/9 and the Vision tests pass. Flutter not compiled.

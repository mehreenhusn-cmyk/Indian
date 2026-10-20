# Pump/Dump update - checked and fixed (Oct 21)
Copy these files over the repo (same paths), restart backend, run the GitHub build.
Bot, strategy, paper trader and real orders are NOT touched.

## Build breakers fixed (this is why GitHub failed)
- ai_assistant_screen.dart: stray script text at the end of the file removed; p.background -> p.bg; OwlAmbientBackground used as a Stack layer (it has no child).
- vision_pumpdump_view.dart (new widget would have failed the next build): p.card -> p.surfaceElevated, AppSpacing.lg -> AppSpacing.l, OwlPressable/OwlRefresh -> OWLPressable/OWLRefresh.
- vision_tab_screen.dart: tab label shortened to "Pump" (6 tabs did not fit).

## Logic bugs fixed in ai_pumpdump.py
- One pump was counted many times (n was fake: 64 events from 10 real ones). Now one pass, same leg is never counted twice (test: 1 pump + 1 dump).
- "Before" numbers were taken at the TOP of the pump. Now: before = start of the move, at_top = trigger bar.
- Detection is causal (uses only candles up to the trigger bar), so stats are not biased by hindsight.
- Seed button: first coin blocked all other coins for 7 days -> now per coin. Seed used only 450 candles (~4.7 days) -> now 1500 (~15 days, the max one call gives; the old text said 30 days).
- Playbook shows "SMALL SAMPLE" under 20 events; added TSI-vs-signal and Z-vs-Z-SMA buckets.
- New notebook tags were not side-relative (buyers_control etc. mixed BUY and SELL trades) -> replaced by flow_with and chasing_move.
- ai_pumpdump.py added to the ai_guard read-only list. Widget shows an error instead of an empty screen when the backend is old.
Tests: python3 test/test_pumpdump.py (strict now), test_vision_notebook.py, test_ai_isolation.py, test_variant_lab.py pass. Flutter not compiled here (no SDK) - bracket balance + every name checked against theme/widgets.

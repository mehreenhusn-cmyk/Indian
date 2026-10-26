# Part 1: Brain learns by itself (paper only)
- smart_brain.py: scans TODAY's top-10 gainers + top-10 losers (not old coins). Own lessons: a setup mix the Brain lost on is not repeated, a mix that worked is repeated. Newer trades count more.
- brain_own.py: stages by judged own trades: learning (0-99, loose) -> medium (100+) -> quality (300+, strict). Max 40 new own trades per day (day = 5:30 AM IST). Stage + lesson saved on each trade. Summary has stage + trades left for next stage.
- test_smart_brain.py: 86 checks OK. Other brain/dual tests OK.
- NOT touched: Dual Bot trading code, dual_lab_data.json, Vision AI, strategy files. BTC is not scanned by the Brain (kept separate).

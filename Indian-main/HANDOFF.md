# HANDOFF - Strategy Doctor work (Indian-main repo) - for any Claude/AI that continues

Owner: Hinglish/Hindi speaker, wants replies in English, casual WhatsApp style. Bot = Flutter app + FastAPI backend (Termux phone).
HARD RULES: never change strategy/trade rules (strategy.py, entry_context.py, protection_manager.py, paper_trader.py exit logic,
execution_router.py, binance_trader.py, tradebulls_client.py, fyers_client.py, india_broker.py order logic, india_options.py).
Doctor is READ-ONLY, suggestions only. Deliver updated files only, in one zip. Do not share backend/.env.

## Problem found
India Doctor hung: `india_runtime._loop()` slept up to 30s and did broker REST calls while holding `self.lock`; Doctor/stats/trades/positions
need the same lock -> app 8s timeout -> endless spinner. Crypto side is healthy (CPU 1.6%, broadcast 10ms). No language rewrite needed.

## DONE (all in this zip, tests pass)
1. `backend/recovered_bot/india_runtime.py` - lock fix: sleep/keepalive/broker fetches outside lock, `_stop_evt` wakes sleep on Stop,
   `_prewarm()` fills provider cache outside the lock (same calls on_tick/runner make), `_fast_loop` also prewarms. Old code: Doctor 9.8s
   when market closed; new: ~1ms. Test: `test/test_india_lock.py` (`python3 test/test_india_lock.py` -> PASS).
2. `backend/recovered_bot/doctor_verdict.py` (NEW) - Verdict: profit leakage, hold time, time of day, index, CE/PE, timeframe, SD zone,
   TSI x SD zone, TSI/Z bands; each group checked older 70% vs newest 30% (confirmed_bad/good only if both halves agree); "not enough data" < 30 trades.
   `studies_lines()` (crypto) only PEEKS at cached ai_reading / ai_exit_study / ai_level_study headlines (never computes -> stays fast).
3. `india_doctor.py` - attaches `rep["verdict"]`, passes new tags (z_band, tsi_band, tsi_with_trade, z_with_trade).
4. `strategy_doctor.py` - crypto `build()` attaches `rep["verdict"]` (with studies).
5. `india_bridge.py` - `indicator_tags()` RECORD-ONLY Z/TSI tags saved with each new India trade (try/except, no decision uses them).
   Only NEW trades get them; old trades are left out of TSI tables.
6. Flutter: `frontend/lib/widgets/doctor_verdict_card.dart` (NEW) + 5 lines in `screens/strategy_doctor_screen.dart` (shows card for India and crypto).
   Screen already had timeout + Retry.
Tests: `test/test_doctor_verdict.py`, `test/test_strategy_doctor.py`, `test/test_india_lock.py`, `backend/test_india_part4.py` (run each as a script; pytest not installed).

## NOT DONE / NEXT (in order)
A. Flutter was NOT compiled (no SDK where this was built). Run `flutter analyze`/build; fix any error in doctor_verdict_card.dart
   (uses context.palette / context.type / AppSpacing from theme/app_theme.dart).
B. Exact TP1-vs-TP4 for India needs each trade's price path (not recorded). Needs a small change in a trading file (india_paper.py,
   record-only path/peak samples) -> ASK THE OWNER FIRST.
C. Run Doctor on the owner's REAL India paper-state file (closed trades) - all tests used fake trades. Ask owner to upload it.
D. Optional: `/api/system` stage timings, price-delay meter, watchdog (nice-to-have, Stage 3 of earlier plan).
E. status() in india_runtime may still call Fyers REST under the lock on a cold cache (measure first; only fix if >500ms).
F. Re-check /api/system during market hours (earlier numbers were taken with market closed).

---
## REVIEW + FIXES (second pass, 2026-10-17) - read this first
Verified on a staged copy of the repo with the files in this zip:
- Lock fix: old code made the India Doctor wait 9.8 s (market closed) / ~2 s (market open, slow broker); new code ~1 ms. With a slow-broker
  mock the new code makes ZERO broker fetches while holding the runtime lock (old: all of them). Stop wakes the sleeping loop instantly.
- Same trades: with the same random seed on demo data, old and new loop closed identical trades (319 vs 319, same pnl/reason/order).
  NOTE: the runtime draws its demo seed in __init__, so seed `random` BEFORE building IndiaRuntime when comparing.
- DEFECT FOUND AND FIXED in doctor_verdict.py: the first version called a group "confirmed" when its average was negative (or positive)
  in both halves. On pure-noise trades that flagged ~70% of groups (142 of 200). `_judge` now needs the group to differ from the REST of the
  trades by z>=2.0 on the older 70% AND z>=1.64 on the newest 30% (same bars as strategy_doctor), min 15 old / 5 new trades.
  Noise now: ~0.7% (4 of 600); the planted 09:15-10:30 leak is still found (tests/test_verdict_noise.py).
- Record-only Z/TSI tags (india_bridge.indicator_tags): 0.7 ms, never raises, no decision reads them. Only NEW trades get them.
Tests (run each as a script from the repo root): test/test_india_lock.py, test_india_lock_open.py, test_verdict_noise.py, test_doctor_verdict.py,
test_strategy_doctor.py, test_part2_india.py, test_part1a.py, backend/test_india_part4.py, and
test_india_demo_equivalence.py <path-to-OLD-india_runtime.py> (1-2 min).

## STILL OPEN (in this order)
1. Flutter NOT compiled anywhere yet: run `flutter analyze` and fix anything in widgets/doctor_verdict_card.dart (or let GitHub Actions build and read the log).
2. Run the Doctor on the owner's REAL India paper state (closed trades) - every test used synthetic trades. Ask the owner for the file.
3. status()/ticker()/summary() in india_runtime can still hit broker REST under the lock on a cold cache (worst ~1.5 s). Measure first; fix (spot snapshot) only if > 500 ms.
4. on_signal() (rare, only when a signal fires) can still fetch contracts/option price under the lock on a cold cache.
5. Exact TP1-vs-TP4 for India needs each trade's price path (not recorded) -> small record-only change in india_paper.py. ASK THE OWNER FIRST.
6. Re-check /api/system during market hours (the numbers seen so far were taken with the market closed). Optional extras: price-delay meter, watchdog.
Never share backend/.env (it was inside the original zip).

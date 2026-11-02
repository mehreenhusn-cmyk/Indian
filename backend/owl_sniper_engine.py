"""owl_sniper_engine.py - OwlSniper RE-EXPORT (Round 17). The real code now lives in 4 small files; this file only keeps the OLD import name alive.
  owl_sniper_engine_a   maths (SMA / EMA / population SD / Z / TSI)        owl_sniper_engine_b   features, regime, raw signal, stop line
  owl_sniper_engine_c1  fee + slippage simulator, whole-day train / test    owl_sniper_engine_c2  SD-length search + class OwlSniperEngine
Old callers (owl_sniper_prob.py, owl_sniper_feed.py) still write `import owl_sniper_engine as E` and keep working.
TRAP (known): the OLD first_valid(S) took a series DICT, Part A's first_valid(list) takes a list. The old name is therefore mapped to warmup_end(S) of Part B.
Nothing is traded and nothing is saved here. CHoCH and BOS stay excluded."""
from owl_sniper_engine_a import sma, sma_any, ema, ema_any, pstdev, tsi_series, zscore, sd_bands            # noqa: F401
from owl_sniper_engine_b import (DEFAULTS, EXCLUDED, to_series, build_features, regime_at, regime_counts,   # noqa: F401
                                 sd_price, stop_price, raw_signal, latest_snapshot, warmup_end)
from owl_sniper_engine_c1 import (TEST_FRAC, MIN_DAYS, MAX_HOLD, MAX_SL_PCT, MIN_SL_PCT, MIN_TRAIN_TRADES, MIN_TEST_TRADES,  # noqa: F401
                                  T_NEEDED, MARGIN_FRAC, SD_CURVE, cost_pct, day_of, split_by_days, simulate_trade,
                                  run_period, stats_of, prep_sets, trades_for)
from owl_sniper_engine_c2 import sample_cfg, search_params, calibration_lines, OwlSniperEngine              # noqa: F401

VERSION = "owl_sniper_engine 3 (re-export of engine a / b / c1 / c2)"
first_valid = warmup_end            # old name, old meaning (takes the series dict S, returns the first index where every number exists)

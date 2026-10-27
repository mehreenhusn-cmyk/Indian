"""dual_tp_ext.py - Part H2: EXTRA take-profit levels for NEW Dual Bot trades (paper only).

The bot's ladder (strategy.calculate_tp_levels) stops at the +3 SD band (short: -3 SD), and when the entry is already
high the first four targets are all the same level. A rally often runs past that band, so the trade was closed too early.
Here every new Dual trade gets N_EXTRA more targets: the next SD bands further out in the trade direction, so the trade
can stay open above (below) the top band. Nothing else changes: same entry, same stop, same exit rules.

extend(tps, d, mean, sd) -> the 4 bot levels + up to N_EXTRA further SD levels. Any problem returns the original list.
Only the Dual Bot uses this (dual_lab.py hook). The main bot, strategy.py and the Brain's own trades are not touched.
Test: cd backend && python3 test_dual_tp_ext.py
"""
N_EXTRA = 3          # how many extra targets (TP5, TP6, TP7). Raise here, nothing else to change.
GRID = range(-9, 10)  # SD bands considered: mean + k * sd


def extend(tps, d, mean, sd, n_extra=N_EXTRA):
    try:
        base = [float(x) for x in tps]
        if len(base) != 4 or mean is None or not sd or sd <= 0 or n_extra <= 0:
            return list(tps)
        far, eps = base[3], sd * 1e-6
        grid = [mean + k * sd for k in GRID]
        if d > 0:
            more = sorted(v for v in grid if v > far + eps)
        else:
            more = sorted((v for v in grid if v < far - eps), reverse=True)
        return base + more[:n_extra]
    except Exception:
        return list(tps)

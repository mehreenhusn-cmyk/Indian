"""owl_sniper_feedall_feat.py - OwlSniper FEED EVERYTHING, part 2 of 2 (R2). PURE: no file, no network, no order code. Does not change any indicator maths.
It turns ONE example (feature row + label of owl_sniper_bridge_label.join) into a WIDE number list, so the Sniper can learn from more than the old 4 numbers.
Every number is turned so that "+" means "with the trade direction". A missing number becomes 0.0 and is COUNTED (never hidden). Nothing is read from the label (no look-ahead).
API: wide_vec(ex) -> (list, n_missing), sd_pos(ex), tsi_zone(v), WIDE_FEATS (names, same order as the list)."""

import math

VERSION = "owl_sniper_feedall_feat 2 (R30)"
TSI_HOT = 25.0                       # |TSI| above this = stretched zone (a plain, visible cut-off; the model decides what it means)
WIDE_FEATS = ("z_dir", "hist_dir", "gap_pct", "vi_ratio", "tsi_dir", "tsi_hot", "cloud_dir", "sd_pct", "dist_sma_dir", "sd_pos_dir", "stop_line_pct",
              "ret_1_dir", "ret_3_dir", "ret_12_dir", "range_pct", "body_dir", "vol_ratio", "sniper_agrees", "regime_trend", "tf_min",
              "btc_1_dir", "btc_3_dir", "btc_12_dir", "btc_trend_dir", "hour_sin", "hour_cos", "vs_btc_dir")   # R30: the last 7 = BTC + session context (owl_sniper_ctx), 20 -> 27 numbers
TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def _n(v):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else None
    except (TypeError, ValueError):
        return None


def tsi_zone(v):
    """TSI value -> 'HOT_UP' / 'HOT_DOWN' / 'NORMAL' / None (no value)."""
    v = _n(v)
    return None if v is None else ("HOT_UP" if v > TSI_HOT else "HOT_DOWN" if v < -TSI_HOT else "NORMAL")


def sd_pos(ex):
    """Where the price sits against the SMA, in SD units (dist_sma_pct / sd_pct), signed WITH the trade direction. None when not known."""
    x = ex.get("extra") or {}
    a, b = _n(x.get("dist_sma_pct")), _n(x.get("sd_pct"))
    d = (ex.get("feat") or {}).get("dir") or 0
    return None if a is None or not b or not d else round(a / b * d, 4)


def wide_vec(ex):
    """Example -> (numbers in WIDE_FEATS order, how many were missing and set to 0.0)."""
    f, x = ex.get("feat") or {}, ex.get("extra") or {}
    d = f.get("dir") or 1
    z, h = _n(f.get("z")), _n(f.get("hist"))
    tsi = _n(x.get("tsi"))
    vals = [None if z is None else z * d, None if h is None else h * d, _n(f.get("gap_pct")), _n(f.get("vi_ratio")),
            None if tsi is None else tsi * d, None if tsi is None else float(abs(tsi) > TSI_HOT), _n(x.get("cloud_dir")), _n(x.get("sd_pct")),
            None if _n(x.get("dist_sma_pct")) is None else _n(x.get("dist_sma_pct")) * d, sd_pos(ex), _n(x.get("stop_line_pct")),
            None if _n(x.get("ret_1")) is None else _n(x.get("ret_1")) * d, None if _n(x.get("ret_3")) is None else _n(x.get("ret_3")) * d,
            None if _n(x.get("ret_12")) is None else _n(x.get("ret_12")) * d, _n(x.get("range_pct")),
            None if _n(x.get("body_pct")) is None else _n(x.get("body_pct")) * d, _n(x.get("vol_ratio")),
            None if x.get("sniper_agrees") is None else float(bool(x.get("sniper_agrees"))),
            {"TRENDING": 1.0, "SIDEWAYS": 0.0}.get(ex.get("regime")), _n(TF_MIN.get(ex.get("tf")))]
    b = ex.get("btc") or {}                                   # R30: BTC move / trend (with the trade direction) + hour of day (sin / cos) + coin minus BTC over 3 candles
    hr, r3, b3 = _n(b.get("hour")), _n(x.get("ret_3")), _n(b.get("btc_3"))
    vals += [None if _n(b.get(k)) is None else _n(b.get(k)) * d for k in ("btc_1", "btc_3", "btc_12", "btc_trend")]
    vals += [None if hr is None else math.sin(2 * math.pi * hr / 24.0), None if hr is None else math.cos(2 * math.pi * hr / 24.0), None if r3 is None or b3 is None else (r3 - b3) * d]
    miss = sum(1 for v in vals if v is None)
    return [0.0 if v is None else float(v) for v in vals], miss

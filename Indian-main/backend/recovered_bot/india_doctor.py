"""india_doctor.py - feeds India paper trades into the same Strategy Doctor engine the crypto side uses.

India trade -> Doctor row:
  LONG (bought a CE) -> "BUY",  SHORT (bought a PE) -> "SELL"   (the screen shows them as CE / PE)
  roi_pct  = net pnl / money spent (premium x qty + buy charges) x 100   - charges already inside
  pnl      = Rs after charges
  peak     = best premium gain the trade ever had (mfe_pct)   - only trades closed AFTER this update have it
Entry-context tags (SD zone, EMA slope, volume, choppiness, ADX, EMA distance, higher-TF trend) are the ones the
strategy computed when it fired; older trades simply lack some of them and are left out of those groups.
Read-only: nothing here changes the engine or the strategy.
"""
from datetime import datetime

from . import strategy_doctor

SIDE_NAMES = {"BUY": "CE (call)", "SELL": "PE (put)"}


def _ts(x):
    try:
        if isinstance(x, datetime):
            return x.timestamp()
        return datetime.fromisoformat(str(x)).timestamp()
    except Exception:
        return 0.0


def rows(closed):
    out = []
    for t in closed or []:
        try:
            cost = float(t["entry_premium"]) * float(t["qty"]) + float(t.get("buy_fee") or 0.0)
            if cost <= 0:
                continue
            pnl = float(t["pnl"])
            tags = dict(t.get("tags") or {})
            r = {
                "action": "BUY" if t.get("action") == "LONG" else "SELL",
                "roi_pct": pnl / cost * 100.0, "pnl_usdt": pnl, "fee_usdt": float(t.get("fees") or 0.0),
                "opened_at_ts": _ts(t.get("opened_at")), "closed_at_ts": _ts(t.get("closed_at")),
                "quality_tag": "clean", "clean_exit_reason": str(t.get("reason") or ""),
                "peak_roi_pct": t.get("mfe_pct") if "mfe_pct" in t and "tags" in t else None,
                "tp_hit_levels": list(range(1, int(t.get("tp_hit") or 0) + 1)),
                "underlying": t.get("underlying"), "otype": (t.get("contract") or {}).get("type"),
                "timeframe": tags.get("timeframe"),
            }
            for k in ("entry_zone", "ema_slope_pct", "volume_ratio", "regime_cross_n", "atr_pct", "sd_width_pct",
                      "ema_turn", "adx", "ema_gap_atr", "htf_trend",
                      "z_band", "tsi_band", "tsi_with_trade", "z_with_trade"):
                r[k] = tags.get(k)
            if str(t.get("reason")) == "MANUAL":
                r["clean_exit_reason"] = "MANUAL"
            out.append(r)
        except Exception:
            continue
    return out


def build(closed):
    """Strategy Doctor report for India (never raises)."""
    try:
        rep = strategy_doctor.build_from(rows(closed), unit="Rs", side_names=SIDE_NAMES, post_exit=False)
        rep["market"] = "india"
        try:
            from . import doctor_verdict
        except ImportError:
            import doctor_verdict
        rep["verdict"] = doctor_verdict.build(rows(closed), unit="Rs")      # read-only extra section
        return strategy_doctor._finite(rep)
    except Exception as e:
        return {"ok": False, "sample": 0, "enough": False, "unit": "Rs", "min_sample": strategy_doctor.MIN_SAMPLE,
                "headline": ["India Strategy Doctor could not read the trades yet."], "error": f"{type(e).__name__}: {e}"}

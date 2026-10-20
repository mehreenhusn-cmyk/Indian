"""Vision context helpers (no network / no AI). Run: python3 test/test_vision_context.py"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Minimal candle series: slow climb then sharp pump into last bars
def _candles(n=80, pump=True):
    out = []
    px = 100.0
    t0 = time.time() - n * 300
    for i in range(n):
        if pump and i > n - 8:
            px *= 1.015
        else:
            px *= 1.001
        out.append({
            "timestamp": t0 + i * 300,
            "open": px * 0.999,
            "high": px * 1.002,
            "low": px * 0.998,
            "close": px,
            "volume": 10.0,
        })
    return out


def main():
    from recovered_bot import ai_vision as V

    # _recent_context should warn on BUY after pump
    ctx = V._recent_context(_candles(), "BUY")
    assert isinstance(ctx, str) and len(ctx) > 20, ctx
    assert "WARNING" in ctx or "pump" in ctx.lower() or "TOP" in ctx or "range" in ctx.lower(), ctx

    # _indicator_summary never raises
    lv = {
        "close": 110.0, "e30": 109.0, "e50": 108.0, "mean": 108.5, "sd": 1.0,
        "p1": 109.5, "p2": 110.5, "p3": 111.5, "m1": 107.5, "m2": 106.5, "m3": 105.5,
        "tsi": 12.0, "tsl": 8.0, "z": 1.2, "zsma": 0.4,
        "low12": 100.0, "high12": 112.0, "avg_range": 0.5,
    }
    ind = V._indicator_summary(lv, "BUY", {"ema_agrees": True, "tsi_agrees": True})
    assert ind.get("ema") and ind.get("tsi") and ind.get("sd"), ind

    # prompt includes both-indicator instruction
    rec = {"symbol": "BTCUSDT", "side": "BUY", "tf_min": 5, "sig_price": 110.0, "feat": {"ema_agrees": True}}
    p = V._signal_prompt(rec, lv, 110.0, recent_ctx=ctx)
    assert "BOTH indicator" in p or "both" in p.lower()
    assert "WARNING" in p or "pump" in p.lower() or "Recent market context" in p

    print("PASS test_vision_context")


if __name__ == "__main__":
    main()

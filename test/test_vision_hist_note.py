"""TSI histogram note for Vision AI (v3: no hand-made words, only numbers). No network, no AI. Run: python3 test/test_vision_hist_note.py"""
import io
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

OLD_WORDS = ("Buyers coming in", "Buyers leaving", "Sellers coming in", "Sellers leaving", "Not a buy yet", "Not a sell yet",
             "never a reason to buy", "Buyers taking over", "Sellers taking over")


def _f(vals, **kw):
    d = {"diff": [None, None] + list(vals)}
    d.update(kw)
    return d


def _candles(n=420):
    random.seed(7)
    out, px, t0 = [], 100.0, time.time() - n * 300
    for i in range(n):
        px *= 1 + random.uniform(-0.004, 0.0045)
        out.append({"timestamp": (t0 + i * 300) * 1000, "open": px * 0.999, "high": px * 1.003,
                    "low": px * 0.997, "close": px, "volume": 10.0})
    return out


def main():
    from recovered_bot import ai_vision as V

    # --- only numbers: no reading words anywhere in the text the AI gets
    for vals in ([1, 2, 3, 4.2, 5.5], [6, 5, 4, 3.1, 2.0], [-1, -2, -3, -4, -5], [-3, -2, -1, 0.5, 1.5], [3, 2, 1, -0.5, -1.0], [2, 3, 2.5, 3, 2.8]):
        n = V.hist_note(_f(vals))
        assert len(n["vals"]) == 5 and n["vals"] == [round(float(x), 3) for x in vals], n
        for w in OLD_WORDS:
            assert w not in n["text"] and w not in n["short"], (w, n)
        assert "green = above 0, red = below 0" in n["text"], n
        assert n["word"] == "" and n["line"] == "", n

    # the owner's example numbers are in the text, oldest to newest
    n = V.hist_note(_f([4.2, 3.1, 1.8, 0.6, -0.9]))
    assert "+4.2, +3.1, +1.8, +0.6, -0.9" in n["text"], n

    # --- short / missing history: no crash, honest text
    for bad in ([], [1, 2], [None, 1, 2, 3, 4]):
        n = V.hist_note({"diff": bad})
        assert n["line"] == "Not enough bars" and n["vals"] == [], n
    assert V.hist_note({})["word"] == "Unknown"

    # --- the last 10 bars and the raw TSI / signal numbers (no verdict)
    f = {"diff": [-15.3, -14, -13, -12.5, -11.9, -11.2, -10.9, -10.7, -10.5, -10.3], "tsi": [-20, -12.3], "tsl": [-18, -9.1]}
    n = V.hist_note(f)
    assert len(n["vals10"]) == 10 and len(n["vals"]) == 5, n
    assert "TSI -12.3" in n["text"] and "signal line -9.1" in n["text"], n
    for w in OLD_WORDS:
        assert w not in n["text"], (w, n)
    assert V.hist_note({"diff": [1, 2, 3, 4, 5]})["pos"] == ""

    # --- the note text is inside the prompts the AI reads, and the old reading lines are not
    note = V.hist_note(_f([6, 5, 4, 3.1, 2.0]))
    lv = {"close": 110.0, "e30": 109.0, "e50": 108.0, "mean": 108.5, "sd": 1.0, "p1": 109.5, "p2": 110.5,
          "p3": 111.5, "m1": 107.5, "m2": 106.5, "m3": 105.5, "tsi": 12.0, "tsl": 8.0, "z": 1.2, "zsma": 0.4,
          "low12": 100.0, "high12": 112.0, "avg_range": 0.5}
    rec = {"symbol": "BTCUSDT", "side": "BUY", "tf_min": 5, "sig_price": 110.0, "feat": {}, "tsi_hist_note": note}
    p = V._signal_prompt(rec, lv, 110.0)
    assert note["text"] in p, p
    for w in OLD_WORDS:
        assert w not in p, w
    tr = {"symbol": "BTCUSDT", "side": "BUY", "tf_min": 5, "entry": 100.0, "sl": 99.0, "target": 105.0, "lev": 10}
    rp = V._review_prompt(tr, lv, 101.0, "test", hist_text=note["text"])
    assert note["text"] in rp, rp
    assert "TSI histogram" not in V._review_prompt(tr, lv, 101.0, "test")     # old call still works
    for w in OLD_WORDS:
        assert w not in V.GUIDE, w
    assert "HIST box" in V.GUIDE

    # --- the chart still draws (needs Pillow)
    try:
        from PIL import Image
    except ImportError:
        print("SKIP chart part (Pillow missing)")
    else:
        png = V.render_chart("TESTUSDT", _candles(), "5m", "BUY", {})
        im = Image.open(io.BytesIO(png))
        assert im.size[0] > 800 and im.size[1] > 1200, im.size

    print("PASS test_vision_hist_note")


if __name__ == "__main__":
    main()

"""TSI histogram note for Vision AI (no network, no AI). Run: python3 test/test_vision_hist_note.py"""
import io
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def _f(vals):
    return {"diff": [None, None] + list(vals)}


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

    # --- the 5 words and the plain lines, with planted numbers
    cases = [
        ([1, 2, 3, 4.2, 5.5], "Growing", "Buyers coming in"),
        ([6, 5, 4, 3.1, 2.0], "Shrinking", "Buyers leaving"),
        ([-1, -2, -3, -4, -5], "Growing", "Sellers coming in"),
        ([-6, -5, -4, -3, -2], "Shrinking", "Sellers leaving"),
        ([-3, -2, -1, 0.5, 1.5], "Flipping up", "Buyers taking over"),
        ([3, 2, 1, -0.5, -1.0], "Flipping down", "Sellers taking over"),
        ([3, 2, -0.5, -1.0, -2.0], "Growing", "Sellers coming in"),     # flip was 3 bars ago: no longer "flipping"
        ([2, 3, 2.5, 3, 2.8], "Flat", "No clear push"),
    ]
    for vals, word, line in cases:
        n = V.hist_note(_f(vals))
        assert n["word"] == word and n["line"] == line, (vals, n)
        assert line in n["text"] and word in n["text"], n
        assert len(n["vals"]) == 5, n

    # example from the owner's request: +4.2 +3.1 +1.8 +0.6 -0.9 -> just flipped down
    n = V.hist_note(_f([4.2, 3.1, 1.8, 0.6, -0.9]))
    assert n["word"] == "Flipping down" and "+4.2, +3.1, +1.8, +0.6, -0.9" in n["text"], n

    # same sign, shrinking, 3 bars
    n = V.hist_note(_f([4.2, 3.1, 1.8, 0.6, 0.2]))
    assert n["word"] == "Shrinking" and n["line"] == "Buyers leaving", n

    # --- short / missing history: no crash, honest text
    for bad in ([], [1, 2], [None, 1, 2, 3, 4]):
        n = V.hist_note({"diff": bad})
        assert n["line"] == "Not enough bars" and n["vals"] == [], n
    assert V.hist_note({})["word"] == "Unknown"

    # --- only the LAST 5 bars are used
    n = V.hist_note(_f([9, 9, 9, 9, 9, 9, 1, 2, 3, 4, 5]))
    assert n["vals"] == [1, 2, 3, 4, 5], n

    # --- the note text is inside the prompts the AI reads
    note = V.hist_note(_f([6, 5, 4, 3.1, 2.0]))
    lv = {"close": 110.0, "e30": 109.0, "e50": 108.0, "mean": 108.5, "sd": 1.0, "p1": 109.5, "p2": 110.5,
          "p3": 111.5, "m1": 107.5, "m2": 106.5, "m3": 105.5, "tsi": 12.0, "tsl": 8.0, "z": 1.2, "zsma": 0.4,
          "low12": 100.0, "high12": 112.0, "avg_range": 0.5}
    rec = {"symbol": "BTCUSDT", "side": "BUY", "tf_min": 5, "sig_price": 110.0, "feat": {}, "tsi_hist_note": note}
    p = V._signal_prompt(rec, lv, 110.0)
    assert note["text"] in p and "Buyers leaving" in p and "name it in your reason" in p, p
    tr = {"symbol": "BTCUSDT", "side": "BUY", "tf_min": 5, "entry": 100.0, "sl": 99.0, "target": 105.0, "lev": 10}
    rp = V._review_prompt(tr, lv, 101.0, "test", hist_text=note["text"])
    assert note["text"] in rp, rp
    assert "TSI histogram" not in V._review_prompt(tr, lv, 101.0, "test")     # old call still works
    assert "HIST box" in V.GUIDE and "say it in your reason" in V.GUIDE

    # --- the chart draws with the box (needs Pillow) and the rest of the picture is still made
    try:
        from PIL import Image
    except ImportError:
        print("SKIP chart part (Pillow missing)")
    else:
        png = V.render_chart("TESTUSDT", _candles(), "5m", "BUY", {})
        im = Image.open(io.BytesIO(png))
        assert im.size[0] > 800 and im.size[1] > 1200, im.size
        # white box with grey border exists inside the TSI pane (right side)
        px = im.convert("RGB").load()
        W = im.size[0]
        found = any(px[x, y] == (120, 120, 120) for x in range(W - 450, W - 140) for y in range(734, 760)) or \
            any(px[x, y] == (120, 120, 120) for x in range(W - 450, W - 140) for y in range(925, 962))
        assert found, "HIST box border not found in the TSI pane"

    print("PASS test_vision_hist_note")


if __name__ == "__main__":
    main()

def test_v2():
    """v2: 10 values, TSI/signal position, 'not a buy yet' when TSI is still below 0."""
    from recovered_bot import ai_vision as V
    f = {"diff": [-15.3, -14, -13, -12.5, -11.9, -11.2, -10.9, -10.7, -10.5, -10.3],
         "tsi": [-20, -12.3], "tsl": [-18, -9.1]}
    n = V.hist_note(f)
    assert n["word"] == "Shrinking" and len(n["vals10"]) == 10 and len(n["vals"]) == 5, n
    assert "Not a buy yet" in n["ctx"] and "below 0" in n["pos"], n
    assert "never a reason to buy" in n["text"] and "-12.3" in n["text"], n
    f2 = dict(f, tsi=[1, 5.0], tsl=[1, 4.0], diff=[4, 3.5, 3, 2.5, 2, 1.8, 1.5, 1.2, 0.9, 0.6])
    n2 = V.hist_note(f2)
    assert "Not a sell yet" in n2["ctx"], n2
    # no TSI lines: still works
    n3 = V.hist_note({"diff": [1, 2, 3, 4, 5]})
    assert n3["pos"] == "" and n3["word"] == "Growing", n3
    # chart still renders with the bigger box
    png = V.render_chart("TESTUSDT", _candles(), "5m")
    assert png and png[:4] == b"\x89PNG", "no png"
    print("PASS test_v2")


if __name__ == "__main__":
    test_v2()

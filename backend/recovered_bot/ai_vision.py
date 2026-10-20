"""
ai_vision.py - VISION AI: one AI that looks at a chart picture of every bot signal and says TAKE / SKIP / WAIT.

What it does
  * The bot is untouched. It still trades the EMA50 cross exactly as before.
  * For every bot signal this module draws the chart (price + EMA30/EMA50 + SD bands, the TSI pane and the Z-score pane),
    sends the picture to the AI (Gemini, Claude or OpenAI - the key from Settings > AI Assistant) and gets back a decision,
    a reason, a short checklist, a stop and a first target.
  * TAKE opens a VIRTUAL trade in the AI's own paper account. SKIP / WAIT do not. WAIT is looked at again on the next candles.
  * Open AI trades are managed by the AI: a hard stop is checked on every tick (no AI call needed), and every few candles
    (and when the target is touched) the AI looks at a fresh chart and says HOLD or EXIT and may move the stop / target.
    There is no fixed take-profit: the exit comes from what the indicators show (momentum, divergence, bands).
  * Everything is saved so the app can show the decision, the reason and the exact chart the AI saw.

Safety (same rules as the other AI files): read-only toward the bot and the exchange (no orders, no changes to the bot's
trades), own daemon thread, every error is caught and written to the log, own files ai/ai_vision.json + ai/vision_img/.
Honest limits: a picture-reading AI is not a guarantee. The scoreboard compares its trades with what the bot did on the
same signals, so the owner can see with real numbers whether the reading helps.
"""
import base64
import io
import json
import math
import os
import re
import threading
import time

import requests

from . import ai_ind_features as F

KEEP_DEC = 400
KEEP_TRADES = 400
KEEP_IMG = 100
CANDLES = 450          # enough for Z-score (200) + its 200-candle average
VIEW = 90              # candles drawn
TICK_S = 3.0
WAITS = 3              # a WAIT is looked at again on up to 3 more candles

_lock = threading.RLock()
_state = {"dec": [], "trades": [], "since": 0.0, "log": []}
_loaded = False
_dirty = False
_file = None
_img_dir = None
_px = {}               # symbol -> (price, time)
_calls = []            # times of AI calls in the last minute (rate limit)
_day_calls = []        # times of AI calls in the last 24 h (daily cap = the owner's budget)
_stat = {"error": "", "ok_at": 0.0, "pause_until": 0.0, "model": ""}
_slot_err = {}         # slot -> last error text of that key (empty = last call worked)
_mon = []              # AI call log for the "AI Calls" card: (time, slot, kind ok|quota|error, seconds)
_started = False
_botmap = {"t": 0.0, "closed": {}, "open": set()}
_gem_ok = {"name": None}
_last_save = [0.0]

_GEMINI_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]   # old gemini-2.5 / 2.0 names removed (retired); a 404 suggestion is added on the fly
_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_MODEL = "gpt-4o-mini"


# ------------------------------------------------------------------ the guide the AI reads
GUIDE = """You are the Vision AI of a crypto paper-trading bot. The bot opens a trade every time price crosses the EMA50 on a closed candle. Your job is to look at the chart picture and judge that signal the way a calm, experienced human trader would. You do not follow fixed rules. The notes below only explain what each part of the picture means and where it can fool you.

MAIN CHART (top)
- Green line = EMA30, red line = EMA50. Look at the slope and the gap. Flat, tangled lines with small choppy candles mean a sideways market. Lines fanning out with big full-body candles mean energy.
- Curved bands = SD bands (mean +/- 1, 2 and 3 standard deviations; the dark line is the mean). They act like support and resistance. Price outside the 2nd or 3rd band is stretched.
- Long wicks = rejection. Small bodies = no energy.

TSI PANE (middle)
- Grey line = TSI value. The thick coloured line = TSI signal line. Its colour has four meanings:
  dark green = signal above zero and TSI above the signal (buyers strong);
  light green = signal above zero but TSI below the signal (buying is cooling; a pullback is possible, but the trend can also continue and it can even drop below zero quickly);
  light red = signal below zero and TSI above the signal (selling is weak; a bounce is possible);
  dark red = signal below zero and TSI below the signal (sellers strong).
- Bars = TSI minus signal (the push). Ignore any reversal arrows.

Z-SCORE PANE (bottom)
- Green area = upside momentum. Red area = downside momentum. The black line = Z-SMA (200-candle average of Z).
- Z above the black line = strong momentum. If the area is green but the black line is above it, the black line can act like resistance.
- Shaded zones: inside 1 sigma, 1-2 sigma, 2-3 sigma. The further out, the more stretched.
- Divergence: price makes a new high while Z falls (or the reverse) can show weakness. But markets sometimes just move sideways, so divergence is a clue, not a rule.

The empty space on the right of the picture is the future: nothing is known there. Use it to think about where price may go.

Think about what past candles say about where price may go next. Give honest probabilities, not certainty. If the picture is unclear, say so and choose SKIP or WAIT."""


def guide_text(symbol=None, side=None):
    notes = str(_cfg("vision_notes", "") or "").strip()
    out = GUIDE
    if notes:
        out += "\n\nOWNER'S OWN NOTES (written by the person who built these indicators; trust them):\n" + notes
    try:                                                   # the learning notebook: approved rules + the AI's own recent lessons
        if bool(_cfg("vision_lessons_enabled", True)):
            from . import ai_vision_lessons as L
            out += L.prompt_block(symbol, side)
    except Exception as e:
        print(f"[Vision] notebook: {e}")
    return out


# ------------------------------------------------------------------ plumbing
def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def enabled():
    return bool(_cfg("vision_enabled", True))


def init(path):
    global _file, _img_dir
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "ai_vision.json")
        _img_dir = os.path.join(path, "vision_img")
        os.makedirs(_img_dir, exist_ok=True)
        from . import ai_vision_lessons as L
        L.init(path)
    except Exception as e:
        print(f"[Vision] init: {e}")


def _mark():
    global _dirty
    _dirty = True


def _log(text):
    with _lock:
        _state["log"].append({"t": time.time(), "text": str(text)[:300]})
        _state["log"] = _state["log"][-60:]
        _mark()


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _src = safe_io.read_json_safe(_file, "ai_vision")
                if isinstance(d, dict):
                    for k in ("dec", "trades", "log"):
                        if isinstance(d.get(k), list):
                            _state[k] = d[k]
                    _state["since"] = float(d.get("since") or 0.0)
        except Exception as e:
            print(f"[Vision] load: {e}")
        if not _state["since"]:
            _state["since"] = time.time()
            _mark()


def _save(force=False):
    global _dirty
    with _lock:
        if not _file or not (_dirty or force):
            return
        if not force and time.time() - _last_save[0] < 5:
            return
        try:
            from . import safe_io
            _state["dec"] = _state["dec"][-KEEP_DEC:]
            _state["trades"] = _state["trades"][-KEEP_TRADES:]
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
            _last_save[0] = time.time()
        except Exception as e:
            print(f"[Vision] save: {e}")


def _f(x, default=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _tf_min(label):
    try:
        from . import exchange
        return int(exchange.resolve_timeframe(label))
    except Exception:
        m = re.search(r"(\d+)", str(label or "5"))
        n = int(m.group(1)) if m else 5
        return n * 60 if str(label or "").lower().endswith("h") else n


def _tf_label(mins):
    return f"{mins}m" if mins < 60 else f"{mins // 60}h"


def _ist(ts):
    try:
        t = time.gmtime(float(ts) + 5.5 * 3600)
        return time.strftime("%d %b %H:%M", t)
    except Exception:
        return ""


def _fmt(v):
    if v is None:
        return "-"
    v = float(v)
    if v == 0:
        return "0"
    d = max(2, min(8, 4 - int(math.floor(math.log10(abs(v))))))
    return f"{v:.{d}f}"


def _side_word(side):
    return "LONG" if side == "BUY" else "SHORT"


def _roi(side, entry, px, lev):
    if not entry:
        return 0.0
    mv = (px - entry) / entry if side == "BUY" else (entry - px) / entry
    return mv * lev * 100.0


# ------------------------------------------------------------------ candles + chart picture
def _fetch(symbol, tf_min):
    from . import exchange
    c = exchange.get_klines(symbol, tf_min, CANDLES, False, None, False)
    return c or []


def _levels(candles):
    """Plain numbers read from the same candles the picture shows - the AI uses them for exact prices."""
    f = F.build(candles)
    n = f["n"]
    i = n - 1
    e30 = F.ema(f["c"], 30, seed="sma")
    mean, sd = f["sma"][i], f["std"][i]
    lv = {"close": f["c"][i], "e30": e30[i], "e50": f["e50"][i], "mean": mean, "sd": sd,
          "low12": min(f["l"][-12:]), "high12": max(f["h"][-12:]),
          "avg_range": sum(f["h"][j] - f["l"][j] for j in range(max(0, n - 14), n)) / max(1, min(14, n)),
          "ts": f["t"][i]}
    if mean is not None and sd:
        for k in (1, 2, 3):
            lv[f"p{k}"] = mean + k * sd
            lv[f"m{k}"] = mean - k * sd
    # Extra indicator snapshot for the AI prompt and the Results cards
    try:
        tsi, tsl, z, zsma = f["tsi"][i], f["tsl"][i], f["z"][i], f.get("zsma", [None] * n)[i]
        lv["tsi"], lv["tsl"], lv["z"], lv["zsma"] = tsi, tsl, z, zsma
    except Exception:
        pass
    return f, e30, lv


def _recent_context(candles, side):
    """Plain-English context: recent pump/dump, stretch, structure vs this signal.
    Stops the AI from BUY-ing right after a pump it never 'saw' in numbers."""
    try:
        if not candles or len(candles) < 30:
            return ""
        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        n = len(closes)
        last = closes[-1]
        # Biggest move in last 20 candles (peak-to-trough)
        win = 20
        seg_h = max(highs[-win:])
        seg_l = min(lows[-win:])
        move_pct = (seg_h - seg_l) / seg_l * 100.0 if seg_l > 0 else 0.0
        # Where is price now inside that range?
        pos = (last - seg_l) / (seg_h - seg_l) if seg_h > seg_l else 0.5
        # 5-candle impulse
        impulse = (closes[-1] - closes[-6]) / closes[-6] * 100.0 if closes[-6] else 0.0
        # Higher structure: last 50 vs previous 50 average
        a_now = sum(closes[-50:]) / 50.0 if n >= 50 else last
        a_prev = sum(closes[-100:-50]) / 50.0 if n >= 100 else a_now
        trend = "higher-time structure UP" if a_now > a_prev * 1.005 else (
            "higher-time structure DOWN" if a_now < a_prev * 0.995 else "higher-time structure FLAT")
        bits = [f"Last {win} candles spanned about {move_pct:.1f}% (high {_fmt(seg_h)} / low {_fmt(seg_l)})."]
        if move_pct >= 4.0:
            if pos >= 0.75:
                bits.append("Price is near the TOP of that recent range (after a pump or squeeze).")
            elif pos <= 0.25:
                bits.append("Price is near the BOTTOM of that recent range (after a dump or selloff).")
            else:
                bits.append("Price is mid-range after a large recent move.")
        if abs(impulse) >= 1.5:
            bits.append(f"Last 5 candles moved {impulse:+.1f}% (short impulse).")
        bits.append(trend + ".")
        # Alignment warning
        if side == "BUY" and pos >= 0.8 and move_pct >= 4.0:
            bits.append("WARNING for BUY: chasing near the top of a recent pump often dumps next.")
        if side == "SELL" and pos <= 0.2 and move_pct >= 4.0:
            bits.append("WARNING for SELL: shorting near the bottom of a recent dump often bounces.")
        return " ".join(bits)
    except Exception:
        return ""


def _indicator_summary(lv, side, feat=None):
    """Short structured read of both indicator families for Results cards + AI."""
    feat = feat or {}
    out = {"ema": "", "sd": "", "tsi": "", "zscore": "", "align": ""}
    try:
        e30, e50 = lv.get("e30"), lv.get("e50")
        if e30 is not None and e50 is not None:
            if side == "BUY":
                out["ema"] = "EMA30 above EMA50 (bull stack)" if e30 >= e50 else "EMA30 below EMA50 (against BUY)"
            else:
                out["ema"] = "EMA30 below EMA50 (bear stack)" if e30 <= e50 else "EMA30 above EMA50 (against SELL)"
        mean, close, sd = lv.get("mean"), lv.get("close"), lv.get("sd")
        if mean is not None and sd and close is not None and sd > 0:
            zband = (close - mean) / sd
            if abs(zband) >= 2:
                out["sd"] = f"Stretched ~{zband:+.1f} SD from mean"
            elif abs(zband) >= 1:
                out["sd"] = f"Near 1 SD ({zband:+.1f})"
            else:
                out["sd"] = f"Inside 1 SD ({zband:+.1f})"
        tsi, tsl = lv.get("tsi"), lv.get("tsl")
        if tsi is not None and tsl is not None:
            if tsl >= 0 and tsi >= tsl:
                out["tsi"] = "TSI strong buy side (above signal, above 0)"
            elif tsl >= 0:
                out["tsi"] = "TSI above 0 but below signal (buying cooling)"
            elif tsi <= tsl:
                out["tsi"] = "TSI strong sell side (below signal, below 0)"
            else:
                out["tsi"] = "TSI below 0 but above signal (selling weak)"
        z, zs = lv.get("z"), lv.get("zsma")
        if z is not None:
            if zs is not None:
                out["zscore"] = f"Z={z:+.2f} vs Z-SMA={zs:+.2f} ({'above' if z >= zs else 'below'} average)"
            else:
                out["zscore"] = f"Z={z:+.2f}"
        agrees = [k for k, v in (feat or {}).items() if v is True and k.endswith("_agrees")]
        against = [k for k, v in (feat or {}).items() if v is False and k.endswith("_agrees")]
        if agrees or against:
            out["align"] = f"Agrees: {', '.join(agrees) or 'none'}; against: {', '.join(against) or 'none'}"
    except Exception:
        pass
    return out


def render_chart(symbol, candles, tf_label, side=None, marks=None, title_extra=""):
    """PNG bytes of the chart the AI (and the owner) sees. marks: entry, sl, target, exit, bar_ts."""
    from PIL import Image, ImageDraw, ImageFont
    marks = marks or {}
    f, e30, lv = _levels(candles)
    n = f["n"]
    lo = max(0, n - VIEW)
    nb = n - lo
    W, H = 940, 1290
    x0, x1 = 14, W - 134
    FUT = 16                                   # empty bars on the right = the future, like on TradingView
    step = (x1 - x0) / float(nb + FUT)
    PM = (60, 700)      # main panel top / bottom
    PT = (730, 965)     # TSI
    PZ = (995, 1230)    # Z-score

    def font(sz):
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()

    f12, f14, f18 = font(12), font(14), font(18)
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    d = ImageDraw.Draw(img)

    def sx(i):
        return x0 + (i - lo + 0.5) * step

    def mk(top, bot, vlo, vhi):
        span = (vhi - vlo) or 1.0

        def g(v):
            y = bot - (v - vlo) / span * (bot - top)
            return max(top - 3, min(bot + 3, y))
        return g

    # ---- main panel range
    vis = range(lo, n)
    hs = [f["h"][i] for i in vis] + [e for e in e30[lo:] if e] + [e for e in f["e50"][lo:] if e]
    ls = [f["l"][i] for i in vis] + [e for e in e30[lo:] if e] + [e for e in f["e50"][lo:] if e]
    pmax, pmin = max(hs), min(ls)
    span = (pmax - pmin) or pmax * 0.01
    for k in ("entry", "sl", "target", "exit"):
        v = _f(marks.get(k))
        if v:
            pmax, pmin = max(pmax, v), min(pmin, v)
    cands = []
    if lv.get("mean") is not None and lv.get("sd"):
        cands = [lv["p1"], lv["m1"], lv["p2"], lv["m2"], lv["mean"]]
    for v in cands:
        if pmin - 2.0 * span <= v <= pmax + 2.0 * span:
            pmax, pmin = max(pmax, v), min(pmin, v)
    pad = (pmax - pmin) * 0.06
    gy = mk(PM[0], PM[1], pmin - pad, pmax + pad)

    # ---- SD clouds (fills first)
    def band(upper, lower, rgba):
        pts_u, pts_l = [], []
        for i in range(lo, n):
            if upper[i] is not None and lower[i] is not None:
                pts_u.append((sx(i), gy(upper[i])))
                pts_l.append((sx(i), gy(lower[i])))
        if len(pts_u) > 1:
            od.polygon(pts_u + pts_l[::-1], fill=rgba)

    sma, std = f["sma"], f["std"]
    ser = {}
    for k in (-3, -2, -1, 0, 1, 2, 3):
        ser[k] = [None if (sma[i] is None or std[i] is None) else sma[i] + k * std[i] for i in range(n)]
    band(ser[2], ser[1], (227, 241, 230, 190))
    band(ser[-1], ser[-2], (227, 241, 230, 190))
    band(ser[3], ser[2], (253, 249, 220, 190))
    band(ser[-2], ser[-3], (253, 249, 220, 190))
    # EMA fill
    for i in range(max(lo + 1, 1), n):
        a, b, c2, d2 = e30[i - 1], f["e50"][i - 1], e30[i], f["e50"][i]
        if None in (a, b, c2, d2):
            continue
        col = (76, 175, 80, 70) if (a + c2) >= (b + d2) else (239, 83, 80, 70)
        od.polygon([(sx(i - 1), gy(a)), (sx(i), gy(c2)), (sx(i), gy(d2)), (sx(i - 1), gy(b))], fill=col)

    # ---- TSI panel range + fills
    tv = [v for v in f["tsi"][lo:] + f["tsl"][lo:] if v is not None]
    tlo = min([-45.0] + tv) - 4
    thi = max([45.0] + tv) + 4
    gt = mk(PT[0], PT[1], tlo, thi)
    z0 = gt(0)
    for i in range(lo, n):
        df = f["diff"][i]
        if df is None:
            continue
        # Histogram bars first (opaque) so they stay visible under the light TSI fill.
        col = (165, 214, 167, 255) if df >= 0 else (239, 154, 154, 255)
        od.rectangle([sx(i) - step * 0.3, min(z0, gt(df)), sx(i) + step * 0.3, max(z0, gt(df))], fill=col)
    for i in range(max(lo + 1, 1), n):
        a, b, c2, d2 = f["tsi"][i - 1], f["tsl"][i - 1], f["tsi"][i], f["tsl"][i]
        if None in (a, b, c2, d2):
            continue
        # Lighter fill (was 85) so histogram bars stay readable for the AI and the owner.
        col = (76, 175, 80, 40) if (a + c2) >= (b + d2) else (239, 83, 80, 40)
        od.polygon([(sx(i - 1), gt(a)), (sx(i), gt(c2)), (sx(i), gt(d2)), (sx(i - 1), gt(b))], fill=col)

    # ---- Z panel zones + area
    ZR = 3.4
    gz = mk(PZ[0], PZ[1], -ZR, ZR)
    for a, b, col in ((0, 1, (200, 230, 200, 120)), (1, 2, (255, 245, 200, 140)), (2, 3, (255, 205, 210, 140))):
        od.rectangle([x0, gz(b), x1, gz(a)], fill=col)
        od.rectangle([x0, gz(-a), x1, gz(-b)], fill=col)
    zz0 = gz(0)
    for i in range(max(lo + 1, 1), n):
        a, c2 = f["z"][i - 1], f["z"][i]
        if a is None or c2 is None:
            continue
        col = (76, 175, 80, 140) if (a + c2) >= 0 else (239, 83, 80, 140)
        od.polygon([(sx(i - 1), zz0), (sx(i - 1), gz(max(-ZR, min(ZR, a)))), (sx(i), gz(max(-ZR, min(ZR, c2)))), (sx(i), zz0)], fill=col)

    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)

    # ---- panel frames + zero lines
    for top, bot in (PM, PT, PZ):
        d.rectangle([x0, top, x1, bot], outline=(210, 214, 220), width=1)
    d.line([x0, z0, x1, z0], fill=(150, 150, 150), width=1)
    d.line([x0, gt(30), x1, gt(30)], fill=(240, 170, 175), width=1)
    d.line([x0, gt(-30), x1, gt(-30)], fill=(150, 195, 240), width=1)
    d.line([x0, zz0, x1, zz0], fill=(150, 150, 150), width=1)

    def poly(vals, g, color, width=1):
        pts = [(sx(i), g(vals[i])) for i in range(lo, n) if vals[i] is not None]
        if len(pts) > 1:
            d.line(pts, fill=color, width=width, joint="curve")

    # SD lines
    for k in (-3, -2, 2, 3):
        poly(ser[k], gy, (160, 160, 160), 1)
    for k in (-1, 0, 1):
        poly(ser[k], gy, (70, 70, 70), 1)

    # candles
    up, dn = (8, 153, 129), (242, 54, 69)
    bw = max(1.0, step * 0.32)
    for i in range(lo, n):
        o, h, l, c = f["o"][i], f["h"][i], f["l"][i], f["c"][i]
        col = up if c >= o else dn
        x = sx(i)
        d.line([x, gy(h), x, gy(l)], fill=col, width=1)
        ya, yb = gy(o), gy(c)
        if abs(ya - yb) < 1.5:
            yb = ya + 1.5
        d.rectangle([x - bw, min(ya, yb), x + bw, max(ya, yb)], fill=col)
    poly(e30, gy, (34, 160, 64), 2)
    poly(f["e50"], gy, (230, 50, 60), 2)

    # TSI lines
    poly(f["tsi"], gt, (130, 130, 130), 1)
    for i in range(max(lo + 1, 1), n):
        a, b, v, s = f["tsl"][i - 1], f["tsl"][i], f["tsi"][i], f["tsl"][i]
        if a is None or b is None or v is None:
            continue
        pos, above = s > 0, v > s
        col = ((8, 153, 129) if above else (150, 215, 170)) if pos else ((255, 138, 122) if above else (233, 30, 99))
        d.line([sx(i - 1), gt(a), sx(i), gt(b)], fill=col, width=4)

    # Z lines
    zc = [None if v is None else max(-ZR, min(ZR, v)) for v in f["z"]]
    poly(zc, gz, (60, 60, 60), 1)
    poly([None if v is None else max(-ZR, min(ZR, v)) for v in f["zsma"]], gz, (0, 0, 0), 3)

    # ---- marks (entry / stop / target / exit)
    def hline(v, col, label, dashed=True):
        v = _f(v)
        if not v:
            return
        y = gy(v)
        if y < PM[0] - 2 or y > PM[1] + 2:
            return
        if dashed:
            xx = x0
            while xx < x1:
                d.line([xx, y, min(xx + 8, x1), y], fill=col, width=2)
                xx += 14
        else:
            d.line([x0, y, x1, y], fill=col, width=2)
        txt = f"{label} {_fmt(v)}"
        tw = d.textlength(txt, font=f12)
        d.rectangle([x1 + 2, y - 8, x1 + 6 + tw, y + 8], fill=col)
        d.text((x1 + 4, y - 7), txt, fill=(255, 255, 255), font=f12)

    hline(marks.get("entry"), (33, 150, 243), "ENTRY", False)
    hline(marks.get("sl"), (242, 54, 69), "STOP")
    hline(marks.get("target"), (8, 153, 129), "TARGET")
    hline(marks.get("exit"), (255, 152, 0), "EXIT", False)
    bts = marks.get("bar_ts")
    if bts:
        j = None
        for i in range(lo, n):
            if f["t"][i] <= bts:
                j = i
        if j is not None:
            xm = sx(j)
            for yy in range(PM[0], PM[1], 12):
                d.line([xm, yy, xm, yy + 5], fill=(120, 120, 120), width=1)
            ytip = gy(f["l"][j]) + 18 if side == "BUY" else gy(f["h"][j]) - 18
            colm = (8, 153, 129) if side == "BUY" else (242, 54, 69)
            if side == "BUY":
                d.polygon([(xm, ytip - 14), (xm - 8, ytip), (xm + 8, ytip)], fill=colm)
            elif side == "SELL":
                d.polygon([(xm, ytip + 14), (xm - 8, ytip), (xm + 8, ytip)], fill=colm)

    # ---- right axis labels
    for k in range(6):
        v = (pmin - pad) + (pmax - pmin + 2 * pad) * k / 5.0
        d.text((x1 + 4, gy(v) - 7), _fmt(v), fill=(90, 90, 90), font=f12)
    for v in (30, 0, -30):
        d.text((x1 + 4, gt(v) - 7), f"{v}", fill=(90, 90, 90), font=f12)
    for v in (3, 2, 1, 0, -1, -2, -3):
        d.text((x1 + 4, gz(v) - 7), f"{v:+d}s" if v else "0", fill=(90, 90, 90), font=f12)
    if lv.get("mean") is not None and lv.get("sd"):
        for k, name in ((0, "mean"), (1, "+1SD"), (2, "+2SD"), (-1, "-1SD"), (-2, "-2SD")):
            v = lv["mean"] + k * lv["sd"]
            y = gy(v)
            if PM[0] + 4 < y < PM[1] - 4:
                d.text((x0 + 4, y - 14), name, fill=(110, 110, 110), font=f12)

    # ---- time axis (IST) + titles
    for k in range(5):
        i = lo + int((nb - 1) * k / 4.0)
        d.text((max(2, sx(i) - 28), PZ[1] + 8), _ist(f["t"][i] / 1000.0)[-5:], fill=(90, 90, 90), font=f12)
    sig = f"  |  bot signal: {_side_word(side)}" if side else ""
    d.text((x0, 10), f"{symbol}   {tf_label}{sig}", fill=(20, 20, 20), font=f18)
    d.text((x0, 34), "Green line EMA30  |  Red line EMA50  |  curved bands = SD 1/2/3 (dark = mean/1SD)" + (f"   {title_extra}" if title_extra else ""), fill=(100, 100, 100), font=f12)
    d.text((x0 + 4, PT[0] + 4), "TSI: grey = value, thick = signal line (4 colours)", fill=(100, 100, 100), font=f12)
    d.text((x0 + 4, PZ[0] + 4), "Z-SCORE: green/red area, black line = Z-SMA 200", fill=(100, 100, 100), font=f12)
    d.text((x1 - 120, 10), _ist(f["t"][-1] / 1000.0) + " IST", fill=(100, 100, 100), font=f12)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ AI call
# Two key slots: "main" (Settings > AI Assistant) and an optional "backup" (Settings > AI backup key: Mistral or Groq, both have a
# free plan). When one slot runs out of quota it is paused on its own and the next slot answers. If every slot is paused the
# signals simply wait (they are NOT marked ERROR) and the tab shows when the quota is expected back.
_OAI_STYLE = {      # provider -> (url, default vision model). All three speak the same "OpenAI chat" format.
    "openai": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
    "mistral": ("https://api.mistral.ai/v1/chat/completions", "mistral-small-latest"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "meta-llama/llama-4-maverick:free"),   # free model names change: set the Model field if it says 404
}
_rr = [0]            # round-robin counter: calls are SHARED between the ready keys instead of emptying the first key first
_pause = {}          # "slot:model" -> time until which that model is paused (quota or key problem)
QUOTA_PROBE_S = 1800  # after a DAILY quota error one test call is made every 30 minutes until Google says yes again


def _ai_key():
    key = str(_cfg("ai_api_key", "") or "").strip()
    return key, str(_cfg("ai_provider", "openai") or "openai"), str(_cfg("ai_model", "") or "").strip()


_PFX = {"main": "ai", "backup": "ai2", "backup2": "ai3", "backup3": "ai4"}     # slot -> settings prefix


def _fix_provider(key, prov):
    """The key's own first letters win over a wrongly typed provider (e.g. an sk-or- OpenRouter key under 'openai')."""
    try:
        from . import ai_keyid
        g, sure = ai_keyid.guess(key)
        if g and sure:
            return g
    except Exception:
        pass
    return prov


def _auto_model(pfx, prov):
    """Model picked by 'Detect' for this slot (empty = none). Ignored if the provider changed since."""
    if str(_cfg(f"{pfx}_auto_prov", "") or "") != prov:
        return ""
    return str(_cfg(f"{pfx}_auto_model", "") or "").strip()


def _slots():
    out = []
    key, prov, model = _ai_key()
    if key:
        prov = _fix_provider(key, prov)
        out.append({"slot": "main", "key": key, "provider": prov, "model": model, "auto": _auto_model("ai", prov)})
    for n, name in ((2, "backup"), (3, "backup2"), (4, "backup3")):
        k = str(_cfg(f"ai{n}_api_key", "") or "").strip()
        if k:
            p = _fix_provider(k, str(_cfg(f"ai{n}_provider", "mistral") or "mistral").strip().lower())
            p = p if p in _OAI_STYLE or p in ("gemini", "anthropic") else "mistral"
            out.append({"slot": name, "key": k, "provider": p, "model": str(_cfg(f"ai{n}_model", "") or "").strip(),
                        "auto": _auto_model(f"ai{n}", p)})
    return out


def _rediscover(sl):
    """A model name came back 404 (retired). Ask the company which models exist, remember the best one. Returns it or ''."""
    try:
        from . import ai_keyid, settings_store
        res = ai_keyid.inspect(sl["key"], sl["provider"], force=True)
        m = res.get("model") or ""
        if m:
            pfx = _PFX.get(sl["slot"], "ai")
            settings_store.update(**{f"{pfx}_auto_model": m, f"{pfx}_auto_prov": sl["provider"]})
        return m
    except Exception:
        return ""


def ready():
    return bool(_slots())


def _short(r):
    try:
        j = r.json()
        e = j.get("error", j)
        m = e.get("message") if isinstance(e, dict) else str(e)
        return f"{r.status_code}: {str(m)[:160]}"
    except Exception:
        return f"{r.status_code}"


def _quota_wait(r):
    """Seconds to wait after a 429 answer. A DAILY limit -> probe again in 30 min, a per-minute limit -> what the server says."""
    txt = ""
    try:
        txt = r.text or ""
    except Exception:
        pass
    if re.search(r"PerDay|per day|daily|insufficient_quota|billing", txt, re.I):
        return QUOTA_PROBE_S
    m = re.search(r"retryDelay\"?\s*:\s*\"?(\d+(?:\.\d+)?)s", txt)
    if m:
        return min(3600, int(float(m.group(1))) + 2)
    try:
        return min(3600, max(5, int(float(r.headers.get("Retry-After", "")))))
    except Exception:
        return 60


def _slot_paused_until(sl):
    """When this slot can be used again (0 = now). A slot is paused only when ALL its candidate models are paused."""
    names = _slot_models(sl)
    now = time.time()
    waits = [_pause.get(f"{sl['slot']}:{n}", 0.0) for n in names]
    return 0.0 if not waits or min(waits) <= now else min(waits)


def _slot_models(sl):
    auto = sl.get("auto") or ""
    if sl["provider"] == "gemini":
        if sl["model"]:
            return [sl["model"]]
        first = [auto] if auto else ([_gem_ok["name"]] if _gem_ok["name"] else [])
        return first + [m for m in _GEMINI_MODELS if m not in first]
    if sl["provider"] == "anthropic":
        return [sl["model"] or auto or _ANTHROPIC_MODEL]
    return [sl["model"] or auto or _OAI_STYLE.get(sl["provider"], _OAI_STYLE["openai"])[1]]


def _try_gemini(sl, system, text, b64):
    last = "unknown error"
    for nm in _slot_models(sl):
        if _pause.get(f"{sl['slot']}:{nm}", 0.0) > time.time():
            continue
        gc = {"temperature": 0.2, "maxOutputTokens": 1000, "responseMimeType": "application/json"}
        if "2.5-flash" in nm:
            gc["thinkingConfig"] = {"thinkingBudget": 0}
        parts = [{"text": text}] + ([{"inline_data": {"mime_type": "image/png", "data": b64}}] if b64 else [])
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}], "generationConfig": gc}
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{nm}:generateContent",
                          headers={"x-goog-api-key": sl["key"], "Content-Type": "application/json"}, json=body, timeout=50)
        if r.status_code == 200:
            ps = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts") or []
            out = "".join(p.get("text", "") for p in ps if isinstance(p, dict))
            if out.strip():
                _gem_ok["name"] = nm
                return out, None, nm
            last = "empty answer"
            continue
        last = _short(r)
        if r.status_code == 429:
            _pause[f"{sl['slot']}:{nm}"] = time.time() + _quota_wait(r)
            continue
        if r.status_code == 404:                      # retired model name: pause it for a day, try the next one
            _pause[f"{sl['slot']}:{nm}"] = time.time() + 86400
            sug = re.search(r"use models/([\w.\-]+)", r.text)
            if sug and not sl["model"] and sug.group(1) not in _GEMINI_MODELS:
                _GEMINI_MODELS.append(sug.group(1))
            continue
        if r.status_code in (401, 403) or (r.status_code == 400 and "API key" in r.text):
            for n2 in _slot_models(sl):
                _pause[f"{sl['slot']}:{n2}"] = time.time() + 600
            return None, "AI key problem - " + last, nm
    return None, last, ""


def _try_anthropic(sl, system, text, b64):
    nm = _slot_models(sl)[0]
    content = ([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}] if b64 else []) + [{"type": "text", "text": text}]
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": sl["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": nm, "max_tokens": 900, "temperature": 0.2, "system": system, "messages": [{"role": "user", "content": content}]}, timeout=60)
    if r.status_code == 200:
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"), None, nm
    if r.status_code == 429:
        _pause[f"{sl['slot']}:{nm}"] = time.time() + _quota_wait(r)
    elif r.status_code in (401, 403):
        _pause[f"{sl['slot']}:{nm}"] = time.time() + 600
        return None, "AI key problem - " + _short(r), nm
    return None, _short(r), nm


def _try_oai(sl, system, text, b64):
    url, _dm = _OAI_STYLE.get(sl["provider"], _OAI_STYLE["openai"])
    user = [{"type": "text", "text": text}] + ([{"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}] if b64 else [])
    nm = _slot_models(sl)[0]
    for attempt in (0, 1):
        body = {"model": nm, "temperature": 0.2, "max_tokens": 900, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        r = requests.post(url, headers={"Authorization": f"Bearer {sl['key']}", "Content-Type": "application/json"}, json=body, timeout=60)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"], None, nm
        if r.status_code == 404 and not sl["model"] and attempt == 0:      # retired model name: ask the company for a live one, retry once
            newm = _rediscover(sl)
            if newm and newm != nm:
                nm = newm
                continue
        break
    if r.status_code == 429:
        _pause[f"{sl['slot']}:{nm}"] = time.time() + _quota_wait(r)
    elif r.status_code in (401, 403):
        _pause[f"{sl['slot']}:{nm}"] = time.time() + 600
        return None, "AI key problem - " + _short(r), nm
    elif r.status_code == 404:
        _pause[f"{sl['slot']}:{nm}"] = time.time() + 1800                  # do not hammer a model that does not exist
        return None, f"Model {nm} not found for this key. Open Settings > AI keys and press Detect.", nm
    return None, _short(r), nm


def quota_resume_at():
    """Earliest time any key slot can be used again, or 0 when one is free right now."""
    sls = _slots()
    if not sls:
        return 0.0
    ws = [_slot_paused_until(s) for s in sls]
    return 0.0 if min(ws) <= 0 else min(ws)


def _mon_add(slot, kind, secs):
    now = time.time()
    _mon.append((now, slot, kind, round(float(secs), 2)))
    if len(_mon) > 1500 or (_mon and now - _mon[0][0] > 86400 * 1.2):
        _mon[:] = [x for x in _mon if now - x[0] < 86400][-1500:]


def monitor():
    """Numbers for the AI Calls card (last 24 h): calls per key, how many worked / hit quota / failed, speed, and why it waits."""
    now = time.time()
    rows = [x for x in _mon if now - x[0] < 86400]
    slots = []
    for sl in _slots():
        mine = [x for x in rows if x[1] == sl["slot"]]
        ok = [x for x in mine if x[2] == "ok"]
        pu = _slot_paused_until(sl)
        slots.append({"slot": sl["slot"], "provider": sl["provider"], "model": (_slot_models(sl) or [""])[0], "last_error": _slot_err.get(sl["slot"], ""), "calls": len(mine), "ok": len(ok),
                      "quota": sum(1 for x in mine if x[2] == "quota"), "errors": sum(1 for x in mine if x[2] == "error"),
                      "avg_s": round(sum(x[3] for x in ok) / len(ok), 1) if ok else None,
                      "state": "paused" if pu > 0 else "ready", "paused_until": pu})
    with _lock:
        waiting = sum(1 for d in _state["dec"] if d.get("status") in ("queued", "waiting"))
    cap = int(_f(_cfg("vision_max_calls_day", 200), 200))
    return {"slots": slots, "used_24h": _day_used(), "cap": cap, "waiting": waiting, "last_min": len(_calls),
            "max_per_min": max(1, int(_f(_cfg("vision_max_per_min", 6), 6))), "last_error": _stat.get("error") or "",
            "model": _stat.get("model", ""),
            "tip": ("All keys are out of quota. Signals wait, stop-loss still works." if slots and all(x["state"] == "paused" for x in slots)
                    else "Some keys are out of quota, the others are answering." if len(slots) > 1 and any(x["state"] == "paused" for x in slots)
                    else "Everything is running." if slots else "No AI key yet.")}


def _call_ai(system, text, png=None):
    """-> (reply text, error). png=None = a text-only call (used by the learning notebook).
    Tries the main slot, then the backup slot. A quota answer pauses only that slot. When every slot is paused the error starts with
    'quota:' (callers keep the signal waiting instead of marking it ERROR)."""
    sls = _slots()
    if not sls:
        return None, "No AI key: add one in Settings > AI Assistant."
    b64 = base64.b64encode(png).decode() if png else None
    last = "unknown error"
    if len(sls) > 1:                      # share the load: start with a different ready key each call
        _rr[0] = (_rr[0] + 1) % len(sls)
        sls = sls[_rr[0]:] + sls[:_rr[0]]
    for attempt in range(2):
        transient = False
        for sl in sls:
            if _slot_paused_until(sl) > 0:
                continue
            t0 = time.time()
            try:
                fn = _try_gemini if sl["provider"] == "gemini" else _try_anthropic if sl["provider"] == "anthropic" else _try_oai
                out, err, nm = fn(sl, system, text, b64)
            except requests.exceptions.RequestException as e:
                out, err, nm = None, f"network: {str(e)[:120]}", ""
            except Exception as e:
                out, err, nm = None, f"unexpected: {str(e)[:120]}", ""
            try:
                _mon_add(sl["slot"], "ok" if (out is not None and str(out).strip()) else ("quota" if _slot_paused_until(sl) > 0 else "error"), time.time() - t0)
            except Exception:
                pass
            _slot_err[sl["slot"]] = "" if (out is not None and str(out).strip()) else ("" if _slot_paused_until(sl) > 0 and not err else str(err or "")[:200])
            if out is not None and str(out).strip():
                _stat["model"] = (sl["slot"] + ": " if sl["slot"] != "main" else "") + (nm or sl["provider"])
                _stat["error"] = ""
                return out, None
            if err:
                last = err
            if _slot_paused_until(sl) <= 0 and not (err or "").startswith("AI key problem"):
                transient = True
        if not transient:
            break
        time.sleep(2.0 * (attempt + 1))
    at = quota_resume_at()
    if at > 0:
        return None, "quota: " + (last if last != "unknown error" else "AI quota used up")
    return None, last


def _parse(text):
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        v = json.loads(t[a:b + 1])
        return v if isinstance(v, dict) else None
    except Exception:
        return None


def _count():
    now = time.time()
    _calls.append(now)
    _day_calls.append(now)


def _uncount():
    """A call that never reached the AI (quota) must not eat the daily budget."""
    if _calls:
        _calls.pop()
    if _day_calls:
        _day_calls.pop()


def _day_used():
    now = time.time()
    _day_calls[:] = [t for t in _day_calls if now - t < 86400]
    return len(_day_calls)


def _gate():
    now = time.time()
    _calls[:] = [t for t in _calls if now - t < 60]
    return len(_calls) < max(1, int(_f(_cfg("vision_max_per_min", 6), 6)))


def _short_txt(x, n=140):
    s = " ".join(str(x or "").split())
    return s[:n]


def _clean_check(c):
    if not isinstance(c, dict):
        return {}
    return {str(k)[:20]: _short_txt(v, 90) for k, v in list(c.items())[:9]}


# ------------------------------------------------------------------ prompts
def _lv_text(lv):
    parts = [f"last close {_fmt(lv['close'])}", f"EMA30 {_fmt(lv['e30'])}", f"EMA50 {_fmt(lv['e50'])}"]
    if lv.get("mean") is not None and lv.get("sd"):
        parts += [f"SD mean {_fmt(lv['mean'])}", f"+1SD {_fmt(lv['p1'])}", f"+2SD {_fmt(lv['p2'])}", f"+3SD {_fmt(lv['p3'])}",
                  f"-1SD {_fmt(lv['m1'])}", f"-2SD {_fmt(lv['m2'])}", f"-3SD {_fmt(lv['m3'])}"]
    parts += [f"lowest low of last 12 candles {_fmt(lv['low12'])}", f"highest high of last 12 candles {_fmt(lv['high12'])}",
              f"average candle range {_fmt(lv['avg_range'])}"]
    return "; ".join(parts)


def _signal_prompt(rec, lv, price, recent_ctx=""):
    prev = ""
    if rec.get("reason") and rec.get("decision") == "WAIT":
        prev = f"\nEarlier you said WAIT: \"{rec['reason']}\" (waiting for: {rec.get('wait_for') or 'a better entry'}). Check whether that has happened now.\n"
    try:
        from . import ai_vision_lessons as _L
        prev += _L.similar_block(rec["symbol"], rec["side"], rec.get("feat"))
    except Exception:
        pass
    ctx = f"\nRecent market context (use this; do not ignore a prior pump/dump): {recent_ctx}\n" if recent_ctx else "\n"
    ind = _indicator_summary(lv, rec.get("side") or "BUY", rec.get("feat"))
    ind_line = "; ".join(f"{k}={v}" for k, v in ind.items() if v)
    return (f"A bot signal just fired.\nSymbol: {rec['symbol']}; timeframe {_tf_label(rec['tf_min'])}; signal: {rec['side']} "
            f"(the bot wants to go {_side_word(rec['side'])}); bot entry price {_fmt(rec.get('sig_price'))}; price now {_fmt(price)}.\n"
            f"Numbers read from the same chart: {_lv_text(lv)}.\n"
            f"Indicator read (both families — EMA/SD and TSI/Z): {ind_line}.{ctx}{prev}\n"
            "You MUST weigh BOTH indicator families (EMA+SD bands AND TSI+Z-score). Do not decide from EMA alone.\n"
            "If price just pumped and is stretched at the top of the recent range, prefer SKIP or WAIT for BUY.\n"
            "Decide TAKE, SKIP or WAIT. TAKE = open the trade now. WAIT = the idea may work but the entry is not ready (say what you wait for; you will be asked again on the next candles). SKIP = do not trade.\n"
            "For TAKE give a stop (the price where the idea is wrong, beyond a recent swing or band) and a first target (the next level where price may stall). The target is NOT a fixed exit: you will manage the trade later from fresh charts.\n"
            "Answer with JSON only, in simple English:\n"
            '{"decision":"TAKE|SKIP|WAIT","reason":"one short sentence","checklist":{"ema":"","candles":"","sd_zone":"","tsi":"","zscore":"","divergence":"","room":""},"stop":number or null,"target":number or null,"wait_for":"short text or empty"}\n'
            "Each checklist answer: at most 12 words.")


def _review_prompt(tr, lv, price, why):
    roi = _roi(tr["side"], tr["entry"], price, tr["lev"])
    return (f"You are managing an open virtual {_side_word(tr['side'])} trade.\nSymbol: {tr['symbol']}; timeframe {_tf_label(tr['tf_min'])}; entry {_fmt(tr['entry'])}; "
            f"price now {_fmt(price)}; current stop {_fmt(tr['sl'])}; current target {_fmt(tr.get('target'))}; ROI now {roi:+.1f}% (leverage {tr['lev']:g}x); "
            f"best ROI so far {tr.get('peak_roi', 0):+.1f}%.\nWhy you are asked now: {why}.\n"
            f"Numbers read from the chart: {_lv_text(lv)}.\n"
            "The chart shows the entry, stop and target lines. Decide HOLD or EXIT. EXIT when momentum fades, a divergence shows, price is stretched at a band, or the structure breaks. "
            "HOLD while the trend is intact; you may move the stop closer in the profit direction (never further away) and move the target further if price keeps going. There is no fixed take-profit.\n"
            "Answer with JSON only, in simple English:\n"
            '{"action":"HOLD|EXIT","reason":"one short sentence","new_stop":number or null,"new_target":number or null,"checklist":{"momentum":"","divergence":"","bands":"","ema":""}}\n'
            "Each checklist answer: at most 12 words.")


# ------------------------------------------------------------------ records
def _find(coll, key, val):
    for r in coll:
        if r.get(key) == val:
            return r
    return None


def _live_price(symbol):
    try:
        from . import market_ws
        p, _src, _err = market_ws.get_best_live_price(symbol)
        if p:
            _px[symbol] = (float(p), time.time())
            return float(p)
    except Exception:
        pass
    v = _px.get(symbol)
    return v[0] if v and time.time() - v[1] < 120 else None


def _save_img(name, png):
    try:
        if not _img_dir:
            return
        with open(os.path.join(_img_dir, name + ".png"), "wb") as fh:
            fh.write(png)
        files = sorted((os.path.join(_img_dir, x) for x in os.listdir(_img_dir) if x.endswith(".png")), key=os.path.getmtime)
        for old in files[:-KEEP_IMG]:
            try:
                os.remove(old)
            except Exception:
                pass
    except Exception as e:
        print(f"[Vision] image: {e}")


def _open_for(symbol):
    with _lock:
        for t in _state["trades"]:
            if t["status"] == "open" and t["symbol"] == symbol:
                return t
    return None


def _open_count():
    with _lock:
        return sum(1 for t in _state["trades"] if t["status"] == "open")


def _note(tr, text):
    tr.setdefault("notes", []).append({"t": time.time(), "text": _short_txt(text, 220)})
    tr["notes"] = tr["notes"][-14:]


def _finish(rec, status, decision, reason):
    with _lock:
        rec["status"] = status
        if decision:
            rec["decision"] = decision
        rec["reason"] = _short_txt(reason, 200)
        rec["decided_at"] = time.time()
        _mark()


def _validate_take(side, price, stop, target, lv):
    stop, target = _f(stop), _f(target)
    risk_cap = float(_f(_cfg("vision_max_risk_pct", 3.0), 3.0))
    if side == "BUY":
        if not stop or stop >= price:
            stop = lv["low12"] if lv["low12"] < price else None
        if not stop:
            return None, None, "no valid stop below price"
        if not target or target <= price:
            target = price + 1.5 * (price - stop)
    else:
        if not stop or stop <= price:
            stop = lv["high12"] if lv["high12"] > price else None
        if not stop:
            return None, None, "no valid stop above price"
        if not target or target >= price:
            target = price - 1.5 * (stop - price)
    risk = abs(price - stop) / price * 100.0
    if risk < 0.12:
        return None, None, f"stop is too tight ({risk:.2f}% from price)"
    if risk > risk_cap:
        return None, None, f"stop is too far ({risk:.1f}% from price, limit {risk_cap:g}%)"
    return stop, target, None


def _open_trade(rec, price, stop, target):
    lev = _f(rec.get("lev"), 0) or _f(_cfg("leverage", 1), 1) or 1
    cur = _bar_start(time.time(), rec["tf_min"])
    tr = {"id": "v" + str(rec["signal_no"]), "dec_id": rec["id"], "symbol": rec["symbol"], "side": rec["side"], "tf_min": rec["tf_min"],
          "entry": price, "sl": stop, "sl0": stop, "target": target, "lev": lev,
          "invest": float(_f(_cfg("invest_amount", 10.0), 10.0)), "fee_roi": float(_f(_cfg("fee_roi_pct", 1.0), 1.0)),
          "opened_at": time.time(), "status": "open", "peak_roi": 0.0, "last_review_bar": cur, "tgt_bar": 0, "notes": [], "bar_ts": rec.get("bar_ts")}
    _note(tr, f"Opened {_side_word(rec['side'])} at {_fmt(price)}. Stop {_fmt(stop)}, target {_fmt(target)}. {rec.get('reason', '')}")
    with _lock:
        _state["trades"].append(tr)
        rec["trade_id"] = tr["id"]
        _mark()
    return tr


def _close_trade(tr, price, reason):
    with _lock:
        if tr["status"] != "open":
            return
        gross = _roi(tr["side"], tr["entry"], price, tr["lev"])
        net = gross - tr["fee_roi"]
        tr.update(status="closed", exit=price, exit_reason=reason, closed_at=time.time(), roi=net, pnl=tr["invest"] * net / 100.0)
        _note(tr, f"Closed at {_fmt(price)}: {reason}. Result {tr['pnl']:+.2f} USDT after fees.")
        _mark()


def _bar_start(now, tf_min):
    s = tf_min * 60
    return int(now // s) * s


# ------------------------------------------------------------------ the work
def _scan_signals():
    from . import db
    try:
        rows = db.get_recent_signals(40)
    except Exception:
        return
    only_open = bool(_cfg("vision_only_opened", True))
    with _lock:
        known = {d["signal_no"] for d in _state["dec"]}
        since = _state["since"]
        for r in reversed(rows):
            no = r.get("signal_no")
            if no is None or no in known or (r.get("recorded_at") or 0) < since:
                continue
            if only_open and not r.get("opened"):
                continue
            side = "BUY" if str(r.get("action", "")).upper() in ("BUY", "LONG") else "SELL"
            tfm = _tf_min(r.get("timeframe"))
            _state["dec"].append({"id": "s" + str(no), "signal_no": no, "symbol": r["symbol"], "side": side, "tf_min": tfm,
                                  "sig_price": r.get("entry_price"), "sig_time": r.get("recorded_at"), "sig_ist": r.get("ist_time_str"),
                                  "lev": r.get("leverage"), "status": "queued", "decision": None, "reason": "", "checklist": {},
                                  "checks": 0, "waits_left": WAITS, "last_bar": 0, "bar_ts": None})
            known.add(no)
            _mark()


def _bot_outcomes():
    now = time.time()
    if now - _botmap["t"] < 20:
        return _botmap
    try:
        from . import trade_store, paper_trader
        closed = {}
        for t in trade_store.get_recent_closed(1500, net=True):
            no = t.get("signal_no")
            if no is not None and t.get("pnl_usdt") is not None:
                closed[no] = float(t["pnl_usdt"])
        with paper_trader._lock:
            opened = {p.get("signal_no") for p in paper_trader._positions.values() if (p.get("bot") or "b1") == "b1"}   # Bot 2 numbers its signals separately
        _botmap.update(t=now, closed=closed, open=opened)
    except Exception:
        _botmap["t"] = now
    return _botmap


def _process_signal(rec):
    """One AI look at a bot signal (new, or a WAIT being re-checked)."""
    sym, tf = rec["symbol"], rec["tf_min"]
    ot = _open_for(sym)
    if ot:
        if ot["side"] == rec["side"]:
            return _finish(rec, "skipped", "SKIP", "The AI already holds this symbol.")
        _review(ot, f"the bot just gave an opposite {rec['side']} signal")
        if ot["status"] == "open":
            return _finish(rec, "skipped", "SKIP", "The AI is still holding the opposite trade.")
    if _open_count() >= int(_f(_cfg("vision_max_open", 8), 8)):
        return _finish(rec, "skipped", "SKIP", "AI trade limit reached.")
    try:
        candles = _fetch(sym, tf)
    except Exception as e:
        return _retry(rec, f"candles: {str(e)[:80]}")
    if len(candles) < 260:
        return _finish(rec, "error", None, "Not enough candle history for this coin.")
    price = _live_price(sym) or candles[-1]["close"]
    rec["bar_ts"] = candles[-1]["timestamp"]
    try:
        png = render_chart(sym, candles, _tf_label(tf), rec["side"], {"bar_ts": rec["bar_ts"]})
        _f_, _e, lv = _levels(candles)
        try:                                               # measured tags for the learning notebook (plain arithmetic, no AI)
            from . import ai_vision_lessons as L
            rec["feat"] = L.features(_f_, rec["side"])
        except Exception:
            pass
        rec["indicator_summary"] = _indicator_summary(lv, rec["side"], rec.get("feat"))
        recent_ctx = _recent_context(candles, rec["side"])
        rec["recent_context"] = recent_ctx
    except ImportError:
        return _finish(rec, "error", None, "Pillow is missing on the backend. Run: pkg install python-pillow")
    except Exception as e:
        return _retry(rec, f"chart: {str(e)[:80]}")
    _count()
    text, err = _call_ai(guide_text(sym, rec["side"]),
                         _signal_prompt(rec, lv, price, recent_ctx=rec.get("recent_context") or ""), png)
    if err and str(err).startswith("quota:"):
        # No quota left on any key: the signal just WAITS (it is not an error and it does not use up its 3 tries).
        _uncount()
        _stat["error"] = err
        _stat["pause_until"] = quota_resume_at() or (time.time() + 60)
        rec["next_try"] = _stat["pause_until"]
        _log(f"{sym}: AI quota used up, waiting until {_ist(_stat['pause_until'])} IST")
        return
    rec["checks"] = rec.get("checks", 0) + 1
    _save_img(rec["id"], png)
    rec["img"] = True
    if err:
        _stat["error"] = err
        if "key problem" in err:
            _stat["pause_until"] = time.time() + 120
            return _finish(rec, "error", None, err)
        return _retry(rec, err)
    out = _parse(text)
    _stat["error"] = ""
    _stat["ok_at"] = time.time()
    if not out:
        return _retry(rec, "the AI answer could not be read")
    dec = str(out.get("decision", "")).upper()
    with _lock:
        rec["reason"] = _short_txt(out.get("reason"))
        rec["checklist"] = _clean_check(out.get("checklist"))
        rec["wait_for"] = _short_txt(out.get("wait_for"), 100)
        rec["decision"] = dec if dec in ("TAKE", "SKIP", "WAIT") else "SKIP"
        rec["decided_at"] = time.time()
        _mark()
    if rec["decision"] == "TAKE":
        stop, target, bad = _validate_take(rec["side"], price, out.get("stop"), out.get("target"), lv)
        if bad:
            return _finish(rec, "skipped", "SKIP", f"The AI said TAKE but {bad}.")
        rec["stop"], rec["target"] = stop, target
        _open_trade(rec, price, stop, target)
        rec["status"] = "taken"
    elif rec["decision"] == "WAIT":
        rec["waits_left"] = rec.get("waits_left", WAITS) - 1
        if rec["waits_left"] <= 0:
            return _finish(rec, "expired", "SKIP", "Waited several candles; the entry never became ready.")
        rec["status"] = "waiting"
        rec["last_bar"] = _bar_start(time.time(), tf)
    else:
        rec["status"] = "skipped"
    _mark()


def _retry(rec, why):
    rec["tries"] = rec.get("tries", 0) + 1
    if rec["tries"] >= 3:
        return _finish(rec, "error", None, f"AI check failed: {why}")
    rec["next_try"] = time.time() + 20
    _log(f"{rec['symbol']}: {why} (retry {rec['tries']})")


def _review(tr, why):
    """One AI look at an open trade: HOLD or EXIT, may move the stop / target."""
    sym, tf = tr["symbol"], tr["tf_min"]
    try:
        candles = _fetch(sym, tf)
        price = _live_price(sym) or candles[-1]["close"]
        marks = {"entry": tr["entry"], "sl": tr["sl"], "target": tr.get("target"), "bar_ts": tr.get("bar_ts")}
        png = render_chart(sym, candles, _tf_label(tf), tr["side"], marks)
        _f_, _e, lv = _levels(candles)
    except Exception as e:
        tr["last_review_bar"] = _bar_start(time.time(), tf)
        return _log(f"review {sym}: {str(e)[:80]}")
    _count()
    text, err = _call_ai(guide_text(sym, tr["side"]), _review_prompt(tr, lv, price, why), png)
    tr["last_review_bar"] = _bar_start(time.time(), tf)
    if err and str(err).startswith("quota:"):
        _uncount()
        _stat["error"] = err
        _stat["pause_until"] = quota_resume_at() or (time.time() + 60)
        tr["last_review_bar"] = 0                       # look again as soon as the quota is back (the hard stop keeps working meanwhile)
        return
    _save_img(tr["id"], png)
    if err:
        _stat["error"] = err
        if "key problem" in err:
            _stat["pause_until"] = time.time() + 120
        return _log(f"review {sym}: {err}")
    out = _parse(text)
    if not out:
        return
    _stat["error"] = ""
    _stat["ok_at"] = time.time()
    with _lock:
        side = tr["side"]
        ns, nt = _f(out.get("new_stop")), _f(out.get("new_target"))
        moved = []
        if ns and ((side == "BUY" and tr["sl"] < ns < price * 0.9995) or (side == "SELL" and tr["sl"] > ns > price * 1.0005)):
            tr["sl"] = ns
            moved.append(f"stop to {_fmt(ns)}")
        if nt and ((side == "BUY" and nt > price) or (side == "SELL" and nt < price)):
            tr["target"] = nt
            moved.append(f"target to {_fmt(nt)}")
        tr["last_checklist"] = _clean_check(out.get("checklist"))
        act = str(out.get("action", "HOLD")).upper()
        txt = f"{'EXIT' if act == 'EXIT' else 'HOLD'}: {_short_txt(out.get('reason'))}" + (f" (moved {', '.join(moved)})" if moved else "")
        _note(tr, txt)
        _mark()
    if act == "EXIT":
        _close_trade(tr, price, "AI exit: " + _short_txt(out.get("reason"), 90))


def _tick_trades():
    """Hard stop on every tick (no AI call), best-ROI tracking, and 'target touched' flags."""
    with _lock:
        opens = [t for t in _state["trades"] if t["status"] == "open"]
    for tr in opens:
        px = _live_price(tr["symbol"])
        if not px:
            continue
        buy = tr["side"] == "BUY"
        if (buy and px <= tr["sl"]) or (not buy and px >= tr["sl"]):
            _close_trade(tr, tr["sl"], "Stop loss hit")
            continue
        roi = _roi(tr["side"], tr["entry"], px, tr["lev"])
        if roi > tr.get("peak_roi", 0):
            tr["peak_roi"] = roi
            _mark()
        tg = tr.get("target")
        if tg and ((buy and px >= tg) or (not buy and px <= tg)):
            tr["target_touched"] = True


def _next_job():
    now = time.time()
    review_n = max(1, int(_f(_cfg("vision_review_candles", 4), 4)))
    with _lock:
        trades = [t for t in _state["trades"] if t["status"] == "open"]
        decs = list(_state["dec"])
    for t in trades:                                   # 0: open trades first - they hold (virtual) money
        cur = _bar_start(now, t["tf_min"])
        if now - cur < 5:
            continue
        if t.get("target_touched") and t.get("tgt_bar") != cur:
            t["tgt_bar"] = cur
            t["target_touched"] = False
            return ("review", t, "price touched your target - decide to extend or exit")
        if cur - t.get("last_review_bar", 0) >= review_n * t["tf_min"] * 60:
            return ("review", t, f"regular check after {review_n} closed candle(s)")
    for r in decs:                                     # 1: new signals (oldest first), drop the stale ones
        if r["status"] != "queued":
            continue
        age = now - (r.get("sig_time") or now)
        if age > r["tf_min"] * 60 + 90:
            _finish(r, "late", None, "The AI was busy; this signal was too old to judge.")
            continue
        if r.get("next_try", 0) <= now:
            return ("signal", r, "")
    for r in decs:                                     # 2: WAIT re-checks on a new closed candle
        if r["status"] == "waiting":
            cur = _bar_start(now, r["tf_min"])
            if now - cur >= 5 and cur > r.get("last_bar", 0) and r.get("next_try", 0) <= now:
                if now - (r.get("sig_time") or now) > r["tf_min"] * 60 * (WAITS + 2):
                    _finish(r, "expired", "SKIP", "Waited several candles; the entry never became ready.")
                    continue
                return ("signal", r, "")
    return None


def _expire_stale():
    """Signals that waited too long (AI busy or no quota) are closed with an honest reason instead of hanging in the queue."""
    now = time.time()
    with _lock:
        decs = list(_state["dec"])
    for r in decs:
        if r["status"] == "queued" and now - (r.get("sig_time") or now) > r["tf_min"] * 60 + 90:
            out_of_quota = now < _stat["pause_until"] or quota_resume_at() > 0
            _finish(r, "late", None, "The AI had no quota left; this signal was too old to judge." if out_of_quota
                    else "The AI was busy; this signal was too old to judge.")


def _lessons_job():
    """Idle time = write a lesson / the daily rules. Never when the budget is nearly used (signals come first)."""
    if not bool(_cfg("vision_lessons_enabled", True)):
        return False
    cap = int(_f(_cfg("vision_max_calls_day", 200), 200))
    if cap > 0 and _day_used() >= int(cap * 0.7):
        return False
    try:
        import sys
        from . import ai_vision_lessons as L
        return bool(L.next_job(sys.modules[__name__]))
    except Exception as e:
        _log(f"notebook: {str(e)[:100]}")
        return False


def _step():
    if not enabled():
        return False
    _scan_signals()
    _tick_trades()
    _expire_stale()
    if time.time() < _stat["pause_until"] or not ready() or not _gate():
        return False
    job = _next_job()
    if not job:
        return _lessons_job()
    kind, obj, why = job
    cap = int(_f(_cfg("vision_max_calls_day", 200), 200))
    if cap > 0:                                        # the owner's daily budget: new signals stop first, open-trade checks get 50% extra
        used = _day_used()
        if (kind == "signal" and used >= cap) or (kind == "review" and used >= int(cap * 1.5)):
            if kind == "signal":
                _finish(obj, "late", None, f"Daily AI limit reached ({cap} calls). Raise vision_max_calls_day to judge more.")
            return False
    if kind == "review":
        _review(obj, why)
    else:
        _process_signal(obj)
    return True


def _loop():
    _load()
    while True:
        try:
            did = _step()
            _save()
            time.sleep(0.4 if did else TICK_S)
        except Exception as e:
            _log(f"loop: {str(e)[:120]}")
            time.sleep(TICK_S)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="ai-vision", daemon=True).start()


# ------------------------------------------------------------------ read side (the app)
def _trade_view(t):
    px = _live_price(t["symbol"]) if t["status"] == "open" else None
    v = {k: t.get(k) for k in ("id", "dec_id", "symbol", "side", "tf_min", "entry", "sl", "sl0", "target", "lev", "invest", "opened_at",
                              "status", "peak_roi", "exit", "exit_reason", "closed_at", "roi", "pnl", "notes", "last_checklist")}
    if t["status"] == "open" and px:
        gross = _roi(t["side"], t["entry"], px, t["lev"])
        v["price"] = px
        v["roi"] = gross - t["fee_roi"]
        v["pnl"] = t["invest"] * v["roi"] / 100.0
    v["tf"] = _tf_label(t["tf_min"])
    return v


def _indicator_use(decs):
    """How often the AI's own checklist answered each indicator (both families). Plain counts, no opinion."""
    judged = [d for d in decs if d.get("decision") in ("TAKE", "SKIP", "WAIT") and isinstance(d.get("checklist"), dict) and d.get("checklist")]
    def has(d, k):
        return len(str((d.get("checklist") or {}).get(k) or "").strip()) >= 3
    out = {"n": len(judged), "ema": 0, "sd": 0, "tsi": 0, "zscore": 0, "both": 0}
    for d in judged:
        e, sd, t, z = has(d, "ema"), has(d, "sd_zone"), has(d, "tsi"), has(d, "zscore")
        out["ema"] += e; out["sd"] += sd; out["tsi"] += t; out["zscore"] += z
        if (e or sd) and (t or z):
            out["both"] += 1
    return out


def snapshot(limit=80):
    _load()
    bm = _bot_outcomes()
    with _lock:
        trades = [dict(t) for t in _state["trades"]]
        decs = [dict(d) for d in _state["dec"]]
        log = list(_state["log"][-8:])
    closed = [t for t in trades if t["status"] == "closed"]
    opens = [t for t in trades if t["status"] == "open"]
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    net = sum(t.get("pnl") or 0 for t in closed)
    ov = [_trade_view(t) for t in opens]
    unreal = sum(v.get("pnl") or 0 for v in ov)
    taken_bot = [bm["closed"][d["signal_no"]] for d in decs if d["status"] == "taken" and d["signal_no"] in bm["closed"]]
    skip_bot = [bm["closed"][d["signal_no"]] for d in decs if d["status"] in ("skipped", "expired") and d["signal_no"] in bm["closed"]]
    tv = {t["dec_id"]: t for t in trades}
    out_dec = []
    for d in reversed(decs[-limit:]):
        x = {k: d.get(k) for k in ("id", "signal_no", "symbol", "side", "status", "decision", "reason", "checklist", "stop", "target",
                                   "sig_price", "sig_ist", "sig_time", "decided_at", "checks", "waits_left", "wait_for", "trade_id",
                                   "indicator_summary", "recent_context", "feat")}
        x["tf"] = _tf_label(d["tf_min"])
        no = d["signal_no"]
        x["bot"] = {"state": "closed", "pnl": bm["closed"][no]} if no in bm["closed"] else ({"state": "open"} if no in bm["open"] else None)
        t = tv.get(d["id"])
        if t:
            x["trade"] = {"status": t["status"], "pnl": (_trade_view(t).get("pnl")), "roi": _trade_view(t).get("roi")}
        out_dec.append(x)
    key, provider, _m = _ai_key()
    msg = ""
    if not enabled():
        msg = "Vision AI is switched off."
    elif not key:
        msg = "Add your AI key in Settings > AI Assistant to start the Vision AI."
    elif quota_resume_at() <= 0 and int(_f(_cfg("vision_max_calls_day", 200), 200)) > 0 and _day_used() >= int(_f(_cfg("vision_max_calls_day", 200), 200)):
        msg = f"Daily AI limit reached ({int(_f(_cfg('vision_max_calls_day', 200), 200))} calls in 24 h). New signals are not judged until calls free up."
    elif quota_resume_at() > 0:
        msg = (f"AI quota is used up on every key. Signals wait and the stop-loss still works. Trying again at {_ist(quota_resume_at())} IST."
               + ("" if len(_slots()) > 1 else " Tip: add free backup keys in Settings > AI Assistant (Backup key 1-3)."))
    elif _stat["error"]:
        msg = "Last AI problem: " + _stat["error"]
    return {
        "ready": bool(key) and enabled(), "message": msg, "provider": provider, "model": _stat.get("model", ""),
        "backup": len(_slots()) > 1, "paused_until": quota_resume_at(),
        "since": _state["since"], "calls_last_min": len(_calls), "calls_24h": _day_used(), "monitor": monitor(),
        "summary": {"closed": len(closed), "wins": len(wins), "net": net, "unrealized": unreal, "open": len(opens),
                    "win_rate": (len(wins) * 100.0 / len(closed)) if closed else None,
                    "avg": (net / len(closed)) if closed else None,
                    "signals": len(decs), "take": sum(1 for d in decs if d["status"] == "taken"),
                    "skip": sum(1 for d in decs if d["status"] in ("skipped", "expired")),
                    "wait": sum(1 for d in decs if d["status"] == "waiting"),
                    "queued": sum(1 for d in decs if d["status"] == "queued"),
                    "bot_on_taken": {"n": len(taken_bot), "net": sum(taken_bot)},
                    "bot_on_skipped": {"n": len(skip_bot), "net": sum(skip_bot),
                                       "wins": sum(1 for x in skip_bot if x > 0), "losses": sum(1 for x in skip_bot if x <= 0)}},
        "open": ov, "closed": [_trade_view(t) for t in reversed(closed[-40:])], "decisions": out_dec, "log": log,
        "indicator_use": _indicator_use(decs),
    }


def image_bytes(item_id, live=False):
    """The saved decision picture, or a fresh picture (with the stop / target lines) when live=True."""
    _load()
    item_id = re.sub(r"[^A-Za-z0-9_]", "", str(item_id))
    if not live and _img_dir:
        p = os.path.join(_img_dir, item_id + ".png")
        if os.path.exists(p):
            with open(p, "rb") as fh:
                return fh.read()
    with _lock:
        tr = _find(_state["trades"], "id", item_id) or _find(_state["trades"], "dec_id", item_id)
        dec = _find(_state["dec"], "id", item_id) or (_find(_state["dec"], "id", tr["dec_id"]) if tr else None)
        tr = dict(tr) if tr else None
        dec = dict(dec) if dec else None
    src = tr or dec
    if not src:
        return None
    candles = _fetch(src["symbol"], src["tf_min"])
    if len(candles) < 100:
        return None
    marks = {"bar_ts": (tr or dec).get("bar_ts")}
    if tr:
        marks.update(entry=tr["entry"], sl=tr["sl"], target=tr.get("target"), exit=tr.get("exit"))
    elif dec and dec.get("stop"):
        marks.update(sl=dec.get("stop"), target=dec.get("target"))
    return render_chart(src["symbol"], candles, _tf_label(src["tf_min"]), src["side"], marks)


def set_notes(text):
    from . import settings_store
    settings_store.update(vision_notes=str(text or "")[:4000])
    return {"ok": True}

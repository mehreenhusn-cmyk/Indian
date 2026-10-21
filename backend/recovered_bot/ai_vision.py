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
CANDLES = 600          # VIEW(90) + ~400 for Z-SMA200 + margin; Binance limit 1500
VIEW = 90              # candles drawn
TICK_S = 3.0
WAITS = 3              # a WAIT is looked at again on up to 3 more candles

_lock = threading.RLock()
_state = {"dec": [], "trades": [], "since": 0.0, "log": [], "scan": []}   # "scan" = AI Own scan log, one row per coin per candle
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
_ANTHROPIC_MODEL = "claude-haiku-5-5"        # cheap model for chart reading; old default was claude-haiku-4-5-20251001
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
- A small HIST box in this pane (and the same numbers in the text you are given) shows the last 5 bars, oldest to newest, one trend word and one plain line. Growing = the push is getting stronger; Shrinking = the push is fading; Flipping up / Flipping down = the push just changed side; Flat = no clear push. Plain lines: Buyers coming in, Buyers leaving, Sellers coming in, Sellers leaving, Buyers taking over, Sellers taking over, No clear push. The box can also show the last 10 bars (red below 0, green above 0) and where TSI and its signal line sit against zero. IMPORTANT: a shrinking histogram alone is never a reason to buy or sell. If TSI and the signal line are still below 0, sellers are still in control, so do not buy early just because the bars are shrinking; check Z-score, EMA and SD levels yourself first. Use these numbers, do not guess the bars from the picture. When the note matters for your decision, say it in your reason (for example: skipped because the histogram is shrinking, buyers leaving).

Z-SCORE PANE (bottom)
- Green area = upside momentum. Red area = downside momentum. The black line = Z-SMA (200-candle average of Z).
- The black line is the average level of Z. It can act as SUPPORT when Z falls onto it from above, and as RESISTANCE when Z rises up to it from below. This is a clue, not a rule.
- Z above the black line = momentum above its own average; Z below = below average.
- Shaded zones: inside 1 sigma, 1-2 sigma, 2-3 sigma. The further out, the more stretched.
- Divergence: price makes a new high while Z falls (or the reverse) can show weakness. Clue, not a rule.

HOW THE TWO SCRIPTS FIT TOGETHER
- Script 1 (main chart): EMA30 green / EMA50 red + SD bands = where price is and how stretched.
- Script 2 (TSI + Z + Z-SMA): the push behind the move. Check that BOTH agree with the trade's side before TAKE.
- If Script 1 looks fine but Script 2 disagrees (or the reverse), prefer WAIT or SKIP.

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
    try:                                                   # pump/dump memory + buyer/seller (measured, no AI)
        from . import ai_pumpdump as PD
        out += PD.prompt_block(symbol, side)
    except Exception as e:
        print(f"[Vision] pumpdump: {e}")
    try:
        from . import ai_vision_exits as XE
        out += XE.prompt_block()
    except Exception as e:
        print(f"[Vision] exits: {e}")
    try:
        from . import ai_level_study as LS
        if hasattr(LS, "headline"):
            h = LS.headline()
            if h:
                out += f"\n\nLEVEL STUDY (read-only peek, n in text): {h}"
        elif hasattr(LS, "snapshot"):
            snap = LS.snapshot()
            if isinstance(snap, dict) and snap.get("headline"):
                out += f"\n\nLEVEL STUDY (read-only peek): {snap['headline']}"
    except Exception:
        pass
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
        from . import ai_pumpdump as PD
        PD.init(path)
        from . import ai_vision_exits as XE
        XE.init(path)
        from . import ai_vision_days as VD
        VD.init(path)
        try:
            VD.backfill(__import__('sys').modules[__name__])
        except Exception as _e:
            print(f'[Vision] days backfill: {_e}')
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
                    for k in ("dec", "trades", "log", "scan"):
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
            try:
                from . import ai_vision_days as VD
                import sys
                VD.rollup(sys.modules[__name__])
            except Exception:
                pass
            _state["dec"] = _state["dec"][-KEEP_DEC:]
            _state["trades"] = _state["trades"][-KEEP_TRADES:]
            _state["scan"] = _state.get("scan", [])[-600:]
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


def _last_num(arr):
    for x in reversed(list(arr or [])):
        if x is not None:
            return float(x)
    return None


def hist_note(f, take=5):
    """Plain read of the TSI histogram bars (TSI minus signal) - the same numbers the chart draws.
    Returns {"vals", "word", "line", "text", "short"}. Words: Growing, Shrinking, Flipping up, Flipping down, Flat."""
    raw = list((f or {}).get("diff") or [])[-take:]
    if len(raw) < take or any(v is None for v in raw):
        return {"vals": [], "word": "Unknown", "line": "Not enough bars", "short": "Not enough bars",
                "text": "TSI histogram: not enough bars to read it."}
    v = [float(x) for x in raw]
    pos = v[-1] >= 0
    if pos and (v[-2] < 0 or v[-3] < 0):
        word, line = "Flipping up", "Buyers taking over"
    elif (not pos) and (v[-2] >= 0 or v[-3] >= 0):
        word, line = "Flipping down", "Sellers taking over"
    else:
        a = [abs(x) for x in v[-3:]]
        who = "Buyers" if pos else "Sellers"
        if a[0] < a[1] < a[2]:
            word, line = "Growing", who + " coming in"
        elif a[0] > a[1] > a[2]:
            word, line = "Shrinking", who + " leaving"
        else:
            word, line = "Flat", "No clear push"
    dec = 2 if max(abs(x) for x in v) < 1 else 1
    nums = [f"{x:+.{dec}f}" for x in v]
    # v2: the last 10 bars (two rows of 5 in the box), where TSI and its signal line sit against zero,
    # and a plain line that says what the bars mean in that place. A shrinking bar alone is never a buy.
    all10 = [x for x in list((f or {}).get("diff") or [])[-10:] if x is not None]
    v10 = [round(float(x), 3) for x in all10] if len(all10) >= take else [round(x, 3) for x in v]
    tsi = _last_num((f or {}).get("tsi"))
    tsl = _last_num((f or {}).get("tsl"))
    pos_txt, ctx, ctx_short = "", "", ""
    if tsi is not None and tsl is not None:
        d2 = 2 if max(abs(tsi), abs(tsl)) < 1 else 1
        if tsi < 0 and tsl < 0:
            side = "both below 0 (sellers' side)"
        elif tsi > 0 and tsl > 0:
            side = "both above 0 (buyers' side)"
        else:
            side = "on different sides of 0 (mixed)"
        pos_txt = f"TSI {tsi:+.{d2}f}, signal line {tsl:+.{d2}f}: {side}."
        below, above = tsi < 0 and tsl < 0, tsi > 0 and tsl > 0
        if word == "Shrinking" and below:
            ctx = "Sellers still in control but weakening. Not a buy yet: wait for the histogram above 0."
            ctx_short = "Sellers weakening - not a buy yet"
        elif word == "Shrinking" and above:
            ctx = "Buyers still in control but weakening. Not a sell yet: wait for the histogram below 0."
            ctx_short = "Buyers weakening - not a sell yet"
        elif word == "Flipping up" and not above:
            ctx = "Histogram just turned up but TSI and signal are not above 0 yet. Early: wait for them to cross above 0."
            ctx_short = "Turned up - TSI still not above 0"
        elif word == "Flipping down" and not below:
            ctx = "Histogram just turned down but TSI and signal are not below 0 yet. Early: wait for them to cross below 0."
            ctx_short = "Turned down - TSI still not below 0"
        elif word == "Growing" and below:
            ctx = "Sellers in control and getting stronger. Not a buy."
            ctx_short = "Sellers getting stronger"
        elif word == "Growing" and above:
            ctx = "Buyers in control and getting stronger. Not a sell."
            ctx_short = "Buyers getting stronger"
    if not ctx_short:
        ctx_short = line
    n10 = [f"{x:+.{dec}f}" for x in v10]
    text = (f"TSI histogram (last {len(v10)} closed bars, oldest to newest): {', '.join(n10)}. Trend: {word}. {line}."
            + (f" {pos_txt}" if pos_txt else "") + (f" {ctx}" if ctx else "")
            + " A shrinking histogram alone is never a reason to buy or sell: also check Z-score, EMA and SD levels.")
    return {"vals": [round(x, 3) for x in v], "vals10": v10, "word": word, "line": line, "ctx": ctx, "ctx_short": ctx_short,
            "pos": pos_txt, "short": f"{word} - {line} ({', '.join(nums)})", "text": text}


def render_chart(symbol, candles, tf_label, side=None, marks=None, title_extra="", source=None):
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
    for _e in (marks.get("trail") or []):
        for _k in ("sl", "price"):
            v = _f(_e.get(_k))
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
    zsma_draw = [None if v is None else max(-ZR, min(ZR, v)) for v in f.get("zsma") or []]
    poly(zsma_draw, gz, (0, 0, 0), 4)  # thicker than Z so the average line stands out
    # label at the right end of the last non-None Z-SMA point
    for _i in range(n - 1, lo - 1, -1):
        if _i < len(zsma_draw) and zsma_draw[_i] is not None:
            d.text((min(sx(_i) + 4, x1 - 70), gz(zsma_draw[_i]) - 10), "Z-SMA 200", fill=(0, 0, 0), font=f12)
            break

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
    # ---- stop-trail (steps) and profit points (banked part), only when the trade has them
    try:
        trail = [e for e in (marks.get("trail") or []) if isinstance(e, dict)]
        if trail:
            def _bar(ts_s):
                jj = lo
                for i in range(lo, n):
                    if f["t"][i] / 1000.0 <= ts_s:
                        jj = i
                return jj
            stops = [e for e in trail if e.get("kind") == "stop" and _f(e.get("sl"))]
            prev_x, prev_y = None, None
            if stops and _f(marks.get("sl0")) and marks.get("opened_at"):
                stops = [{"t": marks["opened_at"], "kind": "stop", "sl": marks["sl0"]}] + stops
            for e in stops:
                xx, yy = sx(_bar(float(e["t"]))), gy(_f(e["sl"]))
                if prev_y is not None:
                    d.line([prev_x, prev_y, xx, prev_y], fill=(255, 112, 67), width=2)
                    d.line([xx, prev_y, xx, yy], fill=(255, 112, 67), width=2)
                d.ellipse([xx - 4, yy - 4, xx + 4, yy + 4], fill=(255, 112, 67))
                prev_x, prev_y = xx, yy
            if prev_y is not None:
                d.line([prev_x, prev_y, x1, prev_y], fill=(255, 112, 67), width=2)
                d.text((max(x0 + 2, prev_x - 70), prev_y - 16), "STOP TRAIL", fill=(230, 81, 0), font=f12)
            for e in trail:
                if e.get("kind") == "partial" and _f(e.get("price")):
                    xx, yy = sx(_bar(float(e["t"]))), gy(_f(e["price"]))
                    d.polygon([(xx, yy - 9), (xx - 8, yy + 6), (xx + 8, yy + 6)], fill=(0, 150, 136))
                    d.text((xx + 10, yy - 8), "PROFIT BANKED", fill=(0, 105, 92), font=f12)
    except Exception:
        pass
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

    # ---- TSI histogram note box (top-right of the TSI pane; moves to the bottom if bars or lines are there)
    try:
        hn = hist_note(f)
        v10 = hn.get("vals10") or hn["vals"]
        dec_ = (2 if max(abs(y) for y in v10) < 1 else 1) if v10 else 1
        rows = [v10[:-5], v10[-5:]] if len(v10) >= 10 else [v10]
        rows = [r for r in rows if r]
        l3 = f"{hn['word']} - {hn['line']}" if hn["vals"] else hn["line"]
        l4 = hn.get("ctx_short") or ""
        lines_w = [d.textlength("HIST  " + "  ".join(f"{x:+.{dec_}f}" for x in r), font=f12) for r in rows]
        bw_ = max(lines_w + [d.textlength(l3, font=f12), d.textlength(l4, font=f12)]) + 14
        rh = 15
        nrow = len(rows) + 1 + (1 if l4 and l4 != hn["line"] else 0)
        bh_ = nrow * rh + 6
        bx1 = x1 - 6
        bx0 = bx1 - bw_

        def _hit(y0, y1):
            for i in range(lo, n):
                if sx(i) < bx0 - step or sx(i) > bx1 + step:
                    continue
                df_ = f["diff"][i]
                if df_ is not None and max(min(z0, gt(df_)), y0) <= min(max(z0, gt(df_)), y1):
                    return True
                for val in (f["tsi"][i], f["tsl"][i]):
                    if val is not None and y0 <= gt(val) <= y1:
                        return True
            return False
        by0 = PT[0] + 4
        if _hit(by0, by0 + bh_):
            alt = PT[1] - bh_ - 4
            if not _hit(alt, alt + bh_):
                by0 = alt
        d.rectangle([bx0, by0, bx1, by0 + bh_], fill=(255, 255, 255), outline=(120, 120, 120))
        y = by0 + 3
        if not v10:
            d.text((bx0 + 6, y), "HIST  not enough bars", fill=(40, 40, 40), font=f12)
            y += rh
        for ri, r in enumerate(rows):
            xx = bx0 + 6
            lab = "HIST  " if ri == 0 else "      "
            d.text((xx, y), lab, fill=(40, 40, 40), font=f12)
            xx += d.textlength(lab, font=f12)
            for x_ in r:
                t_ = f"{x_:+.{dec_}f}  "
                d.text((xx, y), t_, fill=((8, 120, 90) if x_ >= 0 else (200, 40, 55)), font=f12)
                xx += d.textlength(t_, font=f12)
            y += rh
        wc = (8, 120, 90) if hn["line"].startswith("Buyers") else ((200, 40, 55) if hn["line"].startswith("Sellers") else (100, 100, 100))
        d.text((bx0 + 6, y), l3, fill=wc, font=f12)
        y += rh
        if l4 and l4 != hn["line"]:
            d.text((bx0 + 6, y), l4, fill=(90, 90, 90), font=f12)
    except Exception as e:
        print(f"[Vision] hist box: {e}")

    # ---- time axis (IST) + titles
    for k in range(5):
        i = lo + int((nb - 1) * k / 4.0)
        d.text((max(2, sx(i) - 28), PZ[1] + 8), _ist(f["t"][i] / 1000.0)[-5:], fill=(90, 90, 90), font=f12)
    src = (source or (marks or {}).get("source") or "bot")
    if side:
        sig = f"  |  AI own signal: {_side_word(side)}" if src == "own" else f"  |  bot signal: {_side_word(side)}"
    else:
        sig = ""
    d.text((x0, 10), f"{symbol}   {tf_label}{sig}", fill=(20, 20, 20), font=f18)
    d.text((x0, 34), "Green line EMA30  |  Red line EMA50  |  curved bands = SD 1/2/3 (dark = mean/1SD)" + (f"   {title_extra}" if title_extra else ""), fill=(100, 100, 100), font=f12)
    d.text((x0 + 4, PT[0] + 4), "TSI: grey = value, thick = signal line (4 colours)", fill=(100, 100, 100), font=f12)
    zsma_vals = f.get("zsma") or []
    view_start = max(0, n - VIEW)
    zsma_ok = sum(1 for j in range(view_start, n) if j < len(zsma_vals) and zsma_vals[j] is not None)
    if zsma_ok < (n - view_start):
        znote = f"Z-SMA needs ~400 candles: only {zsma_ok}/{n - view_start} bars in view have it"
        d.text((x0 + 4, PZ[0] + 4), znote, fill=(180, 100, 40), font=f12)
    else:
        d.text((x0 + 4, PZ[0] + 4), "Z-SCORE: green/red area, black line = Z-SMA 200", fill=(100, 100, 100), font=f12)
        d.text((x0 + 4, PZ[0] + 18), "Black Z-SMA 200 = average Z (support from above / resistance from below)", fill=(90, 90, 90), font=f12)
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
    hdr = {"x-api-key": sl["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
    body = {"model": nm, "max_tokens": 900, "temperature": 0.2, "system": system, "messages": [{"role": "user", "content": content}]}
    r = requests.post("https://api.anthropic.com/v1/messages", headers=hdr, json=body, timeout=60)
    if r.status_code == 400 and "temperature" in (r.text or "").lower():
        # Newer models may refuse the temperature setting: send once more without it.
        body.pop("temperature", None)
        r = requests.post("https://api.anthropic.com/v1/messages", headers=hdr, json=body, timeout=60)
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
    own = str(rec.get("source") or "bot") == "own"
    head = ("Your own scanner found this setup (the bot did not signal it). Goal: make profit with as few trades as possible. "
            "Take only a clear, well-placed setup where BOTH indicator families agree; SKIP or WAIT on anything doubtful. "
            "There is no daily loss limit on your own trades, so quality is the only filter. "
            "Your reason MUST name the price level (an SD band, EMA or swing high/low) and the indicator that supports it, for example: 'bounce from -2SD, TSI above its signal'.\n") if own else "A bot signal just fired.\n"
    return (head + f"Symbol: {rec['symbol']}; timeframe {_tf_label(rec['tf_min'])}; signal: {rec['side']} "
            f"(the bot wants to go {_side_word(rec['side'])}); bot entry price {_fmt(rec.get('sig_price'))}; price now {_fmt(price)}.\n"
            f"Numbers read from the same chart: {_lv_text(lv)}.\n"
            f"Indicator read (both families — EMA/SD and TSI/Z): {ind_line}.{ctx}{prev}\n"
            f"{(rec.get('tsi_hist_note') or {}).get('text', '')}\n"
            "You MUST weigh BOTH indicator families (EMA+SD bands AND TSI+Z-score). Do not decide from EMA alone. When the TSI histogram note matters, name it in your reason.\n"
            "If price just pumped and is stretched at the top of the recent range, prefer SKIP or WAIT for BUY.\n"
            "Decide TAKE, SKIP or WAIT. TAKE = open the trade now. WAIT = the idea may work but the entry is not ready (say what you wait for; you will be asked again on the next candles). SKIP = do not trade.\n"
            "For TAKE give a stop (the price where the idea is wrong, beyond a recent swing or band) and a first target (the next level where price may stall). The target is NOT a fixed exit: you will manage the trade later from fresh charts.\n"
            "Answer with JSON only, in simple English:\n"
            '{"decision":"TAKE|SKIP|WAIT","reason":"one short sentence","checklist":{"ema":"","candles":"","sd_zone":"","tsi":"","zscore":"","divergence":"","room":""},"stop":number or null,"target":number or null,"wait_for":"short text or empty"}\n'
            "Each checklist answer: at most 12 words.")


def _review_prompt(tr, lv, price, why, hist_text=""):
    roi = _roi(tr["side"], tr["entry"], price, tr["lev"])
    return (f"You are managing an open virtual {_side_word(tr['side'])} trade.\nSymbol: {tr['symbol']}; timeframe {_tf_label(tr['tf_min'])}; entry {_fmt(tr['entry'])}; "
            f"price now {_fmt(price)}; current stop {_fmt(tr['sl'])}; current target {_fmt(tr.get('target'))}; ROI now {roi:+.1f}% (leverage {tr['lev']:g}x); "
            f"best ROI so far {tr.get('peak_roi', 0):+.1f}%.\nWhy you are asked now: {why}.\n"
            f"Numbers read from the chart: {_lv_text(lv)}.\n"
            + (hist_text + " Use it: a shrinking push against the trade is a reason to exit or trail; say it in your reason.\n" if hist_text else "") +
            "The chart shows the entry, stop and target lines. Decide HOLD, PARTIAL, TRAIL or EXIT. EXIT when momentum fades, a divergence shows, price is stretched at a band, or the structure breaks. "
            "HOLD while the trend is intact. TRAIL = keep the whole trade and move the stop closer to price in the profit direction (put the level in new_stop; never further away). "
            f"PARTIAL = bank part of the trade (fraction 0.25 to 0.75) when price reaches a band or zone where trades often fade; allowed once per trade and only while the trade is in profit (partial already taken: {'yes' if tr.get('partial_done') else 'no'}). "
            "You may also move the target further if price keeps going. There is no fixed take-profit.\n"
            "Answer with JSON only, in simple English:\n"
            '{"action":"HOLD|PARTIAL|TRAIL|EXIT","fraction":number or null,"reason":"one short sentence","new_stop":number or null,"new_target":number or null,"checklist":{"momentum":"","divergence":"","bands":"","ema":""}}\n'
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
    src = rec.get("source") or "bot"
    tid = ("vo" + str(rec["signal_no"])) if src == "own" else ("v" + str(rec["signal_no"]))
    tr = {"id": tid, "dec_id": rec["id"], "symbol": rec["symbol"], "side": rec["side"], "tf_min": rec["tf_min"],
          "entry": price, "sl": stop, "sl0": stop, "target": target, "lev": lev,
          "invest": float(_f(_cfg("invest_amount", 10.0), 10.0)), "fee_roi": float(_f(_cfg("fee_roi_pct", 1.0), 1.0)),
          "opened_at": time.time(), "status": "open", "peak_roi": 0.0, "last_review_bar": cur, "tgt_bar": 0, "notes": [], "bar_ts": rec.get("bar_ts"),
          "source": src, "partial_done": False, "partial_frac": 0.0, "partial_pnl": 0.0}
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
        leg_invest = float(tr.get("invest") or 10)
        leg_pnl = leg_invest * net / 100.0
        part = float(tr.get("partial_pnl") or 0)
        tr.update(status="closed", exit=price, exit_reason=reason, closed_at=time.time(), roi=net,
                  pnl=round(leg_pnl + part, 4))
        _note(tr, f"Closed at {_fmt(price)}: {reason}. Result {tr['pnl']:+.2f} USDT after fees.")
        _mark()
        try:
            from . import ai_vision_exits as XE
            XE.record_closed(tr)
        except Exception:
            pass


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
                                  "source": "bot",
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
        png = render_chart(sym, candles, _tf_label(tf), rec["side"], {"bar_ts": rec["bar_ts"], "source": rec.get("source") or "bot"}, source=rec.get("source") or "bot")
        _f_, _e, lv = _levels(candles)
        rec["tsi_hist_note"] = hist_note(_f_)             # same bars the chart box shows; also goes into the AI prompt and the Results card
        try:                                               # measured tags for the learning notebook (plain arithmetic, no AI)
            from . import ai_vision_lessons as L
            rec["feat"] = L.features(_f_, rec["side"])
        except Exception:
            pass
        try:
            from . import ai_pumpdump as PD
            bs_text, bs_nums = PD.buyer_seller(candles)
            rec["buyer_seller"] = bs_text
            if bs_nums:
                score = bs_nums.get("score", 0)
                feat = rec.get("feat") or {}
                buy = str(rec.get("side") or "").upper() == "BUY"
                if score >= 0.5:
                    feat["flow_with"] = buy  # buyers favor BUY
                elif score <= -0.5:
                    feat["flow_with"] = (not buy)  # sellers favor SELL
                rec["feat"] = feat
            zs = PD.zsma_read(_f_, rec["side"])
            if zs:
                rec["zsma_read"] = zs
            # record pump/dump event opportunistically (15m preferred)
            if int(tf) == 15:
                PD.record_from_candles(sym, candles, 15)
        except Exception as e:
            print(f"[Vision] pumpdump tags: {e}")
        rec["indicator_summary"] = _indicator_summary(lv, rec["side"], rec.get("feat"))
        if rec["tsi_hist_note"].get("vals"):
            rec["indicator_summary"]["histogram"] = rec["tsi_hist_note"]["short"]
        recent_ctx = _recent_context(candles, rec["side"])
        if rec.get("buyer_seller"):
            recent_ctx = (recent_ctx + " " + rec["buyer_seller"]).strip()
        if rec.get("zsma_read"):
            recent_ctx = (recent_ctx + " " + rec["zsma_read"]).strip()
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
            try:
                from . import ai_vision_lessons as L
                L.record_skip(rec)
            except Exception:
                pass
            return _finish(rec, "expired", "SKIP", "Waited several candles; the entry never became ready.")
        rec["status"] = "waiting"
        rec["last_bar"] = _bar_start(time.time(), tf)
    else:
        rec["status"] = "skipped"
        try:
            from . import ai_vision_lessons as L
            L.record_skip(rec)
        except Exception:
            pass
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
        png = render_chart(sym, candles, _tf_label(tf), tr["side"], marks, source=tr.get("source") or "bot")
        _f_, _e, lv = _levels(candles)
        hn = hist_note(_f_)
        tr["tsi_hist_note"] = hn
    except Exception as e:
        tr["last_review_bar"] = _bar_start(time.time(), tf)
        return _log(f"review {sym}: {str(e)[:80]}")
    _count()
    text, err = _call_ai(guide_text(sym, tr["side"]), _review_prompt(tr, lv, price, why, hist_text=hn["text"] if hn.get("vals") else ""), png)
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
            log_trail(tr, "stop", price)
            moved.append(f"stop to {_fmt(ns)}")
        if nt and ((side == "BUY" and nt > price) or (side == "SELL" and nt < price)):
            tr["target"] = nt
            moved.append(f"target to {_fmt(nt)}")
        tr["last_checklist"] = _clean_check(out.get("checklist"))
        act = str(out.get("action", "HOLD")).upper()
        if act == "PARTIAL":
            done = None
            try:
                gross_now = _roi(side, tr["entry"], price, tr["lev"])
                if gross_now - float(tr.get("fee_roi") or 0) > 0:          # only while in profit after fees
                    from . import ai_vision_exits as XE
                    frac = _f(out.get("fraction")) or 0.5
                    done = XE.apply_partial(tr, price, frac)
                    if done is not None:
                        log_trail(tr, "partial", price)
            except Exception:
                done = None
            if done is None:
                act = "HOLD"
                moved.append("partial refused (already taken, bad size, or not in profit)")
            else:
                moved.append(f"banked {int(round(tr.get('partial_frac', 0) * 100))}% at {_fmt(price)} ({done:+.2f} USDT)")
        word = act if act in ("EXIT", "PARTIAL") else ("TRAIL" if (act == "TRAIL" and any(m.startswith("stop") for m in moved)) else "HOLD")
        txt = f"{word}: {_short_txt(out.get('reason'))}" + (f" (moved {', '.join(moved)})" if moved else "")
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
        L.check_skip_hindsight(sys.modules[__name__])
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
        try:
            import sys
            from . import ai_vision_own as OWN
            if OWN.tick(sys.modules[__name__]):
                return True
        except Exception as e:
            _log(f"own-scan: {str(e)[:100]}")
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
def _closed_shown(closed):
    """Last 40 closed BOT trades plus last 40 closed AI OWN trades, kept in time order,
    so the AI Own tab never goes empty when many bot trades close."""
    bot = [t for t in closed if (t.get("source") or "bot") != "own"][-40:]
    own = [t for t in closed if (t.get("source") or "bot") == "own"][-40:]
    keep = {id(t) for t in bot + own}
    return [t for t in closed if id(t) in keep]


def log_trail(tr, kind, price=None):
    """Remember each stop move / banked profit so the live chart can draw the stop-trail and profit points."""
    try:
        tl = tr.setdefault("trail", [])
        tl.append({"t": time.time(), "kind": kind, "sl": tr.get("sl"), "price": price})
        if len(tl) > 40:
            del tl[:-40]
    except Exception:
        pass


def _trade_view(t):
    px = _live_price(t["symbol"]) if t["status"] == "open" else None
    v = {k: t.get(k) for k in ("id", "dec_id", "symbol", "side", "tf_min", "entry", "sl", "sl0", "target", "lev", "invest", "opened_at",
                              "status", "peak_roi", "exit", "exit_reason", "closed_at", "roi", "pnl", "notes", "last_checklist",
                              "source", "partial_done", "partial_frac", "partial_pnl", "tsi_hist_note", "trail")}
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



def _day0_ts(now=None):
    """Same 5:30 AM IST trading-day boundary the app uses for Today P&L.
    Optional now (unix epoch) lets tests plant times."""
    if now is not None:
        from datetime import datetime, timezone, timedelta
        now = float(now)
        ist = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(hours=5, minutes=30)
        reset = ist.replace(hour=5, minute=30, second=0, microsecond=0)
        if ist < reset:
            reset = reset - timedelta(days=1)
        return (reset - timedelta(hours=5, minutes=30)).timestamp()
    try:
        from . import trade_store
        return float(trade_store._trading_day_start_ts())
    except Exception:
        pass
    from datetime import datetime, timezone, timedelta
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    reset = ist.replace(hour=5, minute=30, second=0, microsecond=0)
    if ist < reset:
        reset = reset - timedelta(days=1)
    return (reset - timedelta(hours=5, minutes=30)).timestamp()


def _today_block(trades, decs):
    """Counts for the Live 'what the AI did today' card. Status words are fixed.
    taken + skipped + waiting + queued + not_judged == signals (must add up)."""
    day0 = _day0_ts()
    decs = [d for d in decs if (d.get("source") or "bot") == "bot"]        # the card is about BOT signals; own-scan numbers live in /api/vision/compare
    trades = [t for t in trades if (t.get("source") or "bot") == "bot"]
    today_decs = [d for d in decs if float(d.get("sig_time") or d.get("decided_at") or 0) >= day0]
    # status word per signal
    taken = skipped = waiting = queued = not_judged = 0
    words = []
    for d in today_decs:
        st = str(d.get("status") or "")
        if st == "taken":
            taken += 1
            words.append("TAKEN")
        elif st in ("waiting",):
            waiting += 1
            words.append("WAITING")
        elif st == "queued":
            queued += 1
            words.append("WAITING")  # still in line counts as waiting for the card
        elif st in ("late", "error"):
            # the AI never judged it (busy, no quota, failed) - NOT an AI skip
            not_judged += 1
            words.append("NOT JUDGED")
        else:
            # skipped, expired
            skipped += 1
            words.append("SKIPPED")
    signals = len(today_decs)
    # open / closed AI trades that belong to today (opened today or still open from today)
    today_trades = [t for t in trades if float(t.get("opened_at") or 0) >= day0]
    open_n = sum(1 for t in today_trades if t.get("status") == "open")
    closed_today = [t for t in today_trades if t.get("status") == "closed"]
    closed_n = len(closed_today)
    net = round(sum(float(t.get("pnl") or 0) for t in closed_today), 2)
    exited = stopped = 0
    for t in closed_today:
        reason = str(t.get("exit_reason") or "").lower()
        if "stop" in reason:
            stopped += 1
        else:
            exited += 1
    # integrity: taken+skipped+waiting+queued == signals
    return {
        "day0": day0,
        "signals": signals,
        "taken": taken,
        "skipped": skipped,
        "waiting": waiting,
        "queued": queued,
        "not_judged": not_judged,
        "open": open_n,
        "closed": closed_n,
        "net": net,
        "exited": exited,
        "stopped": stopped,
        "words": {"TAKEN": taken, "SKIPPED": skipped, "WAITING": waiting + queued, "NOT JUDGED": not_judged,
                  "EXITED": exited, "STOPPED": stopped},
    }




def _yesterday_line(trades, decs):
    """Small yesterday net for the Live hero sub-line."""
    try:
        from . import ai_vision_days as VD
        import sys
        row = VD.get_day_summary(sys.modules[__name__], 1)
        return {"net": row.get("net"), "closed": row.get("closed"), "date": row.get("date")}
    except Exception:
        day0 = _day0_ts()
        start, end = day0 - 86400, day0
        closed = [t for t in trades if t.get("status") == "closed"
                  and start <= float(t.get("opened_at") or 0) < end]
        return {"net": round(sum(float(t.get("pnl") or 0) for t in closed), 2), "closed": len(closed), "date": None}



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
                                   "indicator_summary", "recent_context", "feat", "source", "tsi_hist_note")}
        if not x.get("source"):
            x["source"] = "bot"
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
        "open": ov, "closed": [_trade_view(t) for t in reversed(_closed_shown(closed))], "decisions": out_dec, "log": log,
        "indicator_use": _indicator_use(decs),
        "today": _today_block(trades, decs),
        "yesterday": _yesterday_line(trades, decs),
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
        marks.update(entry=tr["entry"], sl=tr["sl"], target=tr.get("target"), exit=tr.get("exit"),
                     trail=tr.get("trail"), sl0=tr.get("sl0"), opened_at=tr.get("opened_at"))
    elif dec and dec.get("stop"):
        marks.update(sl=dec.get("stop"), target=dec.get("target"))
    return render_chart(src["symbol"], candles, _tf_label(src["tf_min"]), src["side"], marks, source=src.get("source") or "bot")


def set_notes(text):
    from . import settings_store
    settings_store.update(vision_notes=str(text or "")[:4000])
    return {"ok": True}

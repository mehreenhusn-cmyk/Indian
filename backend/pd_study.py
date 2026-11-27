"""pd_study.py - Round 4 STUDY: how to USE the indicators (Parts 5 + 6, 28 Nov 2026). Read README_PUMPDUMP.md section 8 first.
STUDY ONLY: it reads its own files and writes its own files. Nothing goes into the bot, no Telegram, no order. Runs once a day after 00:10 IST inside the
existing pd_runner thread (a few candle calls per poll, same call cap and back-off as Round 1), never a new thread.
Two kinds of data:
  A) ROWS  study_rows/<day>.jsonl = every START with the indicator snapshot at that moment + its move (in the alert's direction, %) after 1 h / 4 h / 1 day
           (written by pd_learn.py). Tests 1 TSI above / below 0 (+ signal line + histogram), 2 Z length 50 / 100 / 200 (+ Z vs ZSM), 5 entry timing,
           6 far from EMA 50. Needs days of data: a START gets its row 24 h later.
  B) CANDLES  raw 5m / 15m / 1h candles of the coins with the most STARTs of the last 14 days (study_coins). Tests 3 SD Bands as support / resistance
           (length 50 / 100 / 200 / 300, lines mid, +-1, +-2 SD) and 4 ZSM role (Z above / below ZSM, Z crossing ZSM). Phase of a candle by its move over
           study_phase_bars candles: pump (+study_phase_pct % or more), dump (that much down), else side (sideways).
Every answer is a table with counts (n), never a bare %. A group with too few rows says "abhi data kam hai".
Output: <data>/pumpdump/study/<day>.json (full tables), study/summary.json (verdict lines for the app), GET /api/pd/study."""
import time

import pd_config as C
import pd_store as ST
import pd_tsi
from owl_sniper_engine_a import pstdev, sma, sma_any, zscore

TFS = pd_tsi.TFS
HZ = ("60", "240", "1440")                      # minutes after the START (1 h / 4 h / 1 day)
SD_LENS = (50, 100, 200, 300)
LINES = ((-2, "-2sd"), (-1, "-1sd"), (0, "mid"), (1, "+1sd"), (2, "+2sd"))
CANDLE_TFS = ("5m", "15m", "1h")
SIDES = ("pump", "dump")
PHASE_WORD = {"pump": "pump me", "side": "sideways me", "dump": "dump me"}


def _r(x, n=2):
    return None if x is None else round(x, n)


def _gt(a, b):
    return None if a is None or b is None else bool(a > b)


def _ab(v):
    return None if v is None else ("above" if v else "below")


# ------------------------------------------------------------------ A) snapshot + rows
def compact(tfd):
    """Cached indicator numbers of a coin (pd_tsi.Klines.tf_data) -> the small snapshot saved with a START:
    {tf: {t0 TSI above 0, sg TSI above its signal, hg histogram above 0, hu histogram rising, z50 / z100 / z200, zsm, e30 / e50 = % from EMA 30 / 50}}."""
    out = {}
    for tf, d in (tfd or {}).items():
        if d:
            out[tf] = {"t0": d.get("tsi_above_zero"), "sg": _gt(d.get("tsi"), d.get("tsi_signal")), "hg": _gt(d.get("hist"), 0), "hu": _gt(d.get("hist_change"), 0),
                       "z50": _r(d.get("z50")), "z100": _r(d.get("z100")), "z200": _r(d.get("z200")), "zsm": _r(d.get("zsm")),
                       "e30": _r(d.get("ema30_dist")), "e50": _r(d.get("ema50_dist"))}
    return out


def load_rows(now):
    rows, t = [], now
    for _ in range(int(C.get("study_days"))):
        rows.extend(ST.read_day("study_rows", C.day_of(t)))
        t -= 86400
    return rows


def _cell(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "went": 0, "rate": None, "avg": None}
    w = sum(1 for v in vals if v > 0)
    return {"n": n, "went": w, "rate": round(w / n, 2), "avg": round(sum(vals) / n, 2)}


def group(rows, tf, side, hz, fn):
    """Moves (alert direction, %) of the rows of one side, grouped by fn(snapshot of that time frame, +1 pump / -1 dump) -> {key: cell}."""
    sgn = 1.0 if side == "pump" else -1.0
    g = {}
    for r in rows:
        f, m = (r.get("feat") or {}).get(tf), r.get("m" + hz)
        if r["side"] != side or f is None or m is None:
            continue
        k = fn(f, sgn)
        if k is not None:
            g.setdefault(k, []).append(m)
    return {k: _cell(v) for k, v in g.items()}


def tables(rows, fns, tfs=TFS):
    """{name: {tf: {side: {hz: {key: cell}}}}}, empty groups left out."""
    out = {}
    for name, fn in fns.items():
        for tf in tfs:
            for side in SIDES:
                for hz in HZ:
                    g = group(rows, tf, side, hz, fn)
                    if g:
                        out.setdefault(name, {}).setdefault(tf, {}).setdefault(side, {})[hz] = g
    return out


def _hist(f, s):
    if f.get("hg") is None or f.get("hu") is None:
        return None
    return ("plus" if f["hg"] else "minus") + ("_up" if f["hu"] else "_down")


def _zb(v, s):
    """Z in the alert's direction: far = 2 SD or more already, mid = 0 to 2 SD, against = the other side."""
    if v is None:
        return None
    a = v * s
    return "far" if a >= 2 else ("mid" if a >= 0 else "against")


def _far(f, s):
    e = f.get("e50")
    if e is None:
        return None
    a = e * s                                       # distance from EMA 50 in the alert's direction, %
    return "lt1" if a < 1 else ("1to3" if a < 3 else ("3to6" if a < 6 else "gt6"))


def _combo(f, s):
    z, h, t = _zb(f.get("z200"), s), _hist(f, s), _ab(f.get("t0"))
    return None if z is None or h is None or t is None else "tsi_%s|hist_%s|z_%s" % (t, h, z)


TSI_FNS = {"zero": lambda f, s: _ab(f.get("t0")), "signal": lambda f, s: _ab(f.get("sg")), "hist": _hist}
Z_FNS = {"z50": lambda f, s: _zb(f.get("z50"), s), "z100": lambda f, s: _zb(f.get("z100"), s), "z200": lambda f, s: _zb(f.get("z200"), s),
         "zsm": lambda f, s: _ab(_gt(f.get("z200"), f.get("zsm")))}


def best_z(tab):
    """Per time frame + side at 4 h: the Z length whose buckets (far / mid / against) separate the outcomes most. Only buckets with study_cell_min+ rows count."""
    out, mc = [], C.get("study_cell_min")
    for tf in TFS:
        for side in SIDES:
            cand = []
            for n in ("z50", "z100", "z200"):
                g = ((((tab.get(n) or {}).get(tf) or {}).get(side) or {}).get("240")) or {}
                cs = [c for c in g.values() if c["n"] >= mc]
                if len(cs) >= 2:
                    cand.append((max(c["rate"] for c in cs) - min(c["rate"] for c in cs), n, sum(c["n"] for c in cs)))
            if cand:
                sp, n, tot = max(cand)
                out.append({"tf": tf, "side": side, "best": n, "spread": round(sp, 2), "n": tot})
    return out


def timing_top(tab):
    """Entry timing: per tf (5m / 15m / 1h) + side, the 3 TSI + histogram + Z states whose 4 h result was best, with n and the fake share at 1 h."""
    out, mc = [], C.get("study_cell_min")
    for tf in ("5m", "15m", "1h"):
        for side in SIDES:
            t = (((tab.get("combo") or {}).get(tf) or {}).get(side)) or {}
            g4, g1 = t.get("240") or {}, t.get("60") or {}
            rows = [(c["rate"], k, c) for k, c in g4.items() if c["n"] >= mc]
            for rate, k, c in sorted(rows, reverse=True)[:3]:
                a = g1.get(k)
                out.append({"tf": tf, "side": side, "state": k, "n": c["n"], "rate240": rate, "avg240": c["avg"], "fake60": round(1 - a["rate"], 2) if a and a["rate"] is not None else None})
    return out


def _pair(g, ka, kb, la, lb, word="chale"):
    """One plain line comparing two groups, or the 'too little data' line."""
    a, b = (g or {}).get(ka), (g or {}).get(kb)
    if not a or not b:
        return None
    if a["n"] + b["n"] < C.get("study_min_n") or min(a["n"], b["n"]) < C.get("study_cell_min"):
        return "abhi data kam hai (%d alert)" % (a["n"] + b["n"])
    return "%s: %d me %d %s; %s: %d me %d" % (la, a["n"], a["went"], word, lb, b["n"], b["went"])


def _g4(tab, name, tf, side):
    return ((((tab.get(name) or {}).get(tf) or {}).get(side) or {}).get("240")) or {}


def verdicts_rows(tsi, z, zbest, tim, far):
    v = []
    for q, name, tab, ka, kb, la, lb in (("tsi_zero", "zero", tsi, "above", "below", "TSI 0 ke upar", "neeche"), ("tsi_signal", "signal", tsi, "above", "below", "TSI signal ke upar", "neeche"),
                                          ("z_zsm", "zsm", z, "above", "below", "Z, ZSM ke upar", "neeche"), ("far_ema", "far", far, "lt1", "gt6", "EMA50 ke paas (1% se kam)", "bahut door (6%+)")):
        for tf in TFS:
            for side in SIDES:
                t = _pair(_g4(tab, name, tf, side), ka, kb, la, lb)
                if t:
                    v.append({"q": q, "tf": tf, "side": side, "text": t})
    for b in zbest:
        v.append({"q": "z_len", "tf": b["tf"], "side": b["side"], "text": "Z %s sabse saaf (farak %d%%, %d alert)" % (b["best"][1:], round(b["spread"] * 100), b["n"])})
    for b in tim:
        v.append({"q": "timing", "tf": b["tf"], "side": b["side"], "text": "%s: %d me %d%% chale, 1h me fake %s" % (b["state"], b["n"], round(b["rate240"] * 100), ("%d%%" % round(b["fake60"] * 100)) if b["fake60"] is not None else "?")})
    return v


# ------------------------------------------------------------------ B) candles
def _phase(c, i):
    k = int(C.get("study_phase_bars"))
    if i < k:
        return None
    r = (c[i] / c[i - k] - 1.0) * 100.0
    lim = C.get("study_phase_pct")
    return "pump" if r >= lim else ("dump" if r <= -lim else "side")


def _after(h, l, c, i, lv, s, from_above, nb, kb, bar):
    """After a touch of the line: 'b' bounced (moved bar x SD away on the side it came from), 'k' broke (kb closes in a row beyond the line), 'n' neither."""
    run = 0
    for j in range(i + 1, i + nb + 1):
        if from_above:
            if h[j] >= lv + bar * s:
                return "b"
            run = run + 1 if c[j] < lv else 0
        else:
            if l[j] <= lv - bar * s:
                return "b"
            run = run + 1 if c[j] > lv else 0
        if run >= kb:
            return "k"
    return "n"


def sd_scan(h, l, c, tf, acc):
    """Touches of the SD band lines (new touch = the candle range crosses the line and the one before did not). acc['len|line|tf|phase'] = [touches, bounced, broke]."""
    n = len(c)
    nb, kb, bar = int(C.get("study_bounce_bars")), int(C.get("study_break_bars")), C.get("study_bounce")
    for L in SD_LENS:
        mean, sd = sma(c, L), pstdev(c, L)
        for k, name in LINES:
            prev = False
            for i in range(max(L, 1), n - nb):
                m, s = mean[i], sd[i]
                if m is None or not s:
                    prev = False
                    continue
                lv = m + k * s
                hit = l[i] <= lv <= h[i]
                if hit and not prev:
                    ph = _phase(c, i)
                    if ph:
                        res = _after(h, l, c, i, lv, s, c[i - 1] > lv, nb, kb, bar)
                        a = acc.setdefault("%d|%s|%s|%s" % (L, name, tf, ph), [0, 0, 0])
                        a[0] += 1
                        a[1] += res == "b"
                        a[2] += res == "k"
                prev = hit


def zsm_scan(c, tf, acc):
    """Z (length 200) above / below ZSM (SMA 200 of Z) and the crossings, with the move over the next study_fwd_bars candles. acc['tf|phase|label'] = [n, up, sum %]."""
    z = zscore(c, 200)
    zs = sma_any(z, 200)
    fw = int(C.get("study_fwd_bars"))
    for i in range(1, len(c) - fw):
        if z[i] is None or zs[i] is None or z[i - 1] is None or zs[i - 1] is None:
            continue
        ph = _phase(c, i)
        if not ph:
            continue
        up = z[i] > zs[i]
        labs = ["above" if up else "below"]
        if (z[i - 1] > zs[i - 1]) != up:
            labs.append("cross_up" if up else "cross_down")
        fr = (c[i + fw] / c[i] - 1.0) * 100.0
        for lb in labs:
            a = acc.setdefault("%s|%s|%s" % (tf, ph, lb), [0, 0, 0.0])
            a[0] += 1
            a[1] += fr > 0
            a[2] += fr


def sd_result(acc, min_n=50):
    tab, rank, pool = {}, {"pump": [], "side": [], "dump": []}, {"pump": [0, 0, 0], "side": [0, 0, 0], "dump": [0, 0, 0]}
    for key, (n, b, k) in acc.items():
        L, line, tf, ph = key.split("|")
        row = {"n": n, "bounce_pct": round(100.0 * b / n), "break_pct": round(100.0 * k / n)}
        tab.setdefault(L, {}).setdefault(tf, {}).setdefault(ph, {})[line] = row
        for i, x in enumerate((n, b, k)):
            pool[ph][i] += x
        if n >= min_n:
            rank[ph].append(dict(row, len=int(L), line=line, tf=tf))
    best = {ph: sorted(v, key=lambda x: -(x["bounce_pct"] - x["break_pct"]))[:3] for ph, v in rank.items()}
    return {"tables": tab, "best": best, "pooled": {ph: {"touches": p[0], "bounce_pct": round(100.0 * p[1] / p[0]) if p[0] else None, "break_pct": round(100.0 * p[2] / p[0]) if p[0] else None} for ph, p in pool.items()}}


def zsm_result(acc):
    tab, pool = {}, {}
    for key, (n, up, sm) in acc.items():
        tf, ph, lb = key.split("|")
        tab.setdefault(tf, {}).setdefault(ph, {})[lb] = {"n": n, "up_pct": round(100.0 * up / n), "avg": round(sm / n, 3)}
        p = pool.setdefault(ph, {}).setdefault(lb, [0, 0, 0.0])
        p[0] += n
        p[1] += up
        p[2] += sm
    return {"tables": tab, "pooled": {ph: {lb: {"n": p[0], "up": p[1], "up_pct": round(100.0 * p[1] / p[0]), "avg": round(p[2] / p[0], 3)} for lb, p in d.items()} for ph, d in pool.items()}}


def verdicts_candles(sd, zsm):
    v, mn = [], C.get("study_min_n")
    for ph in ("pump", "side", "dump"):
        p = sd["pooled"][ph]
        if p["touches"] < mn:
            v.append({"q": "sd_band", "phase": ph, "text": "%s SD bands: abhi data kam hai (%d touch)" % (PHASE_WORD[ph], p["touches"])})
        else:
            v.append({"q": "sd_band", "phase": ph, "text": "%s SD bands: %d touch me %d%% bounce, %d%% toote" % (PHASE_WORD[ph], p["touches"], p["bounce_pct"], p["break_pct"])})
        for b in sd["best"][ph][:1]:
            v.append({"q": "sd_best", "phase": ph, "text": "%s sabse zyada maana: SD %d %s (%s): %d touch, %d%% bounce, %d%% toote" % (PHASE_WORD[ph], b["len"], b["line"], b["tf"], b["n"], b["bounce_pct"], b["break_pct"])})
        d = zsm["pooled"].get(ph) or {}
        for q, ka, kb, la, lb in (("zsm_side", "above", "below", "Z, ZSM ke upar", "neeche"), ("zsm_cross", "cross_up", "cross_down", "Z ne ZSM upar kaata", "neeche kaata")):
            a, b = d.get(ka), d.get(kb)
            if a and b:
                if min(a["n"], b["n"]) < mn:
                    v.append({"q": q, "phase": ph, "text": "%s %s: abhi data kam hai (%d / %d)" % (PHASE_WORD[ph], la, a["n"], b["n"])})
                else:
                    v.append({"q": q, "phase": ph, "text": "%s %s: %d me %d upar gaye; %s: %d me %d" % (PHASE_WORD[ph], la, a["n"], a["up"], lb, b["n"], b["up"])})
    return v


# ------------------------------------------------------------------ the daily job
def build(rows, sd_acc, zsm_acc, meta):
    """Pure function: rows + candle counts -> the full study result (also used by the checks)."""
    tsi, z = tables(rows, TSI_FNS), tables(rows, Z_FNS)
    tim = tables(rows, {"combo": _combo}, ("5m", "15m", "1h"))
    far = tables(rows, {"far": _far}, ("15m", "1h", "4h"))
    zb, tt = best_z(z), timing_top(tim)
    sd, zs = sd_result(sd_acc), zsm_result(zsm_acc)
    res = dict(meta, rows=len(rows), tsi=tsi, z=z, z_best=zb, timing=tim, timing_top=tt, far=far, sd=sd, zsm=zs,
               note="Main-chart Z and lower-indicator Z are the same maths here (price vs SMA / SD of the same length), so ONE Z test covers both. Phase of a candle = its move over the last study_phase_bars candles.")
    res["verdicts"] = verdicts_rows(tsi, z, zb, tt, far) + verdicts_candles(sd, zs)
    return res


class Study:
    def __init__(self, klines):
        self.kl = klines
        self.job = None
        self.errors = 0
        self.last_day = ST.read_json("study/state.json", {}).get("last_day", "")

    def clear(self):
        self.job = None

    def status(self):
        j = self.job
        return {"running": j is not None, "left": len(j["queue"]) if j else 0, "total": j["total"] if j else 0, "last_day": self.last_day, "errors": self.errors}

    def _due(self, now):
        if self.last_day == C.day_of(now):
            return False
        t = time.gmtime(now + C.get("tz_min") * 60)
        return not (t.tm_hour == 0 and t.tm_min < 10)        # wait until 00:10 IST so the day that just ended is complete

    def update(self, now):
        """Called every poll. Idle most of the day; the daily job fetches study_step_max candle sets per call."""
        if self.job is None:
            if not self._due(now):
                return
            rows = load_rows(now)
            cnt = {}
            for r in rows:
                cnt[r["symbol"]] = cnt.get(r["symbol"], 0) + 1
            coins = [s for s, _ in sorted(cnt.items(), key=lambda x: -x[1])][: int(C.get("study_coins"))]
            self.job = {"day": C.day_of(now), "t0": now, "rows": rows, "coins": coins, "got": 0, "sd": {}, "zsm": {},
                        "queue": [(s, tf) for s in coins for tf in CANDLE_TFS], "total": len(coins) * len(CANDLE_TFS)}
        j = self.job
        made = 0
        while j["queue"] and made < int(C.get("study_step_max")) and now - j["t0"] < 6 * 3600:
            if self._fetch(j, j["queue"][0], now) == "wait":
                return
            j["queue"].pop(0)
            made += 1
        if not j["queue"] or now - j["t0"] >= 6 * 3600:
            self._finish(now)

    def _fetch(self, j, item, now):
        """'ok' | 'skip' (this coin failed) | 'wait' (call cap full or Binance back-off: try again next poll). Leaves 10 calls a minute for the live sections."""
        kl, (sym, tf) = self.kl, item
        if now < kl.blocked_until:
            return "wait"
        while kl.calls and kl.calls[0] < now - 60:
            kl.calls.popleft()
        if len(kl.calls) >= C.get("kline_calls_min") - 10:
            return "wait"
        kl.calls.append(now)
        try:
            rows = kl.fetch(sym, tf, int(C.get("study_limit")))
        except pd_tsi.RateLimited as e:
            kl.blocked_until = now + e.wait
            return "wait"
        except Exception:
            self.errors += 1
            return "skip"
        sec = pd_tsi.TF_SEC[tf]
        rows = [r for r in rows if r[0] / 1000.0 + sec <= now + 1]
        if len(rows) >= 400:
            h, l, c = [float(r[2]) for r in rows], [float(r[3]) for r in rows], [float(r[4]) for r in rows]
            sd_scan(h, l, c, tf, j["sd"])
            zsm_scan(c, tf, j["zsm"])
            j["got"] += 1
        return "ok"

    def _finish(self, now):
        j, self.job = self.job, None
        res = build(j["rows"], j["sd"], j["zsm"], {"day": j["day"], "generated": int(now), "coins": j["coins"], "candle_sets": j["got"], "min_n": C.get("study_min_n")})
        ST.write_json("study/%s.json" % j["day"], res)
        ST.write_json("study/summary.json", {k: res[k] for k in ("day", "generated", "rows", "coins", "candle_sets", "min_n", "verdicts")})
        self.last_day = j["day"]
        ST.write_json("study/state.json", {"last_day": self.last_day})
        print("[pd] study done: %d rows, %d candle sets, %d verdict lines" % (res["rows"], j["got"], len(res["verdicts"])))

"""brain_learn.py - Batch 4b-1: the TRADE JOURNEY (data foundation only, observation only).

For every finished taken Dual trade it joins the B4a candle rows (table `obs` of dual_archive.db, opened READ-ONLY) with the final result
(table `trades`) and writes two small facts-only tables into brain_archive.db:
  journey   ONE row per trade: how the trade lived (peak, MFE candle, first sign of weakness, what came after, how much came back)
  call_out  ONE row per Brain call (= per closed candle of the trade): the call letter, the ROI at that moment and what FOLLOWED
            (final result, best and worst ROI later, candles left)
There is NO verdict here: no "STRONG works", no hold / protect advice, no confidence. Those come in B4b-2, on top of these rows.
Nothing in this file opens, closes, changes or rejects a trade, calls an API, or reads a price feed. Pure Python + sqlite3.

LOOK-AHEAD RULE (one sentence): a journey is written AFTER the trade closed, so it may use later rows as the OUTCOME; but everything that
says what the Brain knew AT a candle (call letter, ROI now, markers like the first weak candle) is read from that candle's own row and the
rows before it only. B4b-2 must judge a call only against trades that had already closed before that candle (test_brain_learn.py proves the
marker part: a marker found on the first k rows is identical on the full list).

Versioned and append-safe: LEARN_VERSION is part of the key. A new version adds rows beside the old ones, a row is never changed or removed.
Rows with a layout this code does not know (obs version / key list) are skipped and flagged, never guessed. Missing candles are flagged
(gaps), never filled. ROI numbers are NET (fee in, same as `live` / `net`); MFE and giveback are GROSS (Batch 2 basis, before the fee).
Run by hand: cd backend && python3 brain_learn.py
"""
import json
import time

import trade_archive as TA

try:                                   # only the row layout (names + version) is read from brain_edge, none of its logic
    import brain_edge as _BE
    _KEYS, _OV = tuple(_BE.OBS_KEYS), _BE.OBS_VERSION
except Exception:
    _KEYS, _OV = (), None

LEARN_VERSION = "j1"                   # journey layout / rule version: a change gets a new version, old rows stay
MAX_PER_STEP = 40                      # trades turned into journeys per Brain cycle (keeps the worker light; the rest follows next cycle)
AGAINST = 7                            # ev bits 1 + 2 + 4 = the three events that point AGAINST the trade (see brain_edge.OBS_KEYS)
MFE_EPS = 0.06                         # MFE values are rounded to 0.1: "reached the final MFE" means within this
LATE_LAG = 2                           # a row written more than this many candles late is flagged
_KIND = {"E": 0, "O": 1, "X": 2}
_ST = {"err": "", "last": 0.0, "new": 0}


def _num(x):
    try:
        return None if x is None else float(x)
    except Exception:
        return None


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _decode(rows, keys):
    """rows = [(t, k, n, tag, lag, f_json_or_list, ov, bv)] -> [dict]. A row that cannot be read is dropped and counted in `bad`."""
    out, bad = [], 0
    for t, k, n, tag, lag, f, ov, bv in rows:
        try:
            fl = json.loads(f) if isinstance(f, (str, bytes)) else f
            if k not in _KIND or not isinstance(fl, list) or len(fl) != len(keys):
                raise ValueError("layout")
            d = dict(zip(keys, fl))
            d.update(t=int(t), k=k, n=int(n), tag=tag, lag=int(lag or 0), ov=ov, bv=bv)
            out.append(d)
        except Exception:
            bad += 1
    out.sort(key=lambda d: (d["t"], _KIND[d["k"]]))
    return out, bad


def _markers(os_rows):
    """First signs of change, found by walking the Brain's O rows OLDEST FIRST and looking at each row's OWN numbers only.
    hist = TSI histogram turned against the trade, weak = the Brain's own call letter was W or R, ev = an event against the trade.
    Descriptive only. -> {name: (n, roi, extra) or None}. Reads nothing newer than the row it reports."""
    m = {"hist": None, "weak": None, "ev": None}
    for d in os_rows:
        roi = _num(d.get("roi"))
        if m["hist"] is None and _num(d.get("hist")) is not None and d["hist"] < 0:
            m["hist"] = (d["n"], roi, None)
        if m["weak"] is None and d.get("tag") in ("W", "R"):
            m["weak"] = (d["n"], roi, d["tag"])
        if m["ev"] is None and int(d.get("ev") or 0) & AGAINST:
            m["ev"] = (d["n"], roi, int(d["ev"]) & AGAINST)
        if all(m.values()):
            break
    return m


def journey_of(tr, rows):
    """PURE. tr = {id, t, sym, tf, d, net, mfe, giveback, bv} from the trades table (the result of record); rows = decoded obs rows (see _decode)
    for that trade. -> (journey dict in TA.JCOLS names, [call dicts in TA.OCOLS names]). Never raises on odd data: it flags it."""
    flags = []
    E = next((d for d in rows if d["k"] == "E"), None)
    Os = [d for d in rows if d["k"] == "O" and _num(d.get("roi")) is not None]
    Xs = [d for d in rows if d["k"] == "X" and _num(d.get("roi")) is not None]
    X = Xs[-1] if Xs else None
    if not rows:
        flags.append("no_obs")
    else:
        if E is None:
            flags.append("no_entry")
        if X is None:
            flags.append("no_exit")
        if Os:
            gaps = (Os[-1]["n"] - Os[0]["n"] + 1) - len(Os)
            if X is not None:
                gaps += max(0, X["n"] - Os[-1]["n"] - 1)
            if gaps > 0:
                flags.append("gaps:%d" % gaps)
            if Os[0]["n"] > 1:
                flags.append("late:%d" % (Os[0]["n"] - 1))
        lag = max([d["lag"] for d in Os + ([X] if X else [])] or [0])
        if lag > LATE_LAG:
            flags.append("lag:%d" % lag)
    net = _num(tr.get("net"))
    if net is None and X is not None:
        net = _num(X["roi"])
    if X is not None and _num(tr.get("net")) is not None and abs(_num(X["roi"]) - _num(tr["net"])) > 0.15:
        flags.append("net_diff")
    mfe = _num(tr.get("mfe"))
    gb = _num(tr.get("giveback"))
    if mfe is None and X is not None:
        mfe = _num(X.get("mfe"))
    if gb is None and X is not None:
        gb = _num(X.get("gb"))
    curve = Os + ([X] if X is not None else [])
    peak = max(curve, key=lambda d: (d["roi"], -d["n"])) if curve else None          # best closed-candle ROI (the first one if tied)
    mfe_n = None
    if X is not None and mfe is not None and mfe > 0:
        xm = _num(X.get("mfe"))
        xm = mfe if xm is None else xm
        for d in curve:
            if _num(d.get("mfe")) is not None and d["mfe"] >= xm - MFE_EPS:
                ma = d.get("ma")
                mfe_n = d["n"] - int(ma) if ma is not None else d["n"]           # the candle where the best price was made
                break
    mk = _markers(Os)
    firsts = [mk[k] for k in ("hist", "weak", "ev") if mk[k] is not None]
    mom = min(firsts, key=lambda x: x[0]) if firsts else None
    j = {"id": tr["id"], "v": LEARN_VERSION, "t": tr.get("t"), "sym": tr.get("sym"), "tf": tr.get("tf"), "d": tr.get("d"),
         "ov": rows[0]["ov"] if rows else None, "bv": (rows[0].get("bv") if rows else None) or tr.get("bv"),
         "flags": ",".join(flags) if flags else "full", "n_rows": len(Os),
         "first_n": Os[0]["n"] if Os else None, "exit_n": X["n"] if X is not None else None, "exit_why": X.get("tag") if X is not None else None,
         "net": _r(net, 2), "mfe": _r(mfe, 1), "gb": _r(gb, 1), "mfe_n": mfe_n,
         "peak_n": peak["n"] if peak else None, "peak_roi": _r(peak["roi"], 1) if peak else None,
         "gb_peak": _r(max(0.0, peak["roi"] - net), 1) if peak and net is not None else None,
         "hist_n": mk["hist"][0] if mk["hist"] else None, "hist_roi": _r(mk["hist"][1], 1) if mk["hist"] else None,
         "weak_n": mk["weak"][0] if mk["weak"] else None, "weak_roi": _r(mk["weak"][1], 1) if mk["weak"] else None,
         "weak_st": mk["weak"][2] if mk["weak"] else None,
         "ev_n": mk["ev"][0] if mk["ev"] else None, "ev_roi": _r(mk["ev"][1], 1) if mk["ev"] else None,
         "mom_n": mom[0] if mom else None, "mom_roi": _r(mom[1], 1) if mom else None, "saved": None}
    outs = []
    if X is not None and net is not None:
        for q, d in enumerate(Os):                                 # one call per closed candle; `later` is OUTCOME only
            later = [x["roi"] for x in curve[q + 1:]]
            if not later or d.get("tag") is None:
                continue
            outs.append({"id": tr["id"], "t": d["t"], "v": LEARN_VERSION, "n": d["n"], "st": d["tag"], "roi": _r(d["roi"], 1), "fin": _r(net, 2),
                         "max_after": _r(max(later), 1), "min_after": _r(min(later), 1), "bars_left": X["n"] - d["n"],
                         "sc": d.get("sc")})
    return j, outs


def _cols(con, table):
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
    except Exception:
        return set()


def step(base=None, limit=MAX_PER_STEP):
    """One Brain cycle: turn up to `limit` finished taken Dual trades that have no journey yet into journeys. Reads dual_archive.db read-only,
    writes brain_archive.db. Idempotent (a trade already done is skipped). Never raises. -> {"new": n, "err": text}."""
    out = {"new": 0, "err": ""}
    try:                                                         # B4d-2: shadow observation of open trades; its own try/except, never touches journeys or the return value
        import brain_shadow as _SH
        _SH.step(base)
    except Exception:
        pass
    try:
        con = TA.open_dual_ro(base)
        if con is None:
            return out
        try:
            have = _cols(con, "trades")
            done = TA.learn_done_ids(LEARN_VERSION, base)
            sel = "SELECT id, t, sym, tf, side, net, %s, %s, %s FROM trades WHERE status = 'closed' ORDER BY t" % (
                "mfe" if "mfe" in have else "NULL", "giveback" if "giveback" in have else "NULL", "brain_version" if "brain_version" in have else "NULL")
            todo = [r for r in con.execute(sel) if r[0] not in done][:max(1, int(limit))]
            if not todo:
                _ST["err"] = ""
                return out
            has_obs = bool(_cols(con, "obs"))
            lay = {}
            js, os_ = [], []
            for tid, t, sym, tf, side, net, mfe, gb, bv in todo:
                rows = []
                if has_obs:
                    rows = con.execute("SELECT t, k, n, tag, lag, f, v, bv FROM obs WHERE id = ?", (tid,)).fetchall()
                known, other = [], 0
                for r in rows:
                    ov = r[6]
                    if ov not in lay:
                        m = con.execute("SELECT v FROM meta WHERE k = ?", ("obs_keys_%s" % ov,)).fetchone()
                        try:
                            lay[ov] = tuple(json.loads(m[0])) if m else (_KEYS if ov == _OV else None)
                        except Exception:
                            lay[ov] = None
                    if lay[ov] and set(lay[ov]) >= {"roi", "mfe", "gb", "ma", "hist", "ev", "sc"}:
                        known.append((r, lay[ov]))
                    else:
                        other += 1
                dec, bad = [], 0
                for ov in {k[0][6] for k in known}:
                    part, b = _decode([k[0] for k in known if k[0][6] == ov], lay[ov])
                    dec += part
                    bad += b
                j, outs = journey_of({"id": tid, "t": t, "sym": sym, "tf": tf, "d": side, "net": net, "mfe": mfe, "giveback": gb, "bv": bv}, dec)
                extra = (["layout:%d" % other] if other else []) + (["bad_rows:%d" % bad] if bad else [])
                if extra:
                    j["flags"] = ",".join(([] if j["flags"] == "full" else [j["flags"]]) + extra)
                j["saved"] = time.time()
                js.append(tuple(j[c] for c in TA.JCOLS))
                os_ += [tuple(o[c] for c in TA.OCOLS) for o in outs]
        finally:
            con.close()
        if not TA.save_learn(js, os_, base):                    # nothing is marked done when the save failed: the same trades come back next cycle
            out["err"] = (TA._L.get("arch_err") or "save failed")
        else:
            out["new"] = len(js)
        _ST.update(err=out["err"], last=time.time(), new=out["new"])
    except Exception as e:
        out["err"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        _ST["err"] = out["err"]
        print("brain_learn: skipped: %s" % out["err"], flush=True)
    return out


def view_summary(base=None):
    """Small plain block for the Brain view JSON: the collected facts (B4b-1) and, in `stats`, what brain_stats measured (B4b-2b: per state, per
    BUY/SELL x timeframe x regime slice, and the mistakes ledger). Measurement only, nothing is decided. Never raises."""
    c = TA.learn_counts(LEARN_VERSION, base)
    st, status = None, "collecting"
    text = ("Journeys collected: %d (%d complete). No learning result yet: NOT ENOUGH DATA. This part only collects facts, nothing is decided."
            % (c["journeys"], c["full"]))
    try:
        import brain_stats as _BS
        st = _BS.summary(base)
        if st.get("status") == "measuring":
            status = "measuring"
            text = ("Journeys collected: %d (%d complete). Measuring outcomes after each Brain state; only results with %d trades or more are shown. "
                    "Observation only: nothing here controls a trade." % (c["journeys"], c["full"], st["min_n"]))
    except Exception as e:
        st = {"status": "error", "err": "%s: %s" % (type(e).__name__, str(e)[:80])}
    try:                                                         # B4c-2: look-alike learning + mistake risk; a failure here only sets look.status = error
        import brain_pattern as _BP
        lk = _BP.summary(base)
    except Exception as e:
        lk = {"status": "error", "err": "%s: %s" % (type(e).__name__, str(e)[:80]), "text": "NOT ENOUGH DATA", "provisional": True}
    try:                                                         # B4d-4: shadow check (key learn.shadow); a failure here only sets shadow.status = error
        import brain_shadow as _SH
        sh = _SH.summary(base)
    except Exception as e:
        sh = {"status": "error", "err": "%s: %s" % (type(e).__name__, str(e)[:80]), "text": "NOT ENOUGH DATA", "provisional": True}
    return {"version": LEARN_VERSION, "status": status, "journeys": c["journeys"], "full": c["full"], "outcomes": c["outcomes"],
            "err": _ST["err"] or c["err"], "text": text, "stats": st, "look": lk, "shadow": sh}


if __name__ == "__main__":
    print(json.dumps({"step": step(), "view": view_summary()}, indent=1))

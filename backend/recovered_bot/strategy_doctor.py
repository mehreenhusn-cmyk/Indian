"""
strategy_doctor.py - "Strategy Doctor": which entries of the EMA50 strategy lose, and which win.

READ-ONLY. It reads closed Bot 1 trades (fee already taken off, via trade_store.get_all_closed(net=True)) and
the after-exit records (ai_post_exit). It never changes the bot, the strategy or any setting. Every rule it
finds is only a SUGGESTION shown on screen.

How a rule is judged (no invented thresholds):
  * Continuous tags (ADX, EMA distance, ATR, SD width, volume, slope, choppiness) are cut into Low / Mid / High
    by the terciles of YOUR OWN trades; the real numbers are shown next to each label.
  * A group is a candidate "avoid" rule when it did worse than all the other trades. It is found on the OLDER 70%
    of trades and then re-checked on the NEWER 30% it has never seen:
        confirmed = still worse than the rest on the new 30%
        not_sure  = it stopped working on the new 30%
        waiting   = fewer than MIN_TEST such trades in the new 30% (not enough to judge)
  * Many groups are tested, so a few will look good by luck. Only "confirmed" ones are shown as suggestions and
    the screen says so. Too few trades -> "not enough data", never a made-up pattern.
  * "Rule would have saved" numbers are ROI points (leveraged, fee already inside) and USDT.

Pure Python (no pandas / numpy). build() never raises.
"""
import math
import time

MIN_SAMPLE = 30      # below this the screen says "not enough data"
Z_TRAIN = 2.0        # how many standard errors worse/better than the rest a group must be (older 70%)
Z_TEST = 1.64        # ... and again on the newest 30% (about 95% one-sided)
MIN_TRAIN = 15       # trades a group needs in the older 70% to become a candidate
MIN_TEST = 5         # trades a group needs in the newer 30% to be judged
TRAIN_FRAC = 0.70

ZONES = ["<-3sd", "-3sd..-2sd", "-2sd..-1sd", "-1sd..mean", "mean..+1sd", "+1sd..+2sd", "+2sd..+3sd", ">+3sd"]
_ZONE_IDX = {z: i for i, z in enumerate(ZONES)}
_LEARN_TAGS = ("clean", "unknown")

_TITLES = {
    "adx": "ADX (trend strength)",
    "gap": "Distance from EMA50 (in ATRs)",
    "htf": "Higher-timeframe trend",
    "chop": "Choppiness (EMA50 crosses in last 20 candles)",
    "atr": "ATR % (candle size)",
    "sdw": "SD width %",
    "vol": "Volume vs average",
    "slope": "EMA50 slope (+ = with the trade)",
    "turn": "EMA50 shape",
    "tf": "Timeframe",
    "side": "Side",
    "zone": "SD position at entry",
    "und": "Index",
    "otype": "Option type",
    "sdr_mean": "SD rule: buy-side below mean / sell-side above mean",
    "sdr_edge": "SD rule: buy-side below -1SD / sell-side above +1SD",
}


def _num(v):
    try:
        if v is None or v == "" or str(v).lower() in ("none", "nan"):
            return None
        x = float(v)
        return x if math.isfinite(x) else None      # inf / -inf used to travel into the report and break the JSON reply
    except Exception:
        return None


def _finite(o):
    """Safety net: replace any inf / NaN anywhere in the report by None. FastAPI refuses to send a reply that holds even
    one such number (HTTP 500), and the app then shows 'Loading' for ever."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


def _stat(rows):
    n = len(rows)
    if not n:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "sum": 0.0, "usdt": 0.0}
    wins = sum(1 for r in rows if r["pnl"] > 0)
    s = sum(r["roi"] for r in rows)
    return {"n": n, "wr": round(wins / n * 100.0, 1), "avg": round(s / n, 2), "sum": round(s, 2),
            "usdt": round(sum(r["pnl"] for r in rows), 2)}


def _z(group, rest, kind):
    """Standard-error distance between a group's average ROI and the rest's. Positive = group is worse
    (kind 'avoid') / better (kind 'take') than the rest. 0 when it cannot be computed."""
    try:
        if len(group) < 2 or len(rest) < 2:
            return 0.0
        g = [r["roi"] for r in group]
        o = [r["roi"] for r in rest]
        mg, mo = sum(g) / len(g), sum(o) / len(o)
        vg = sum((x - mg) ** 2 for x in g) / (len(g) - 1)
        vo = sum((x - mo) ** 2 for x in o) / (len(o) - 1)
        se = (vg / len(g) + vo / len(o)) ** 0.5
        if se <= 0:
            return 0.0
        d = (mo - mg) if kind == "avoid" else (mg - mo)
        return round(d / se, 2)
    except Exception:
        return 0.0


def _terciles(vals):
    v = sorted(x for x in vals if x is not None)
    if len(v) < 9:
        return None
    a, b = v[len(v) // 3], v[(2 * len(v)) // 3]
    return (a, b) if a < b else None


def _fmt(x):
    ax = abs(x)
    if ax >= 100:
        return f"{x:.0f}"
    if ax >= 10:
        return f"{x:.1f}"
    if ax >= 1:
        return f"{x:.2f}"
    return f"{x:.3f}"


def _band(v, cuts):
    if v is None or cuts is None:
        return None
    a, b = cuts
    if v < a:
        return f"Low (below {_fmt(a)})"
    if v >= b:
        return f"High ({_fmt(b)} and above)"
    return f"Mid ({_fmt(a)} to {_fmt(b)})"


def _clean_trades(raw):
    """Usable trades, oldest first. Same quality rule the other AI stats use (clean / unknown only, no manual closes)."""
    out = []
    for t in raw or []:
        try:
            act = str(t.get("action") or "").upper()
            if act not in ("BUY", "SELL"):
                continue
            if (t.get("quality_tag") or "unknown") not in _LEARN_TAGS:
                continue
            if str(t.get("clean_exit_reason") or "") == "MANUAL" or str(t.get("status") or "").endswith("MANUAL"):
                continue
            roi = _num(t.get("roi_pct"))
            pnl = _num(t.get("pnl_usdt"))
            if roi is None or pnl is None:
                continue
            if abs(roi) > 400.0:      # impossible at 10x (a 40% move) = bad price tick; one such trade (+6600 pts) had skewed every average
                continue
            ts = _num(t.get("opened_at_ts")) or _num(t.get("closed_at_ts")) or 0.0
            out.append({"t": t, "act": act, "roi": roi, "pnl": pnl, "ts": ts})
        except Exception:
            continue
    out.sort(key=lambda r: r["ts"])
    return out


def _tag_all(rows, names=None):
    names = names or {"BUY": "BUY", "SELL": "SELL"}
    """Per trade: {feature: label}. Missing data -> feature absent (trade simply not in that group)."""
    cut = {}
    cut["adx"] = _terciles([_num(r["t"].get("adx")) for r in rows])
    cut["gap"] = _terciles([_num(r["t"].get("ema_gap_atr")) for r in rows])
    cut["chop"] = _terciles([_num(r["t"].get("regime_cross_n")) for r in rows])
    cut["atr"] = _terciles([_num(r["t"].get("atr_pct")) for r in rows])
    cut["sdw"] = _terciles([_num(r["t"].get("sd_width_pct")) for r in rows])
    cut["vol"] = _terciles([_num(r["t"].get("volume_ratio")) for r in rows])

    def signed_slope(r):
        s = _num(r["t"].get("ema_slope_pct"))
        return None if s is None else s * (1.0 if r["act"] == "BUY" else -1.0)

    cut["slope"] = _terciles([signed_slope(r) for r in rows])
    for r in rows:
        t, act = r["t"], r["act"]
        tags = {}
        for key, field in (("adx", "adx"), ("gap", "ema_gap_atr"), ("chop", "regime_cross_n"), ("atr", "atr_pct"),
                           ("sdw", "sd_width_pct"), ("vol", "volume_ratio")):
            b = _band(_num(t.get(field)), cut[key])
            if b:
                tags[key] = b
        b = _band(signed_slope(r), cut["slope"])
        if b:
            tags["slope"] = b
        htf = str(t.get("htf_trend") or "")
        if htf in ("up", "down", "flat"):
            if htf == "flat":
                tags["htf"] = "Flat (no clear trend)"
            elif (htf == "up") == (act == "BUY"):
                tags["htf"] = "With the trade"
            else:
                tags["htf"] = "Against the trade"
        turn = str(t.get("ema_turn") or "")
        if turn and turn != "None":
            tags["turn"] = f"{names[act]} when EMA50 is {turn}"
        tf = str(t.get("timeframe") or "")
        if tf and tf != "None":
            tags["tf"] = tf
        tags["side"] = names[act]
        und = str(t.get("underlying") or "")
        if und and und != "None":
            tags["und"] = und
        ot = str(t.get("otype") or "")
        if ot in ("CE", "PE"):
            tags["otype"] = ot
        zone = str(t.get("entry_zone") or "")
        zi = _ZONE_IDX.get(zone)
        if zi is not None:
            tags["zone"] = f"{names[act]} at {zone}"
            if (act == "BUY" and zi < 4) or (act == "SELL" and zi >= 4):
                tags["sdr_mean"] = "Trades the SD rule would block"
            if (act == "BUY" and zi < 3) or (act == "SELL" and zi >= 5):
                tags["sdr_edge"] = "Trades the SD rule would block"
        r["tags"] = tags
        r["zi"] = zi
    return rows


def _groups(rows):
    g = {}
    for i, r in enumerate(rows):
        for f, lab in r.get("tags", {}).items():
            g.setdefault((f, lab), []).append(i)
    return g


def _judge(rows, groups, split, kind):
    """kind 'avoid' (worse than the rest) or 'take' (better than the rest). Returns rule dicts."""
    rules = []
    n = len(rows)
    train_all = set(range(split))
    test_all = set(range(split, n))
    for (feat, lab), idx in groups.items():
        if feat == "side":
            continue
        ix = set(idx)
        tr = sorted(ix & train_all)
        te = sorted(ix & test_all)
        if len(tr) < MIN_TRAIN:
            continue
        rest_tr = sorted(train_all - ix)
        if not rest_tr:
            continue
        s_tr = _stat([rows[i] for i in tr])
        a_tr, a_rest = s_tr["avg"], _stat([rows[i] for i in rest_tr])["avg"]
        if kind == "avoid" and not (a_tr < 0 and a_tr < a_rest):
            continue
        if kind == "take" and not (a_tr > 0 and a_tr > a_rest):
            continue
        z_tr = _z([rows[i] for i in tr], [rows[i] for i in rest_tr], kind)
        if z_tr < Z_TRAIN:
            continue                      # a gap this small is within normal luck
        status, a_te, z_te = "waiting", None, None
        if len(te) >= MIN_TEST:
            rest_te = sorted(test_all - ix)
            a_te = _stat([rows[i] for i in te])["avg"]
            z_te = _z([rows[i] for i in te], [rows[i] for i in rest_te], kind)
            ok = (a_te < 0 if kind == "avoid" else a_te > 0) and z_te >= Z_TEST
            status = "confirmed" if ok else "not_sure"
        full = _stat([rows[i] for i in ix])
        rules.append({
            "kind": kind, "feature": feat, "title": _TITLES.get(feat, feat), "label": lab,
            "n_train": len(tr), "avg_train": s_tr["avg"], "n_test": len(te),
            "avg_test": a_te, "z_train": z_tr, "z_test": z_te, "status": status,
            "n_all": full["n"], "wr_all": full["wr"], "avg_all": full["avg"],
            # what skipping this group would have changed over ALL trades (avoid rules only)
            "saved_roi": round(-full["sum"], 2) if kind == "avoid" else None,
            "saved_usdt": round(-full["usdt"], 2) if kind == "avoid" else None,
            "_idx": ix, "_train_sum": s_tr["sum"],
        })
    order = {"confirmed": 0, "waiting": 1, "not_sure": 2}
    rules.sort(key=lambda x: (order[x["status"]], x["_train_sum"] if kind == "avoid" else -x["_train_sum"]))
    return rules


def _dedupe(rules, keep):
    """Drop rules that cover (almost) the same trades as one already kept."""
    out = []
    for r in rules:
        dup = False
        for k in out:
            inter = len(r["_idx"] & k["_idx"])
            if inter / max(1, min(len(r["_idx"]), len(k["_idx"]))) > 0.8:
                dup = True
                break
        if not dup:
            out.append(r)
        if len(out) >= keep:
            break
    return out


def _clip(rule):
    return {k: v for k, v in rule.items() if not k.startswith("_")}


def _zone_table(rows):
    out = []
    for i, z in enumerate(ZONES):
        b = _stat([r for r in rows if r["zi"] == i and r["act"] == "BUY"])
        s = _stat([r for r in rows if r["zi"] == i and r["act"] == "SELL"])
        out.append({"zone": z, "buy": b, "sell": s})
    return out


def _sd_rules(rows, names=None, unit="USDT"):
    names = names or {"BUY": "BUY", "SELL": "SELL"}
    b_, s_ = names["BUY"], names["SELL"]
    out = []
    for fid, name in (("sdr_mean", f"SKIP: {b_} below the mean line / {s_} above it"),
                      ("sdr_edge", f"SKIP: {b_} below -1SD / {s_} above +1SD")):
        blocked = [r for r in rows if fid in r.get("tags", {})]
        kept = [r for r in rows if fid not in r.get("tags", {}) and r["zi"] is not None]
        b, k = _stat(blocked), _stat(kept)
        if b["n"] < 10:
            verdict = "Not enough trades on the blocked side yet."
        elif b["sum"] < 0:
            verdict = (f"Good rule: the {b['n']} blocked trades lost {abs(b['sum']):.1f} ROI pts "
                       f"({abs(b['usdt']):.2f} {unit}). Skipping them helps.")
        else:
            verdict = (f"Wrong direction: the {b['n']} blocked trades actually made {b['sum']:.1f} ROI pts. "
                       f"Blocking them would hurt.")
        out.append({"id": fid, "label": name, "blocked": b, "kept": k, "verdict": verdict})
    return out


def _loss_story(rows):
    losers = [r for r in rows if r["roi"] < 0]
    winners = [r for r in rows if r["roi"] > 0]
    out = {"losers": len(losers), "winners": len(winners)}
    if not losers:
        return out
    peaks = [(r, _num(r["t"].get("peak_roi_pct"))) for r in losers]
    known = [(r, p) for r, p in peaks if p is not None]
    out["known"] = len(known)
    if known:
        never = [r for r, p in known if p <= 0.05]
        green = [(r, p) for r, p in known if p > 0.05]
        tp1 = [r for r, _ in known if r["t"].get("tp_hit_levels")]
        out["never_green"] = len(never)
        out["green_then_lost"] = len(green)
        out["hit_tp1_then_lost"] = len(tp1)
        out["avg_peak_green_losers"] = round(sum(p for _, p in green) / len(green), 2) if green else 0.0
    caps = []
    for r in winners:
        p = _num(r["t"].get("peak_roi_pct"))
        if p and p > 0:
            caps.append(max(0.0, min(1.0, r["roi"] / p)))
    if len(caps) >= 10:
        out["winner_captured_pct"] = round(sum(caps) / len(caps) * 100.0, 0)
    return out


def _median(v):
    v = sorted(v)
    n = len(v)
    if not n:
        return 0.0
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _post_exit():
    out = {"enough": False, "n_stop": 0, "n_profit": 0, "lines": []}
    try:
        from . import ai_post_exit
        recs = ai_post_exit.read_all(3000)
    except Exception:
        recs = []
    if not recs:
        out["lines"].append("After-exit tracking started - results appear once trades close and are watched for 90 minutes.")
        return out
    stops = [r for r in recs if str(r.get("reason")) == "SL" and r.get("samples", 0) >= 5]
    profit = [r for r in recs if (str(r.get("reason")).startswith("TP") or "SCALP" in str(r.get("reason"))) and r.get("samples", 0) >= 5]
    out["n_stop"], out["n_profit"] = len(stops), len(profit)
    if len(stops) >= 20:
        went = [r for r in stops if (r.get("at60") or 0) > 0]
        out["stop_back_pct"] = round(len(went) / len(stops) * 100.0, 0)
        out["stop_median_best_after"] = round(_median([r["best_after"] for r in stops]), 2)
        out["lines"].append(
            f"After a stop-loss, price was back in your favour 60 min later on {out['stop_back_pct']:.0f}% of {len(stops)} stops "
            f"(median best move {out['stop_median_best_after']:+.1f} ROI pts).")
        out["enough"] = True
    else:
        out["lines"].append(f"Stop-loss exits watched: {len(stops)}/20 - still collecting.")
    if len(profit) >= 20:
        out["profit_median_best_after"] = round(_median([r["best_after"] for r in profit]), 2)
        out["profit_gave_back_pct"] = round(len([r for r in profit if r.get("back_to_entry")]) / len(profit) * 100.0, 0)
        out["lines"].append(
            f"After a TP exit, price kept going a median {out['profit_median_best_after']:+.1f} ROI pts further; "
            f"it fell back to entry on {out['profit_gave_back_pct']:.0f}% of {len(profit)} exits.")
        out["enough"] = True
    else:
        out["lines"].append(f"Profit exits watched: {len(profit)}/20 - still collecting.")
    return out


def _mistake_map(groups, rows):
    order = ["side", "und", "otype", "zone", "adx", "gap", "htf", "chop", "slope", "turn", "atr", "sdw", "vol", "tf"]
    out = []
    for f in order:
        labs = [(lab, idx) for (ff, lab), idx in groups.items() if ff == f]
        if not labs:
            continue
        labs.sort(key=lambda x: x[0])
        buckets = []
        for lab, idx in labs:
            st = _stat([rows[i] for i in idx])
            buckets.append({"label": lab, "n": st["n"], "wr": st["wr"], "avg": st["avg"]})
        out.append({"feature": f, "title": _TITLES.get(f, f), "buckets": buckets})
    return out


def build(limit=5000):
    """Full Strategy Doctor report (dict). Never raises."""
    try:
        from . import trade_store
        raw = trade_store.get_all_closed(limit, net=True)
        rep = build_from(raw)
        try:                                              # read-only extra: hold time / leakage / time of day + AI study headlines
            from . import doctor_verdict
            rep["verdict"] = doctor_verdict.build([x["t"] for x in _clean_trades(raw)], unit="USDT", studies=True)
        except Exception:
            pass
        return _finite(rep)
    except Exception as e:
        return {"ok": False, "sample": 0, "enough": False, "min_sample": MIN_SAMPLE,
                "headline": ["Strategy Doctor could not read the trades yet."], "error": f"{type(e).__name__}: {e}"}


def build_from(raw, unit="USDT", side_names=None, post_exit=True):
    """unit: money label shown on screen ("USDT" crypto / "Rs" India). side_names: how BUY / SELL are written
    (India shows CE / PE). post_exit=False skips the after-exit section (India does not track it yet)."""
    t0 = time.time()
    names = side_names or {"BUY": "BUY", "SELL": "SELL"}
    rows = _tag_all(_clean_trades(raw), names)
    n = len(rows)
    out = {"ok": True, "sample": n, "min_sample": MIN_SAMPLE, "enough": n >= MIN_SAMPLE, "built_at": time.time()}
    if n == 0:
        out["headline"] = ["No closed trades yet. Doctor starts reading after trades close."]
        out["post_exit"] = _post_exit() if post_exit else {"enough": False, "lines": ["Not tracked for this market yet."]}
        out["unit"] = unit
        out["side_names"] = names
        return out

    overall = _stat(rows)
    fee_total = 0.0
    for r in rows:
        t = r["t"]
        f = _num(t.get("fee_usdt"))
        if f is None:
            inv, fr = _num(t.get("invest_usdt")) or 0.0, _num(t.get("fee_roi_pct")) or 0.0
            f = inv * fr / 100.0
        fee_total += f
    out["overall"] = {"n": n, "win_rate": overall["wr"], "avg_roi": overall["avg"],
                      "net_pnl": overall["usdt"], "fee_total": round(fee_total, 2)}
    out["data_ready"] = {
        "total": n,
        "adx": sum(1 for r in rows if "adx" in r["tags"]),
        "gap": sum(1 for r in rows if "gap" in r["tags"]),
        "htf": sum(1 for r in rows if "htf" in r["tags"]),
    }
    out["sd_zones"] = _zone_table(rows)
    out["sd_rules"] = _sd_rules(rows, names, unit)
    out["loss_story"] = _loss_story(rows)
    out["post_exit"] = _post_exit() if post_exit else {"enough": False, "lines": ["Price after exit is not tracked for this market yet."]}
    out["unit"] = unit
    out["side_names"] = names

    groups = _groups(rows)
    out["mistakes"] = _mistake_map(groups, rows)
    split = int(n * TRAIN_FRAC)
    avoid, take = [], []
    if out["enough"] and split >= MIN_TRAIN:
        avoid = _dedupe(_judge(rows, groups, split, "avoid"), 3)
        take = _dedupe(_judge(rows, groups, split, "take"), 3)
    out["avoid"] = [_clip(r) for r in avoid]
    out["take"] = [_clip(r) for r in take]
    out["split"] = {"train": split, "check": n - split}

    # If every CONFIRMED avoid rule had been on: what would the trades have done?
    conf = [r for r in avoid if r["status"] == "confirmed"]
    removed = set()
    for r in conf:
        removed |= r["_idx"]
    kept_rows = [rows[i] for i in range(n) if i not in removed]
    gone = [rows[i] for i in removed]
    out["final"] = {
        "net_pnl": overall["usdt"], "fee_total": round(fee_total, 2),
        "confirmed_rules": len(conf), "trades_avoided": len(gone),
        "with_rules_pnl": round(_stat(kept_rows)["usdt"], 2) if conf else None,
        "delta_usdt": round(-_stat(gone)["usdt"], 2) if conf else None,
        "delta_roi": round(-_stat(gone)["sum"], 2) if conf else None,
    }

    # ---- headline: 3-4 plain lines ----
    h = [f"{n} trades read: win rate {overall['wr']:.0f}%, net {overall['usdt']:+.2f} {unit} after fee."]
    if not out["enough"]:
        h.append(f"Not enough data yet ({n}/{MIN_SAMPLE}). Tables below are only a first look - do not act on them.")
    else:
        sr = out["sd_rules"][0]
        if sr["blocked"]["n"] >= 10:
            h.append("SD rule (" + sr["label"] + "): " + sr["verdict"])
        else:
            h.append("SD rule: not enough trades on the blocked side yet.")
        if conf:
            top = conf[0]
            h.append(f"Biggest confirmed leak: {top['title']} - {top['label']} "
                     f"(would have saved {top['saved_roi']:+.1f} ROI pts, {top['saved_usdt']:+.2f} {unit}; "
                     f"still true on the newest {out['split']['check']} trades).")
        else:
            h.append("No avoid rule is confirmed yet - nothing found so far survived the check on newer trades.")
    ls = out["loss_story"]
    if ls.get("known") and ls["losers"]:
        pct = ls["green_then_lost"] / max(1, ls["known"]) * 100.0
        h.append(f"{pct:.0f}% of losing trades were in profit first (entry was fine, exit/TP was the problem); "
                 f"the other {100 - pct:.0f}% never went green (entry was wrong).")
    out["headline"] = h
    out["notes"] = [
        "Rules are suggestions only. The bot and strategy are not changed.",
        "Every group is tested on the older 70% and re-checked on the newest 30%. Many groups are tested, so treat "
        "'confirmed' as a lead to watch, not a guarantee.",
        "ADX, EMA distance and higher-timeframe trend are saved only for trades after the update; older trades "
        "are simply left out of those groups.",
        f"Numbers are ROI points (% of money put in, fee already inside) and {unit}.",
    ]
    out["took_s"] = round(time.time() - t0, 3)
    return out

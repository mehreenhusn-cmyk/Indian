"""v2_screen_opinion.py - Part 74: SCREENSHOT CHECK, the OPINION block (backend, pure words, no network, no file, no order).
Owner rule 31 Oct: the Brain must also give its OWN reasoned answer, but it is labelled OPINION and kept APART from the evidence block (counts + sample size + label).
This file turns the numbers of v2_screen_check.py into plain words: stance (WAIT / SETUP FORMING UP / SETUP FORMING DOWN / STRETCHED), the reasons it used, two scenarios and a probability line.
The probability line is ONLY the coin's own history count when it has MIN_SAMPLE similar candles; otherwise it says NOT ENOUGH DATA. It never invents a number.
It is a reading of two indicators (EMA50 + SD bands, TSI + Z-score), not a prediction and never an order (Part 76 lets Claude talk about the same numbers; the numbers stay the same).
Every threshold below is a starting value (NV): TSI zone +30 / -30 comes from v2_scalp_ind, SD zone 2 = two standard deviations from the mean."""

LABEL = "OPINION - words from the numbers above, not a prediction, never an order. The EVIDENCE block is the proof, this is only a reading."
STRETCH_SD = 2


def _stance(st):
    """-> (stance, reasons list). Uses only words already in state(): price_vs_ema, tsi_vs_signal, tsi_zone, z_vs_sma, band_zone."""
    pe, tv, tz, zv, bz = st.get("price_vs_ema"), st.get("tsi_vs_signal"), st.get("tsi_zone"), st.get("z_vs_sma"), st.get("band_zone")
    why = ["price is %s the EMA50" % (pe or "?"), "TSI is %s its signal line (zone %s)" % (tv or "?", tz or "?"), "Z-score is %s its Z-SMA" % (zv or "?"), "price sits in SD zone %s" % bz]
    if tz in ("OB", "OS") or (bz is not None and abs(bz) >= STRETCH_SD + 1):
        return "STRETCHED - WAIT", why + ["the move is already far (TSI over-bought / over-sold or 3 SD out): a late entry here is the risky one"]
    up = pe == "ABOVE" and tv == "ABOVE" and zv == "ABOVE"
    down = pe == "BELOW" and tv == "BELOW" and zv == "BELOW"
    if up:
        return "SETUP FORMING UP", why + ["all three agree upward"]
    if down:
        return "SETUP FORMING DOWN", why + ["all three agree downward"]
    return "WAIT - MIXED", why + ["the three do not agree, so there is no clear side"]


def _scenarios(stance, st):
    e = st.get("ema50")
    near = "the EMA50 (%s)" % ("%.6g" % e) if e else "the EMA50"
    if stance == "SETUP FORMING UP":
        return ["Continues: TSI stays above its signal and price holds above %s -> the up picture stays." % near,
                "Fails: price closes back under %s or TSI crosses under its signal -> the picture is gone, wait again." % near]
    if stance == "SETUP FORMING DOWN":
        return ["Continues: TSI stays under its signal and price stays under %s -> the down picture stays." % near,
                "Fails: price closes back over %s or TSI crosses over its signal -> the picture is gone, wait again." % near]
    if stance == "STRETCHED - WAIT":
        return ["Cools off: price comes back toward %s and TSI leaves the extreme zone -> then a clean setup can form." % near,
                "Keeps running: the move goes on without a pause -> nothing in these numbers says where it ends."]
    return ["Turns clear: price, TSI and Z-score start to agree on one side -> a setup forms.",
            "Stays mixed: nothing changes -> there is nothing to read."]


def opinion(rep):
    out = {"label": LABEL, "kind": "OPINION"}
    status = rep.get("status")
    if status == "NO_CANDLES":
        out.update(stance="NO VIEW", reasons=["no saved candles for this coin"], scenarios=[], probability="NOT ENOUGH DATA")
        return out
    if status == "TIME_NOT_COVERED":
        out.update(stance="NO VIEW", reasons=["the saved candles do not reach that time"], scenarios=[], probability="NOT ENOUGH DATA")
        return out
    st = rep.get("state") or {}
    if status != "OK":
        out.update(stance="WAIT - NOT ENOUGH CANDLES", reasons=["only %s candles before this one, all numbers need %s" % (rep.get("candles_in_run_before"), rep.get("candles_needed_for_all_numbers"))],
                   scenarios=[], probability="NOT ENOUGH DATA")
        return out
    stance, why = _stance(st)
    ev = rep.get("evidence") or {}
    if ev.get("pct"):
        p = ev["pct"]
        prob = "In this coin's own saved history, %d similar candles: UP %.1f %%, DOWN %.1f %%, FLAT %.1f %% (close %d candles later). Overlapping windows; a description, not a promise." % (
            ev["similar_candles"], p["UP"], p["DOWN"], p["FLAT"], 12)
    else:
        prob = "NOT ENOUGH DATA: this coin has %s similar candles saved, a percentage needs at least 30." % ev.get("similar_candles", 0)
    out.update(stance=stance, reasons=why, scenarios=_scenarios(stance, st), probability=prob)
    return out

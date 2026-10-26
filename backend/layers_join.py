"""
layers_join.py - JOIN REPORT (version 2). Puts the Price Action layer, the Volume layer and the Smart Brain's clean score side by side
for the SAME finished Dual Bot trades, to answer one question: do the two layers add anything on top of what the Brain already knows?
Report only. It never trades, never skips and writes nothing into Dual Bot. It stays on "collecting" until there are at least
MIN_JUDGED finished trades read by BOTH layers and MIN_DAYS days of data, so no early guess can fool anyone.
"""
import time

import pa_layer as PA

MIN_JUDGED = 100
MIN_DAYS = 10.0
MIN_GROUP = 15
BRAIN_GOOD = 70            # same line as the green dot in the app: clean score 70 or more


def _agree(pa, vol):
    if pa == "against" or vol == "against":
        return "any_against"
    if pa == "supports" and vol == "supports":
        return "both_support"
    if pa == "supports" or vol == "supports":
        return "one_support"
    return "unclear"


def report(trades, pa_log, vol_log, now=None):
    """-> dict for the app. pa_log / vol_log are the two layer logs ({"rows": {id: {...}}, "since": ts})."""
    import dual_lab
    import smart_brain
    now = now or time.time()
    pr, vr = (pa_log or {}).get("rows") or {}, (vol_log or {}).get("rows") or {}
    usdt = lambda t: dual_lab._mg(t) * t["net"] / 100.0
    joined = []
    for t in trades:
        i = t.get("id")
        if t.get("status") != "closed" or t.get("net") is None or not t.get("tg") or not (pr.get(i, {}).get("v") and vr.get(i, {}).get("v")):
            continue
        joined.append({"t": t, "k": _agree(pr[i]["v"], vr[i]["v"]), "good": smart_brain.clean_score(t["tg"]) >= BRAIN_GOOD})
    since = min(float((pa_log or {}).get("since") or now), float((vol_log or {}).get("since") or now))
    days = round((now - since) / 86400.0, 1)
    out = {"judged": len(joined), "need": MIN_JUDGED, "days": days, "need_days": MIN_DAYS, "status": "collecting", "groups": [], "on_brain": [], "text": ""}

    def grp(key, name, items):
        g = PA._agg([(None, x["t"]) for x in items], usdt)
        return dict(g, key=key, name=name)

    names = (("both_support", "Both layers support"), ("one_support", "One supports, none against"),
             ("unclear", "Both unclear"), ("any_against", "At least one layer is against"))
    out["groups"] = [grp(k, nm, [x for x in joined if x["k"] == k]) for k, nm in names]
    good = [x for x in joined if x["good"]]
    out["on_brain"] = [grp("brain_good", "Brain says good (clean %d+), layers ignored" % BRAIN_GOOD, good),
                       grp("brain_good_support", "Brain good AND both layers support", [x for x in good if x["k"] == "both_support"]),
                       grp("brain_good_against", "Brain good BUT a layer is against", [x for x in good if x["k"] == "any_against"])]
    if len(joined) < MIN_JUDGED or days < MIN_DAYS:
        out["text"] = ("Collecting: %d finished trades read by both layers (need %d) and %.1f days of data (need %d)."
                       % (len(joined), MIN_JUDGED, days, int(MIN_DAYS)))
        return out
    out["status"] = "ready"
    s, a = out["on_brain"][1], out["on_brain"][2]
    if s["n"] < MIN_GROUP or a["n"] < MIN_GROUP:
        out["text"] = "%d trades read. Too few Brain-good trades with clear layer opinions yet (need %d in each group)." % (len(joined), MIN_GROUP)
        return out
    edge = round(s["avg"] - a["avg"], 2)
    srt, half, sign = sorted(good, key=lambda x: x["t"]["t"]), len(good) // 2, []
    for part in (srt[:half], srt[half:]):
        ps, pa = [x for x in part if x["k"] == "both_support"], [x for x in part if x["k"] == "any_against"]
        sign.append(None if len(ps) < 5 or len(pa) < 5 else (PA._agg([(None, x["t"]) for x in ps], usdt)["avg"] > PA._agg([(None, x["t"]) for x in pa], usdt)["avg"]))
    steady = sign[0] is not None and sign[0] == sign[1]
    out["edge"], out["steady"], out["adds_value"] = edge, steady, bool(edge > 0 and steady and sign[0])
    if out["adds_value"]:
        out["text"] = ("Among trades the Brain already likes, the ones both layers supported earned %+.2f USDT each against %+.2f when a layer was against "
                       "(difference %+.2f). Same direction in the older and the newer half, so the layers look useful. Next step is your decision." % (s["avg"], a["avg"], edge))
    else:
        out["text"] = ("Among trades the Brain already likes, 'both layers support' earned %+.2f USDT each and 'a layer is against' %+.2f (difference %+.2f). "
                       "%s Not proven that the layers add value. Keep collecting." % (s["avg"], a["avg"], edge, "The two halves disagree." if not steady else "The layers point the wrong way."))
    return out

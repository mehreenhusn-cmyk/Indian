"""Tests for Batch 4d-4 (learn.shadow in brain_learn.view_summary). Run: cd backend && python3 test_brain_shadow3.py"""
import hashlib, json, os, sys, tempfile
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_learn as BL
import brain_pattern as BP
import brain_shadow as SH
import brain_stats as BS
import test_brain_edge as TE
import test_brain_stats as TS
import trade_archive as TA

T0, MS = 1_700_000_000_000, 300000


def row(tid, n, rec):
    return (tid, T0 + n * MS, "r1", "W", 3.0, "5m", 1, rec, None, None, "x", "s1", None, None, 1.0)


def made(recs=("HOLD_OK", "PROTECT_LOOKS_BETTER", "NO_OPINION", "NO_OPINION")):
    base = tempfile.mkdtemp()
    TS._archive(base, [("A", T0, [(1, "T", 2.0), (2, "W", 3.0)], 1.0, "full")])
    assert TA.save_shadow_recs([row("A", i + 1, r) for i, r in enumerate(recs)], base)
    return base


def hashes(base):
    return [hashlib.sha256(open(os.path.join(base, f), "rb").read()).hexdigest() for f in sorted(os.listdir(base)) if f.endswith(".db")]


def test_learn_shadow_is_valid_small_json():
    v = BL.view_summary(made())
    s = json.loads(json.dumps(v["shadow"], allow_nan=False))
    assert set(s) >= {"rule", "status", "min_n", "provisional", "counts", "score", "text", "err"} and s["err"] == "" and s["provisional"] is True
    assert len(json.dumps(s)) < 3000 and "rows" not in s                                            # no raw rows go to the app


def test_summary_counts_hold_protect_and_no_opinion():
    s = SH.summary(made(), force=True)
    assert s["counts"] == {"HOLD_OK": 1, "PROTECT_LOOKS_BETTER": 1, "NO_OPINION": 2}, s
    assert set(s["score"]) == {"HOLD_OK", "PROTECT_LOOKS_BETTER"}                                    # NO_OPINION is counted, never scored


def test_not_enough_data_is_said_plainly():
    s = SH.summary(made(), force=True)
    assert s["status"] == "collecting" and "NOT ENOUGH DATA" in s["text"] and all(r["verdict"] == "NOT ENOUGH DATA" for r in s["score"].values()), s
    e = SH.summary(tempfile.mkdtemp(), force=True)                                                   # no archive at all
    assert e["status"] == "collecting" and e["counts"] == {"HOLD_OK": 0, "PROTECT_LOOKS_BETTER": 0, "NO_OPINION": 0}, e


def test_old_stats_and_look_output_unchanged():
    base = made()
    v = BL.view_summary(base)
    assert v["stats"] == BS.summary(base) and v["look"] == BP.summary(base) and v["version"] == BL.LEARN_VERSION


def test_forced_shadow_failure_does_not_break_the_brain_view():
    base, keep = made(), SH.summary
    SH.summary = lambda *a, **k: 1 / 0
    try:
        v = BL.view_summary(base)
    finally:
        SH.summary = keep
    assert v["shadow"]["status"] == "error" and v["stats"] == BS.summary(base) and v["look"]["status"] != "error", v
    keep = TA.shadow_recs                                                                            # a failure deeper inside: summary itself still answers
    TA.shadow_recs = lambda *a, **k: 1 / 0
    try:
        assert SH.summary(base, force=True)["status"] == "error" and BL.view_summary(base)["stats"] == v["stats"]
    finally:
        TA.shadow_recs = keep


def test_repeated_call_creates_and_changes_nothing():
    base = made()
    BL.view_summary(base)                                                                            # the first call may freeze look_call rows (existing B4c behaviour)
    h, files = hashes(base), sorted(os.listdir(base))
    a = BL.view_summary(base)["shadow"]
    b = SH.summary(base, force=True)
    assert a == b and hashes(base) == h and sorted(os.listdir(base)) == files


def test_trading_golden_output_unchanged():
    TE.test_process_results_identical_with_and_without_the_hook()                                   # same golden sha256 as before Batch 2


def test_source_guard():
    import inspect
    src = inspect.getsource(SH.summary) + inspect.getsource(TA.shadow_counts)
    for bad in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "urllib", "requests", "socket", "anthropic", "smart_brain", "dual_lab", "market_ws"):
        assert bad not in src, bad
    assert "learn.shadow" not in inspect.getsource(BL.step)                                          # the hook only sits in view_summary


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")

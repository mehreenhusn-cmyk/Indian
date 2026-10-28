"""Tests for NEXT-7 (brain_skip.py + key learn.skip in brain_learn.view_summary). Run: cd backend && python3 test_brain_skip.py"""
import hashlib, inspect, json, os, sys, tempfile
os.environ.setdefault("OWL_DATA_DIR", tempfile.mkdtemp())
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "recovered_bot"))
sys.path.insert(0, HERE)
import brain_learn as BL
import brain_skip as SK
import brain_stats as BS
import trade_archive as TA

T0, MS = 1_700_000_000_000, 300000


def trade(i, status, net, tf="5m"):
    return {"id": "x%d" % i, "t": T0 + i * MS, "s": "BTC", "f": tf, "d": 1, "src": "m", "status": status, "net": net, "exit": "bot", "mode": "skip" if status.startswith("skip") else "learned"}


def made(skipped, taken, open_n=0, tf="5m"):
    base = tempfile.mkdtemp()
    tr, k = [], 0
    for x in skipped:
        tr.append(trade(k, "skipped_done", x, tf)); k += 1
    for x in taken:
        tr.append(trade(k, "closed", x, tf)); k += 1
    for _ in range(open_n):
        tr.append(trade(k, "skipped", None, tf)); k += 1
    assert TA.save_dual({"trades": tr}, {}, base)
    return base


def hashes(base):
    return [hashlib.sha256(open(os.path.join(base, f), "rb").read()).hexdigest() for f in sorted(os.listdir(base)) if f.endswith(".db")]


def test_no_archive_is_not_enough_data_and_makes_no_file():
    base = tempfile.mkdtemp()
    s = SK.summary(base, force=True)
    assert s["verdict"] == "NOT ENOUGH DATA" and s["skipped_done"] == 0 and s["status"] == "collecting" and os.listdir(base) == []


def test_under_min_n_is_not_enough_data_with_the_count_in_the_text():
    s = SK.summary(made([-2.0] * 10, [1.0] * 40), force=True)
    assert s["verdict"] == "NOT ENOUGH DATA" and s["skipped_done"] == 10 and "10 of %d" % BS.MIN_N in s["text"] and s["diff"] is None


def test_skipped_clearly_worse_than_taken_is_an_early_hint_that_the_skip_looked_right():
    skipped = [-3.0 + (i % 5) * 0.2 for i in range(40)]
    taken = [0.5 + (i % 7) * 0.4 for i in range(200)]
    c = SK.compare([(i, x) for i, x in enumerate(skipped)], taken)
    assert c["verdict"] in ("EARLY HINT", "SUPPORTED") and c["diff"] < 0 and c["halves"][0] < 0 and c["halves"][1] < 0, c
    s = SK.summary(made(skipped, taken), force=True)
    assert s["status"] == "measuring" and "worse" in s["text"] and s["taken_done"] == 200 and s["unit"].startswith("ROI points")


def test_same_as_taken_is_no_clear_pattern():
    pool = [(-1.0 + (i % 9) * 0.3) for i in range(300)]
    c = SK.compare([(i, x) for i, x in enumerate(pool[:60])], pool[60:])
    assert c["verdict"] == "NO CLEAR PATTERN", c


def test_halves_that_disagree_never_give_a_hint():
    skipped = [-6.0] * 20 + [6.0] * 20
    c = SK.compare([(i, x) for i, x in enumerate(skipped)], [0.5 + (i % 7) * 0.4 for i in range(200)])
    assert c["verdict"] == "NO CLEAR PATTERN", c


def test_open_skipped_and_missing_net_are_counted_not_judged():
    base = made([1.0] * 5, [1.0] * 5, open_n=3)
    s = SK.summary(base, force=True)
    assert s["skipped_open"] == 3 and s["skipped_done"] == 5 and s["taken_done"] == 5


def test_per_timeframe_counts_and_valid_small_json():
    base = made([-1.0] * 4, [1.0] * 6, tf="15m")
    s = json.loads(json.dumps(SK.summary(base, force=True), allow_nan=False))
    assert s["tf"]["15m"]["skipped"] == 4 and s["tf"]["15m"]["taken"] == 6 and len(json.dumps(s)) < 3000 and s["provisional"] is True


def test_reading_never_changes_the_archive():
    base = made([-1.0] * 40, [1.0] * 100)
    before = hashes(base)
    SK.summary(base, force=True)
    assert hashes(base) == before


def test_cache_serves_the_same_answer_until_the_counts_change():
    base = made([-1.0] * 4, [1.0] * 6)
    a = SK.summary(base, force=True)
    assert SK.summary(base) is a


def test_broken_archive_gives_an_error_block_not_an_exception():
    base = tempfile.mkdtemp()
    open(os.path.join(base, TA.DUAL_DB), "wb").write(b"not a database")
    s = SK.summary(base, force=True)
    assert s["status"] == "error" and s["verdict"] == "NOT ENOUGH DATA"


def test_learn_skip_key_is_in_the_brain_view_and_separate_from_the_other_keys():
    v = BL.view_summary(made([-1.0] * 4, [1.0] * 6))
    assert v["skip"]["skipped_done"] == 4 and set(v) >= {"stats", "look", "shadow", "skip"}
    assert "skip" not in json.dumps(v["stats"]).lower().replace("skipped", "")


def test_source_guards_read_only_and_not_connected_to_trading():
    src = inspect.getsource(SK)
    for bad in ("INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "import dual_lab", "import smart_brain", "import settings_store", "import requests", "import urllib", "paper_trader"):
        assert bad not in src, bad
    assert "learn.skip" not in inspect.getsource(BL.step)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn) and fn.__module__ == "__main__":
            fn()
            n += 1
            print("ok", name)
    print("OK", n, "checks")

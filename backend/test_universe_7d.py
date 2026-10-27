"""Tests for universe_7d.py (no network, no real data folder). Run: python test_universe_7d.py"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import universe_7d as U

OK = [0, 0]


def check(name, cond):
    OK[0 if cond else 1] += 1
    print(("PASS " if cond else "FAIL ") + name)


NOW = 1793000000.0                      # a fixed "now"
TODAY = U.day_start_ms(NOW)


def candle(day_back, pct):
    o = 100.0
    return [TODAY - day_back * U.DAY_MS, str(o), "0", "0", str(o * (1 + pct / 100.0))]


def fake_klines(n=30):
    """n coins, 8 completed days + today; coin Ci has change (i - n/2) + day_back so every day has a clear top / bottom."""
    out = {}
    for i in range(n):
        out["C%02dUSDT" % i] = [candle(d, (i - n / 2.0) + d * 0.01) for d in range(0, 9)]
    return out


def threading_count():
    import threading
    return threading.active_count()


def main():
    check("day_start is 00:00 UTC", TODAY % U.DAY_MS == 0 and TODAY <= NOW * 1000 < TODAY + U.DAY_MS)
    g, l = U.top_lists({"A": 5, "B": -3, "C": 1, "D": 9, "E": -8, "F": 2, "G": 0, "H": 4, "I": -1, "J": 3, "K": -6, "L": 7}, 3)
    check("top_lists best / worst first", g == ["D", "L", "A"] and l == ["E", "K", "B"])
    g, l = U.top_lists({"A": 1, "B": 2}, 5)
    check("a coin is never in both lists", not set(g) & set(l))

    kl = fake_klines()
    days = U.build_days(kl, TODAY)
    check("7 completed days, today skipped", len(days) == 7 and U.day_name(TODAY) not in days)
    d1 = days[U.day_name(TODAY - U.DAY_MS)]
    check("5 gainers + 5 losers per day", len(d1["g"]) == 5 and len(d1["l"]) == 5 and d1["g"][0] == "C29USDT" and d1["l"][0] == "C00USDT")
    check("have = skip known days", U.build_days(kl, TODAY, {U.day_name(TODAY - U.DAY_MS): 1}).keys() == days.keys() - {U.day_name(TODAY - U.DAY_MS)})
    check("bad candles ignored", U.build_days({"X": [["bad"], None]}, TODAY) == {})

    ex = U.extra_coins(days, ["C29USDT"], 30, TODAY)
    check("extras skip today's coins", "C29USDT" not in ex and len(ex) == len(set(ex)))
    check("extras cap works", len(U.extra_coins(days, [], 4, TODAY)) == 4 and U.extra_coins(days, [], 0, TODAY) == [])
    check("BTC never an extra", "BTCUSDT" not in U.extra_coins({U.day_name(TODAY - U.DAY_MS): {"g": ["BTCUSDT", "ABCUSDT"], "l": []}}, [], 9, TODAY))
    check("newest day comes first", U.extra_coins({U.day_name(TODAY - 2 * U.DAY_MS): {"g": ["OLDUSDT"], "l": []},
                                                    U.day_name(TODAY - U.DAY_MS): {"g": ["NEWUSDT"], "l": []}}, [], 9, TODAY) == ["NEWUSDT", "OLDUSDT"])

    with tempfile.TemporaryDirectory() as base:
        calls = []

        def fetch(path, params=None):
            calls.append(path)
            if path.endswith("ticker/24hr"):
                return [{"symbol": s} for s in kl] + [{"symbol": "BTCUSDT_250101"}, {"symbol": "ETHBUSD"}]
            return kl[params["symbol"]]

        d = U.refresh(fetch, NOW, base, pause=0)
        check("refresh saves 7 days", len(d) == 7 and os.path.exists(os.path.join(base, "universe_days.json")))
        check("refresh reads each USDT coin once", calls.count("/fapi/v1/klines") == 30)
        n = len(calls)
        U.refresh(fetch, NOW, base, pause=0)
        check("second refresh does no requests", len(calls) == n)
        # next day: only the new day is added, old days stay
        d2 = U.refresh(fetch, NOW + 86400, base, pause=0)
        check("old days are never deleted", set(d) <= set(d2))
        check("cap file is read", U.cap_now(base) == 30)
        U._save("universe_ctl.json", {"cap": 7}, base)
        check("cap changes without a zip", U.cap_now(base) == 7)
        U._S["last"] = 0
        out = U.coins_for_dual(["T1USDT", "T2USDT"], base, NOW)
        check("dual list = today first, then extras (cap 7)", out[:2] == ["T1USDT", "T2USDT"] and len(out) == 9 and len(set(out)) == 9)
        check("status shows days and cap", U.status(base, NOW)["cap"] == 7 and U.status(base, NOW)["saved_days"] >= 7)

    with tempfile.TemporaryDirectory() as base:      # Brain helper: read-only, starts no download
        U._save("universe_days.json", days, base)
        t0 = threading_count()
        w = U.with_extras(["T1USDT"], base, NOW)
        check("with_extras = today + 7-day names", w[0] == "T1USDT" and len(w) == 11 and len(set(w)) == 11)
        check("with_extras starts no thread", threading_count() == t0)
        check("with_extras never raises", U.with_extras(None, base, NOW) != [] or True)

    with tempfile.TemporaryDirectory() as base:
        U._S["last"] = time.time()          # background read blocked: only today's list comes back
        check("no days yet = today's list only", U.coins_for_dual(["A", "B"], base, NOW) == ["A", "B"])
        check("never raises on bad input", U.coins_for_dual(None, base, NOW) == [])

    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe_7d.py"), encoding="utf-8").read().lower()
    check("no delete code in universe_7d.py", "os.remove" not in src and "unlink" not in src and "rmtree" not in src and "drop table" not in src)
    print("\n%d passed, %d failed" % tuple(OK))
    return OK[1]


if __name__ == "__main__":
    sys.exit(1 if main() else 0)

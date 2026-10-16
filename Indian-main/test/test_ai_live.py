"""Stage 2 (AI real account) test on a FAKE Binance. Nothing real is called. Run: python3 test/test_ai_live.py"""
import json
import os
import stat
import sys
import tempfile
import time
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_live_guard as G, ai_live_keys as K, ai_live_executor as E, ai_live_client as CL

E._sleep = lambda s: None


class FakeBinance:
    def __init__(self):
        self.pos, self.stops, self.trades, self.price, self.n = {}, [], [], {"AAAUSDT": 100.0}, 0
        self.dual, self.fail_stop, self.free, self.orders, self.lev = False, False, 1000.0, [], {}

    def __call__(self, method, url, headers, timeout):
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        ok = lambda d: (200, json.dumps(d))
        err = lambda code, msg, st=400: (st, json.dumps({"code": code, "msg": msg}))
        if p == "/fapi/v2/balance":
            return ok([{"asset": "USDT", "availableBalance": str(self.free)}])
        if p == "/fapi/v1/positionSide/dual":
            return ok({"dualSidePosition": self.dual})
        if p == "/fapi/v2/positionRisk":
            rows = [{"symbol": s, "positionAmt": str(v["amt"]), "entryPrice": str(v["entry"]), "markPrice": str(self.price[s])}
                    for s, v in self.pos.items() if not q.get("symbol") or q["symbol"] == s]
            return ok(rows)
        if p == "/fapi/v1/ticker/price":
            return ok({"price": str(self.price[q["symbol"]])})
        if p == "/fapi/v1/marginType":
            return ok({})
        if p == "/fapi/v1/leverage":
            self.lev[q["symbol"]] = int(q["leverage"])
            return ok({"leverage": int(q["leverage"])})
        if p == "/fapi/v1/exchangeInfo":
            return ok({"symbols": [{"symbol": "AAAUSDT", "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.1"}, {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]})
        if p == "/fapi/v1/order" and method == "POST":
            s, side, qty = q["symbol"], q["side"], float(q["quantity"])
            self.orders.append((s, side, qty, q.get("reduceOnly")))
            px = self.price[s]
            sign = 1 if side == "BUY" else -1
            cur = self.pos.get(s)
            if cur and q.get("reduceOnly") == "true":
                pnl = (px - cur["entry"]) * cur["amt"]
                self.trades.append({"symbol": s, "realizedPnl": str(pnl), "commission": "0.02"})
                del self.pos[s]
            else:
                self.pos[s] = {"amt": sign * qty, "entry": px}
                self.trades.append({"symbol": s, "realizedPnl": "0", "commission": "0.02"})
            return ok({"orderId": 1})
        if p == "/fapi/v1/algoOrder" and method == "POST":
            if self.fail_stop:
                return err(-4120, "stop refused")
            self.n += 1
            self.stops.append({"algoId": self.n, "symbol": q["symbol"], "orderType": "STOP_MARKET", "triggerPrice": q["triggerPrice"]})
            return ok({"algoId": self.n})
        if p == "/fapi/v1/algoOrder" and method == "DELETE":
            self.stops = [s for s in self.stops if str(s["algoId"]) != q["algoId"]]
            return ok({})
        if p == "/fapi/v1/openAlgoOrders":
            return ok([s for s in self.stops if s["symbol"] == q["symbol"]])
        if p == "/fapi/v1/openOrders":
            return ok([])
        if p == "/fapi/v1/userTrades":
            return ok([t for t in self.trades if t["symbol"] == q["symbol"]])
        return err(-1, "unknown path " + p, 404)

    def stop_hit(self, sym, px):
        cur = self.pos.pop(sym)
        self.trades.append({"symbol": sym, "realizedPnl": str((px - cur["entry"]) * cur["amt"]), "commission": "0.02"})
        self.stops = [s for s in self.stops if s["symbol"] != sym]


tmp = tempfile.mkdtemp()
ai_dir = os.path.join(tmp, "ai")
G.init(ai_dir); E.init(ai_dir); K.init(ai_dir)
fx = FakeBinance()
E.set_client(CL.Client(creds=lambda: ("k" * 40, "s" * 40), transport=fx))


def trade(bid="b1", side="BUY", sl=95.0, trail=None):
    return {"bot_id": bid, "sym": "AAAUSDT", "side": side, "entry": 100.0, "sl": sl, "trail": trail, "lev": 10, "tps": [1, 2, 3, 4], "hit": 0}


def run(kind, v, reason=""):
    E.submit(kind, v, None, reason)
    while not E._q.empty():
        E._handle(E._q.get_nowait())


# 1) OFF by default: nothing is sent
run("open", trade())
assert not fx.orders and not E._st["open"], "must do nothing while OFF"

# 2) the switch needs every step
assert not G.enable("", True)[0]
assert not G.enable(G.CONFIRM_TEXT, False)[0]
assert not G.enable(G.CONFIRM_TEXT, True)[0]                       # not verified yet
assert E.verify()["ok"]
assert not G.enable(G.CONFIRM_TEXT, True)[0]                       # no margin / cap
G.set_cfg(margin_per_trade=50, daily_loss_cap=30, max_open=2, max_leverage=5)
assert not G.enable("enable real trading", True)[0]                # exact text only
assert G.enable(G.CONFIRM_TEXT, True)[0] and G.is_on()
assert G.set_cfg(max_leverage=500)["max_leverage"] == G.HARD_MAX_LEVERAGE, "hard ceiling"
G.set_cfg(max_leverage=5)

# 3) open: leverage capped at the limit, entry sized from the margin, stop placed
run("open", trade())
assert fx.lev["AAAUSDT"] == 5, "the coach wanted 10x, the limit is 5x"
assert len(fx.orders) == 1 and fx.orders[0][1] == "BUY"
assert abs(fx.pos["AAAUSDT"]["amt"] - 50 * 5 / 100.0) < 0.11
assert len(fx.stops) == 1 and float(fx.stops[0]["triggerPrice"]) == 95.0
rec = E._st["open"]["b1"]

# 4) stop only tightens, new stop placed before the old one is cancelled
rec["pushed"] = 0
run("stop", trade(sl=100.0))
assert len(fx.stops) == 1 and float(fx.stops[0]["triggerPrice"]) == 100.0
rec["pushed"] = 0
run("stop", trade(sl=96.0))
assert float(fx.stops[0]["triggerPrice"]) == 100.0, "a stop is never loosened"

# 5) close: stop cancelled, reduce-only close, real P&L booked after fees
fx.price["AAAUSDT"] = 104.0
run("close", trade(), "TP reached")
assert not fx.pos and not fx.stops and not E._st["open"]
last = E._st["closed"][-1]
assert fx.orders[-1][3] == "true" and last["by"] == "AI close" and last["pnl"] > 0 and last["fee"] > 0, last
assert abs(E._today() - last["pnl"]) < 1e-9

# 6) stop refused -> position closed at once and everything halts
fx.price["AAAUSDT"] = 100.0
fx.fail_stop = True
run("open", trade("b2"))
assert not fx.pos and not E._st["open"] and G.view()["halted"], "no stop = no trade"
fx.fail_stop = False
n_orders = len(fx.orders)
run("open", trade("b3"))
assert len(fx.orders) == n_orders and "b3" not in E._st["open"], "halted: no new real trade"
G.reset_halt()

# 7) the exchange stop hits while the coach has not noticed: reconcile settles it
run("open", trade("b4"))
assert "b4" in E._st["open"]
fx.stop_hit("AAAUSDT", 95.0)
E.reconcile()
assert "b4" not in E._st["open"] and E._st["closed"][-1]["by"] == "exchange stop" and E._st["closed"][-1]["pnl"] < 0

# 8) a lost stop is re-armed by reconcile
run("open", trade("b5"))
fx.stops.clear()
E.reconcile()
assert len(fx.stops) == 1 and "b5" in E._st["open"]
run("close", trade("b5"), "done")

# 9) a position the AI did not open is reported and left alone
fx.pos["AAAUSDT"] = {"amt": 1.0, "entry": 100.0}
E.reconcile()
assert E._st["unknown"] == ["AAAUSDT"] and fx.pos, "unknown positions are never touched"
run("open", trade("b6"))
assert "b6" not in E._st["open"], "no second position on a coin that is already open"
del fx.pos["AAAUSDT"]

# 10) hedge-mode account: refuse and halt
fx.dual = True
run("open", trade("b7"))
assert "b7" not in E._st["open"] and G.view()["halted"]
fx.dual = False
G.reset_halt()

# 11) daily loss cap stops NEW trades (real closed loss so far is about -(5*... ) -> push it over the cap)
E._st["closed"].append({"bot_id": "x", "sym": "ZZZ", "pnl": -100.0, "t1": time.time(), "fee": 0})
run("open", trade("b8"))
assert "b8" not in E._st["open"], "daily loss cap"
E._st["closed"].pop()

# 12) panic closes everything on the AI account and halts
run("open", trade("b9"))
assert fx.pos
r = E.panic("test")
assert r["ok"] and not fx.pos and not fx.stops and G.view()["halted"] and not E._st["open"]

# 13) keys: stored outside the ai folder with owner-only rights, never echoed, bot key refused
assert not K.set_keys("short", "short")["ok"]
good_k, good_s = "A" * 40, "B" * 40
assert K.set_keys(good_k, good_s)["ok"] and K.has_keys() and K.mask() == "...AAAA"
p = os.path.join(tmp, "ai_secrets", "ai_live_keys.json")
assert os.path.isfile(p) and stat.S_IMODE(os.stat(p).st_mode) == 0o600
assert not os.path.exists(os.path.join(ai_dir, "ai_live_keys.json")), "secret must not be in the backed-up folder"
assert "BBBB" not in json.dumps(E.status()), "status never shows the secret"
K.clear()
assert not K.has_keys()

# 14) the state file holds no secret and a restart starts from the saved books
assert "BBBB" not in open(os.path.join(ai_dir, "live_state.json")).read()
print("test_ai_live: all passed")

# 15) after a restart the switch is OFF again (limits are kept, a halt is kept)
G.set_cfg(margin_per_trade=50, daily_loss_cap=30)
G.reset_halt(); G._st["enabled"] = True; G.halt("x"); G._save()
G._st["enabled"], G._st["halted"] = False, ""
G.init(ai_dir)
assert G.view()["enabled"] is False and G.view()["halted"] == "x" and G.cfg()["margin_per_trade"] == 50
print("test_ai_live: restart ok")

# 16) per-coin size cap: the real margin of ONE trade on that coin is lowered, never raised
G.reset_halt(); G._st["enabled"] = True; G.set_cfg(margin_per_trade=50, daily_loss_cap=30, max_open=3, max_leverage=5)
assert G.margin_for("AAAUSDT") == 50
G.set_coin_cap("aaausdt", 20)
assert G.margin_for("AAAUSDT") == 20 and G.view()["coin_caps"] == {"AAAUSDT": 20.0}
G.set_coin_cap("AAAUSDT", 500)
assert G.margin_for("AAAUSDT") == 50, "a cap above the global margin never raises the size"
G.set_coin_cap("AAAUSDT", 20)
try:
    G.set_coin_cap("BTC", 5)
    raise SystemExit("bad coin name must be refused")
except ValueError:
    pass
fx.price["AAAUSDT"] = 100.0
run("open", trade("c1"))
assert abs(fx.pos["AAAUSDT"]["amt"] - 20 * 5 / 100.0) < 0.11 and E._st["open"]["c1"]["margin"] == 20
# 17) slippage: paper entry 100.0, real fill 100.5 on a long = 0.5% worse; a short filled lower is also worse
fx.pos["AAAUSDT"]["entry"] = 100.0
rec = E._st["open"]["c1"]
rec["entry"], rec["slip_pct"] = 100.5, round((100.5 - 100.0) / 100.0 * 100, 4)
run("close", trade("c1"), "done")
assert E._st["closed"][-1]["slip_pct"] == 0.5 and E._st["closed"][-1]["paper_entry"] == 100.0
sv = E.status()["slip"]
assert sv["n"] >= 1 and sv["worst_pct"] >= 0.5
G.set_coin_cap("AAAUSDT", 0)
assert G.view()["coin_caps"] == {} and G.margin_for("AAAUSDT") == 50
G._st["coin_caps"] = {}
print("test_ai_live: coin cap + slippage ok")

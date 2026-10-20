"""Bot stop/TP through the Binance Algo Service, on a FAKE exchange (classic endpoint answers -4120 for conditional types, like the real one).
Run: python3 test/test_bot_algo_stop.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import protection_manager as PM, binance_trader as BT

algo, classic, calls = {}, {}, []
nid = [100]


def fake(method, path, params=None, timeout=None):
    params = dict(params or {})
    calls.append((method, path, params.get("type")))
    err = lambda st, code: PM.ProtectionAPIError(st, json.dumps({"code": code, "msg": "x"}))
    if path == "/fapi/v2/positionRisk":
        return [{"symbol": "AAAUSDT", "positionAmt": "10", "entryPrice": "100"}]
    if path == "/fapi/v1/algoOrder" and method == "POST":
        assert params["algoType"] == "CONDITIONAL" and params["closePosition"] == "true" and "triggerPrice" in params
        nid[0] += 1
        algo[nid[0]] = {"algoId": nid[0], "symbol": params["symbol"], "orderType": params["type"], "triggerPrice": str(params["triggerPrice"]), "side": params["side"]}
        return {"algoId": nid[0]}
    if path == "/fapi/v1/algoOrder" and method == "DELETE":
        if params["algoId"] not in algo:
            raise err(400, -2011)
        del algo[params["algoId"]]
        return {}
    if path == "/fapi/v1/openAlgoOrders":
        return list(algo.values())
    if path == "/fapi/v1/openOrders":
        return list(classic.values())
    if path == "/fapi/v1/order" and method == "POST":
        if params["type"] in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            raise err(400, -4120)
        return {"orderId": 1}
    if path == "/fapi/v1/order" and method == "DELETE":
        raise err(400, -2011)
    if path == "/fapi/v1/allOpenOrders":
        return {}
    if path == "/fapi/v1/algoOpenOrders":
        algo.clear()
        return {}
    raise AssertionError("unexpected call %s %s" % (method, path))


PM._signed_request = fake
BT._signed_request = fake
PM.round_price = lambda s, p: round(float(p), 4)
BT.round_price = PM.round_price
BT._position_side = lambda s: "BUY"
PM._position_side = lambda s: "BUY"

# 1. place stop -> algo service, never the classic POST with a conditional type
oid = PM.place_stop_loss("AAAUSDT", "BUY", 95.0)
assert oid and len(algo) == 1, (oid, algo)
assert not [c for c in calls if c[1] == "/fapi/v1/order" and c[0] == "POST"], calls
# 2. it is found again, in the old shape reconciliation reads
st = PM.get_active_stop("AAAUSDT")
assert st and st["type"] == "STOP_MARKET" and float(st["stopPrice"]) == 95.0 and st["orderId"] == oid and st["_algo"]
assert BT.get_open_algo_orders("AAAUSDT")
# 3. tighten-only: looser is a no-op, tighter cancels + re-places
assert PM.modify_stop_loss("AAAUSDT", 90.0) == oid and len(algo) == 1
new = PM.modify_stop_loss("AAAUSDT", 100.0)
assert new and new != oid and len(algo) == 1 and float(PM.get_active_stop("AAAUSDT")["stopPrice"]) == 100.0
# 4. take profit goes next to the stop; changing it keeps the stop
tp = PM.set_target_tp("AAAUSDT", "BUY", 110.0)
assert tp and len(algo) == 2
assert PM.set_target_tp("AAAUSDT", "BUY", 112.0) and len(algo) == 2
assert PM.get_active_stop("AAAUSDT") and float(PM.get_active_take_profit("AAAUSDT")["stopPrice"]) == 112.0
# 5. auto break-even primitive of binance_trader
sl2 = BT.cancel_and_replace_sl("AAAUSDT", 101.0)
assert sl2 and float(PM.get_active_stop("AAAUSDT")["stopPrice"]) == 101.0 and len(algo) == 2
# 6. cancel stop only / everything
assert PM.cancel_sl("AAAUSDT") and len(algo) == 1
assert PM.cancel_all_protection("AAAUSDT") and not algo
# 7. bulk cancel also clears algo orders
PM.place_stop_loss("AAAUSDT", "BUY", 95.0)
assert BT.cancel_all_open_orders("AAAUSDT", confirm=True) and not algo
# 8. algo endpoint missing (404) -> classic fallback is used (and would be rejected here with -4120, so it must report failure, not crash)
def fake404(method, path, params=None, timeout=None):
    if path == "/fapi/v1/algoOrder":
        raise PM.ProtectionAPIError(404, "no")
    return fake(method, path, params, timeout)
PM._signed_request = fake404
assert PM.place_stop_loss("AAAUSDT", "BUY", 95.0) is None
# 9. a failed ALGO read must raise (so it is never mistaken for "no stop")
def failread(method, path, params=None, timeout=None):
    if path == "/fapi/v1/openAlgoOrders":
        raise PM.ProtectionAPIError(500, "boom")
    return fake(method, path, params, timeout)
PM._signed_request = failread
try:
    PM.get_open_conditional_orders("AAAUSDT")
    raise SystemExit("should have raised")
except PM.ProtectionAPIError:
    pass
print("bot algo stop test OK")

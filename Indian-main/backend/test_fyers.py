"""Fyers offline tests (fake transport - no network)."""
import hashlib, json, os, sys, tempfile
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import fyers_client as FC, fyers_provider as FP, india_broker
from recovered_bot.india_data import IST
from recovered_bot.india_runtime import IndiaRuntime

# ---- auth code extraction + login url ----
assert FC.extract_auth_code("abc123") == "abc123"
assert FC.extract_auth_code("https://www.google.com/?s=ok&code=200&auth_code=XYZ.1&state=owl") == "XYZ.1"
u = FC.auth_url("APP-100", "https://www.google.com")
assert "client_id=APP-100" in u and "response_type=code" in u

NOW = datetime.now(IST)
D0 = NOW.replace(hour=9, minute=15, second=0, microsecond=0)
SEQ = {"calls": []}

MASTER = ("101,NIFTY 20 Oct 26 23000 CE,14,65,0.05,x,s,2026-10-16,1792486200,NSE:NIFTY26O2023000CE,10,11\n"
          "102,NIFTY 20 Oct 26 23000 PE,14,65,0.05,x,s,2026-10-16,1792486200,NSE:NIFTY26O2023000PE,10,11\n"
          "103,NIFTY 20 Oct 26 22950 CE,14,65,0.05,x,s,2026-10-16,1792486200,NSE:NIFTY26O2022950CE,10,11\n"
          "104,BANKNIFTY 27 Oct 26 58000 CE,14,30,0.05,x,s,2026-10-16,1792486200,NSE:BANKNIFTY26O2758000CE,10,11\n"
          "105,RELIANCE 27 Oct 26 1300 CE,14,500,0.05,x,s,2026-10-16,1792486200,NSE:RELIANCE26O271300CE,10,11\n"
          "106,NIFTY 01 Jan 20 20000 CE,14,65,0.05,x,s,2026-10-16,1,NSE:NIFTY20J0120000CE,10,11\n")


def transport(method, url, headers, body, timeout=20):
    SEQ["calls"].append((method, url, dict(headers), body))
    if "validate-authcode" in url:
        assert body["appIdHash"] == hashlib.sha256(b"APP-100:SECRET").hexdigest()
        assert body["code"] == "CODE9"
        return 200, json.dumps({"s": "ok", "code": 200, "access_token": "TOK_ABC_123456"})
    assert headers.get("Authorization") == "APP-100:TOK_ABC_123456", headers
    if url.endswith("/profile"):
        return 200, json.dumps({"s": "ok", "data": {"name": "HUSSAIN", "fy_id": "X1"}})
    if url.endswith("/funds"):
        return 200, json.dumps({"s": "ok", "fund_limit": [
            {"title": "Total Balance", "equityAmount": 200000.5}, {"title": "Utilized Amount", "equityAmount": 1000},
            {"title": "Available Balance", "equityAmount": 199000.5}]})
    if "/data/quotes" in url:
        sy = url.split("symbols=")[1].replace("%3A", ":").replace("%2C", ",")
        d = [{"n": s, "s": "ok", "v": {"lp": 23000.5 if "INDEX" in s else 120.25, "prev_close_price": 22900.0}}
             for s in sy.split(",")]
        return 200, json.dumps({"s": "ok", "d": d})
    if "/data/history" in url:
        sym = url.split("symbol=")[1].split("&")[0]
        if "CE" in sym and "BAD" in sym:
            return 200, json.dumps({"s": "no_data", "candles": []})
        rows, t, p = [], D0.astimezone(timezone.utc) - timedelta(minutes=5 * 300), 22800.0
        for i in range(300):
            rows.append([int(t.timestamp()), p, p + 5, p - 5, p + 1, 100]); p += 1; t += timedelta(minutes=5)
        return 200, json.dumps({"s": "ok", "candles": rows})
    if "sym_details" in url:
        return 200, MASTER
    return 404, "{}"


# ---- master parser ----
m = FP.parse_master(MASTER, today=date(2026, 10, 15))
assert len(m["NIFTY"]) == 3 and m["NIFTY"][0]["lot"] == 65 and m["NIFTY"][0]["expiry"] == date(2026, 10, 20)
assert len(m["BANKNIFTY"]) == 1 and "RELIANCE" not in m

# ---- provider ----
prov = FP.FyersProvider(tf_min=5, client=FC.FyersClient(transport))
creds = {"app_id": "APP-100", "secret_id": "SECRET", "auth_code": "https://x/?auth_code=CODE9&state=owl"}
prov.connect(creds)
assert creds["access_token"] == "TOK_ABC_123456"
acc = prov.account_info()
assert acc["name"] == "HUSSAIN" and acc["net_available"] == 199000.5 and acc["total"] == 200000.5
assert abs(prov.get_spot("NIFTY") - 23000.5) < 1e-9
cs = prov._fetch_candles("NIFTY", 5, 100)
assert len(cs) == 100 and cs[0]["t"].tzinfo is not None and cs[-1]["t"] > cs[0]["t"]
cons = prov.get_contracts("NIFTY")
assert {c["strike"] for c in cons} == {22950, 23000} and all(c["lot"] == 65 for c in cons)
ce = next(c for c in cons if c["strike"] == 23000 and c["type"] == "CE")
assert abs(prov.get_option_ltp(ce) - 120.25) < 1e-9
assert prov.get_prev_close("NIFTY") == 22900.0
oc, src = prov.get_option_candles(ce, 5, 50)
assert src == "REAL" and len(oc) == 50

# ---- runtime: connect, balance per exchange, option chart ----
d = tempfile.mkdtemp()
rt = IndiaRuntime(d)
india_broker.register("fyers", FP.FyersProvider)
orig = FP.FyersClient
FP.FyersClient = lambda: FC.FyersClient(transport)
try:
    info = rt.connect_broker("fyers", {"app_id": "APP-100", "secret_id": "SECRET", "redirect_url": "https://www.google.com",
                                       "auth_code": "CODE9"})
finally:
    FP.FyersClient = orig
assert info["connected"] and info["name"] == "fyers" and info["accounts"]["fyers"]["net_available"] == 199000.5
saved = rt.creds.get("fyers")
assert saved["access_token"] == "TOK_ABC_123456" and "auth_code" not in saved and saved["app_id"] == "APP-100"
assert rt.broker_login_url("fyers")["url"].startswith("https://api-t1.fyers.in/api/v3/generate-authcode")
assert rt.refresh_balance("fyers")["accounts"]["fyers"]["name"] == "HUSSAIN"
try:
    rt.refresh_balance("tradebulls"); assert False
except india_broker.BrokerError:
    pass

# ---- demo option chart (model premium) with indicators + black-candle flag ----
rt2 = IndiaRuntime(tempfile.mkdtemp())
ch = rt2.chain("NIFTY", None, 5)
key = ch["rows"][2]["CE"]["key"]
oc = rt2.option_candles(key, 120, 5)
assert oc["source"] == "MODEL" and len(oc["candles"]) > 20 and "x50" in oc["candles"][0]
assert len(oc["indicators"]["ema"]["slow"]) == len(oc["candles"])
ic = rt2.candles("NIFTY", 150, 5)
assert any(c["x50"] for c in ic["candles"]) and len(ic["candles"]) == 150
print("fyers tests OK")

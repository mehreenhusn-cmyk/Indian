"""Fyers auto-renew login + what-if + holiday tests (fake transport, no network)."""
import hashlib, json, os, sys, tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import fyers_client as FC, fyers_provider as FP, india_broker, india_calendar as cal
from recovered_bot.india_data import IST
from recovered_bot.india_runtime import IndiaRuntime

H = hashlib.sha256(b"APP-100:SECRET").hexdigest()
STATE = {"expired": False, "refresh_calls": 0, "tok": "TOK_1_aaaaaa"}


def transport(method, url, headers, body, timeout=20):
    if "validate-authcode" in url:
        return 200, json.dumps({"s": "ok", "access_token": "TOK_1_aaaaaa", "refresh_token": "REF_xxxxxx"})
    if "validate-refresh-token" in url:
        assert body["appIdHash"] == H and body["refresh_token"] == "REF_xxxxxx" and body["pin"] == "1234", body
        STATE["refresh_calls"] += 1
        STATE["tok"] = f"TOK_R{STATE['refresh_calls']}_bbbbbb"
        STATE["expired"] = False
        return 200, json.dumps({"s": "ok", "access_token": STATE["tok"]})
    if STATE["expired"] or headers.get("Authorization") != f"APP-100:{STATE['tok']}":
        return 401, json.dumps({"s": "error", "code": -16, "message": "token expired"})
    if url.endswith("/profile"):
        return 200, json.dumps({"s": "ok", "data": {"name": "H", "fy_id": "X1"}})
    if url.endswith("/funds"):
        return 200, json.dumps({"s": "ok", "fund_limit": [{"title": "Total Balance", "equityAmount": 0},
                                                         {"title": "Available Balance", "equityAmount": 0}]})
    if "/data/quotes" in url:
        sy = url.split("symbols=")[1].replace("%3A", ":").replace("%2C", ",")
        return 200, json.dumps({"s": "ok", "d": [{"n": x, "s": "ok", "v": {"lp": 23000.5, "prev_close_price": 22900.0}}
                                                 for x in sy.split(",")]})
    if "sym_details" in url:
        return 200, ("101,NIFTY 27 Oct 26 23000 CE,14,65,0.05,x,s,2026-10-16,1,NSE:NIFTY26O2723000CE,10,11\n")
    return 404, "{}"


# 1) browser login returns a refresh token and the provider remembers it
p = FP.FyersProvider(client=FC.FyersClient(transport=transport))
creds = {"app_id": "APP-100", "secret_id": "SECRET", "auth_code": "CODE9", "pin": "1234"}
p.connect(creds)
assert creds["refresh_token"] == "REF_xxxxxx" and creds["refresh_day"] and creds["token_session"]
assert p.auth_info()["auto_renew"] and p.auth_info()["refresh_days_left"] == 15
assert "auth_code" not in {k for k in creds if k in FP.FyersProvider.persist}

# 2) next day / restart: NO auth code -> refresh token + PIN renews by itself
p2 = FP.FyersProvider(client=FC.FyersClient(transport=transport))
saved = {k: v for k, v in creds.items() if k in FP.FyersProvider.persist}
saved["token_session"] = "2000-01-01"                       # stale token from an old day
p2.connect(saved)
assert STATE["refresh_calls"] == 1 and p2.client.token.startswith("TOK_R1")

# 3) token dies mid-day: the next call renews and retries by itself
STATE["expired"] = True
spot = p2._fetch_spot("NIFTY")
assert spot == 23000.5 and STATE["refresh_calls"] == 2, STATE

# 4) wrong / missing PIN gives a readable message (and never loops)
p3 = FP.FyersProvider(client=FC.FyersClient(transport=transport))
bad = {k: v for k, v in saved.items() if k != "pin"}
bad["token_session"] = "2000-01-01"
try:
    p3.connect(bad)
    raise SystemExit("should fail")
except india_broker.BrokerError as e:
    assert "PIN" in str(e), e

# 5) secrets never appear in the diagnostic log
assert all("REF_xxxxxx" not in row[2] and "1234" not in row[2] for row in p.client.log)

# 6) runtime: saved refresh creds -> reconnect with no code; what-if with a zero balance
d = tempfile.mkdtemp()
rt0 = IndiaRuntime(d)
rt0.creds.save("fyers", {k: v for k, v in saved.items() if k != "token_session"})
rt0.settings["auto_connect_fyers"] = True
FP.FyersProvider.__init__.__defaults__  # (client default is the real one; patch below)
orig = FC.default_transport
FC.default_transport = transport
FP.FyersClient.__init__.__defaults__ = (transport,)
try:
    rt0.connect_broker("fyers")
    assert rt0.live is not None and rt0.settings["source"] == "fyers"
    info = rt0.broker_info()
    assert info["auth"]["auto_renew"] is True
finally:
    FC.default_transport = orig

now = datetime.now(IST)
mk = lambda i, cost_prem, pnl, o, c: dict(id=i, entry_premium=cost_prem, qty=65, buy_fee=20.0, pnl=pnl,
                                          opened_at=o, closed_at=c)
t = [mk(1, 100.0, 500.0, now - timedelta(hours=3), now - timedelta(hours=2)),
     mk(2, 100.0, -200.0, now - timedelta(hours=2, minutes=30), now - timedelta(hours=1)),
     mk(3, 100.0, 300.0, now - timedelta(minutes=50), now - timedelta(minutes=10))]
w0 = rt0.what_if(t, balance=0)
assert w0["taken"] == 0 and w0["skipped"] == 3 and w0["paper_pnl"] == 600.0 and w0["pnl_missed"] == 600.0
w1 = rt0.what_if(t, balance=7000)          # one trade (6520) fits at a time
assert w1["taken"] == 2 and w1["skipped"] == 1 and w1["pnl_with_balance"] == 800.0, w1
assert w1["needed_for_all"] == 13040.0, w1
assert rt0.report(period="30d")["what_if"]["paper_capital"] == 200000.0

# 7) holidays match NSE circular, with names
assert len(cal.HOLIDAYS) == 15 and date(2026, 10, 20) in cal.HOLIDAYS and date(2026, 12, 25) in cal.HOLIDAYS
assert "Dussehra" in cal.market_note(date(2026, 10, 20)) and cal.market_note(date(2026, 10, 21)) == ""
assert "Muhurat" in cal.market_note(date(2026, 11, 8))
print("fyers refresh tests OK")

"""Run on the phone/PC DURING MARKET HOURS:  python tradebulls_feed_probe.py
Logs in, opens the Price-Feed socket, subscribes the three index tokens and saves the first 40
raw packets (token masked) to tradebulls_feed_probe_output.txt. Send me that file if the app shows
no prices - it shows exactly which message/tag number in FeedSpec needs changing."""
import getpass, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot.india_broker import BrokerError
from recovered_bot.tradebulls_client import TradebullsClient
from recovered_bot.tradebulls_feed import PriceFeed, load_spec

c = {"base_url": input("API base URL (https://...): ").strip(), "user_id": input("User ID: ").strip(),
     "api_key": input("API key: ").strip(),
     "login_type": (input("Login type [PASSWORD/MPIN] (Enter = PASSWORD): ").strip() or "PASSWORD"),
     "password": getpass.getpass("Password/MPIN: "), "second_auth": getpass.getpass("2FA password: ")}
out, cl = [], TradebullsClient()
try:
    cl.login(c)
    out.append(f"LOGIN OK as {cl.user_name!r}; broadcast socket: {cl.broadcast_url}")
    spec = load_spec(os.path.dirname(os.path.abspath(__file__)))
    f = PriceFeed(cl.broadcast_url, c["user_id"].upper(), cl.broadcast_token, spec)
    for t in spec["index_tokens"].values():
        f.subscribe(t)
    f.start()
    for _ in range(40):                       # ~20 s
        time.sleep(0.5)
        if len(f.raw) >= 40:
            break
    f.stop()
    out += [f"feed status: {f.status} {f.error}", f"price ticks understood: {f.ticks}", f"last prices: {f.ltp}", "", "raw packets:"] + list(f.raw)
    cl.logout()
except BrokerError as e:
    out.append(f"FAILED: {e}")
text = "\n".join(out)
print(text)
open("tradebulls_feed_probe_output.txt", "w").write(text)

"""Run on the phone/PC to test Tradebulls login WITHOUT the app:  python tradebulls_probe.py
Prints a masked summary (token/password never shown) and saves tradebulls_probe_output.txt -
send me that file if the app's Connect shows an error."""
import getpass, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot.india_broker import BrokerError
from recovered_bot.tradebulls_client import TradebullsClient

c = {"base_url": input("API base URL (https://...): ").strip(),
     "user_id": input("User ID: ").strip(),
     "api_key": input("API key: ").strip(),
     "login_type": (input("Login type [PASSWORD/MPIN] (Enter = PASSWORD): ").strip() or "PASSWORD"),
     "password": getpass.getpass("Password/MPIN: "),
     "second_auth": getpass.getpass("2FA password: ")}
cl, out = TradebullsClient(), []
try:
    cl.login(c)
    out += [f"LOGIN OK as {cl.user_name!r} at {cl.login_time}", f"exchanges: {cl.exchanges}",
            f"broadcast socket: {cl.broadcast_url}", f"message socket: {cl.message_url}"]
    try:
        out.append(f"balance: {cl.balance()}")
    except BrokerError as e:
        out.append(f"balance failed: {e}")
    cl.logout()
except BrokerError as e:
    out.append(f"FAILED: {e}")
out += ["", "raw (masked):"] + [f"{n} HTTP {code}: {txt}" for n, code, txt in cl.log]
text = "\n".join(out)
print(text)
open("tradebulls_probe_output.txt", "w").write(text)

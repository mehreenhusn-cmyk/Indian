"""tradebulls_client.py - Tradebulls REST client, written from the official "Tradebulls Rest API
v1.1.0" document (login, logout, balance). Market data is NOT in that document (it comes
from the separate Price-Feed socket), so it is not here.

Login   POST   /authentication/v1/user/session   body: user_id (CAPITALS), login_type, password,
                                                 second_auth, api_key, source
Logout  DELETE /authentication/v1/user/session
Balance GET    /authentication/v1/user/balance
Header on every later call:  Authorization: Bearer <access_token>
Replies: {"status": "success"|"error", "code", "message", "data"}
"""
import json

try:
    from .india_broker import BrokerError
except ImportError:
    from india_broker import BrokerError

LOGIN_PATH = "/authentication/v1/user/session"
BALANCE_PATH = "/authentication/v1/user/balance"
LOGIN_TYPES = ("PASSWORD", "MPIN")          # FINGERPRINT needs a phone sensor - not usable here


def default_transport(method, url, headers, body, timeout=15):
    import requests
    r = requests.request(method, url, headers=headers, json=body, timeout=timeout)
    return r.status_code, r.text


class TradebullsClient:
    def __init__(self, transport=None):
        self.transport = transport or default_transport
        self.base, self.token = "", None
        self.broadcast_token, self.broadcast_url, self.message_url = None, None, None
        self.user_name, self.login_time, self.exchanges = "", "", []
        self.log = []                         # (call, http code, masked reply) for the probe

    # ---- helpers ------------------------------------------------------
    def _mask(self, text, secrets=()):
        for s in list(secrets) + [self.token, self.broadcast_token]:
            if s and len(str(s)) > 3:
                text = text.replace(str(s), "***")
        return text

    def _call(self, name, method, path, body=None, secrets=()):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            code, text = self.transport(method, self.base + path, headers, body)
        except Exception as e:
            raise BrokerError(f"Cannot reach Tradebulls ({self.base}): {type(e).__name__}: {e}")
        self.log.append((name, code, self._mask(text, secrets)[:1200]))
        try:
            data = json.loads(text)
        except ValueError:
            raise BrokerError(f"{name}: reply was not JSON (HTTP {code}): {self._mask(text, secrets)[:200]}")
        if code == 401:
            self.token = None
            raise BrokerError("Tradebulls session expired - connect again")
        if code >= 400 or (isinstance(data, dict) and data.get("status") == "error"):
            msg = data.get("message") if isinstance(data, dict) else ""
            raise BrokerError(f"{name} failed (HTTP {code}, code {data.get('code', '-') if isinstance(data, dict) else '-'}): {msg or self._mask(text, secrets)[:200]}")
        return data

    # ---- API ----------------------------------------------------------
    def login(self, creds):
        base = str(creds.get("base_url", "")).strip().rstrip("/")
        if not base.startswith("http"):
            raise BrokerError("Enter the API base URL (starts with https://)")
        need = [k for k in ("user_id", "password", "second_auth", "api_key") if not str(creds.get(k, "")).strip()]
        if need:
            raise BrokerError("Fill in: " + ", ".join(need))
        lt = str(creds.get("login_type") or "PASSWORD").upper()
        if lt not in LOGIN_TYPES:
            raise BrokerError("Login type must be PASSWORD or MPIN")
        self.base, self.token = base, None
        body = {"user_id": str(creds["user_id"]).strip().upper(), "login_type": lt,
                "password": str(creds["password"]), "second_auth": str(creds["second_auth"]),
                "api_key": str(creds["api_key"]).strip(), "source": "WEBAPI"}
        secrets = (body["password"], body["second_auth"], body["api_key"])
        d = self._call("login", "POST", LOGIN_PATH, body, secrets)
        data = d.get("data") if isinstance(d, dict) else None
        if not isinstance(data, dict) or not data.get("access_token"):
            raise BrokerError("Login reply had no access_token: " + self._mask(json.dumps(d), secrets)[:250])
        self.token = data["access_token"]
        self.broadcast_token = data.get("broadcast_access_token")
        oth = data.get("others") or {}
        self.broadcast_url, self.message_url = oth.get("broadCastSocket"), oth.get("messageSocket")
        self.user_name, self.login_time = data.get("user_name", ""), data.get("login_time", "")
        self.exchanges = list(data.get("exchanges") or [])
        return data

    def logout(self):
        if self.token:
            try:
                self._call("logout", "DELETE", LOGIN_PATH)
            except BrokerError:
                pass
        self.token = None

    def balance(self):
        """Equity funds (net available cash) - used to show your account cash in the app."""
        d = self._call("balance", "GET", BALANCE_PATH)
        eq = ((d.get("data") or {}).get("equity")) or {}
        return {"net_available": eq.get("net_available"), "total_available": eq.get("total_available"),
                "total_utilised": eq.get("total_utilised")}

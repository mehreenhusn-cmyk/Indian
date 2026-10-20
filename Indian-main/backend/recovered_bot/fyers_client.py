"""fyers_client.py - Fyers API v3 REST client (login, profile, funds, history, quotes, symbol master).

Login: the daily access token expires, but Fyers also returns a REFRESH token (valid ~15 days).
With refresh token + your Fyers PIN saved on the server, the app renews the daily token by itself,
so the browser login is needed only about once every 15 days.
First login / when the refresh token has expired:
  1. app shows a login link  https://api-t1.fyers.in/api/v3/generate-authcode?client_id=<APP_ID>&redirect_uri=<URL>&response_type=code&state=owl
  2. you log in on Fyers, the browser lands on your redirect URL (google.com is fine)
  3. copy `auth_code=...` from that address (or paste the WHOLE address) into the app
  4. POST /api/v3/validate-authcode  {grant_type, appIdHash=sha256("APP_ID:SECRET"), code} -> access_token
Every later call carries   Authorization: <APP_ID>:<access_token>
Nothing here places an order. The transport is injectable so tests run offline.
"""
import hashlib
import json
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode

try:
    from .india_broker import BrokerError, RateLimited
except ImportError:
    from india_broker import BrokerError, RateLimited

API = "https://api-t1.fyers.in/api/v3"
DATA = "https://api-t1.fyers.in/data"
MASTER = "https://public.fyers.in/sym_details/{seg}.csv"
DATA_CALLS = ("quotes", "history")      # the calls that count against the plan limit and are throttled
COOLDOWN_SEC = 20                       # pause after Fyers says "too many requests"


def default_transport(method, url, headers, body, timeout=20):
    import requests
    r = requests.request(method, url, headers=headers, json=body, timeout=timeout)
    return r.status_code, r.text


def auth_url(app_id, redirect_url, state="owl"):
    q = urlencode({"client_id": app_id, "redirect_uri": redirect_url, "response_type": "code", "state": state})
    return f"{API}/generate-authcode?{q}"


def extract_auth_code(text):
    """Accept the bare code OR the whole redirected address (…?s=ok&code=200&auth_code=XXXX&state=owl)."""
    t = (text or "").strip()
    if "auth_code=" in t:
        try:
            q = parse_qs(urlparse(t).query)
            if q.get("auth_code"):
                return q["auth_code"][0]
        except Exception:
            pass
        return t.split("auth_code=")[1].split("&")[0].strip()
    return t


class FyersClient:
    def __init__(self, transport=None):
        self.transport = transport or default_transport
        self.app_id, self.token = "", ""
        self.refresh_token = ""
        self.renewer = None                 # callable() -> bool, set by the provider: renews an expired token
        self._renewing = False
        self.log = []                       # (call, http code, masked reply) for diagnosing
        self.max_per_min = 40               # Fyers Standard plan = 50/min; stay safely under it
        self._stamps, self._rl_lock = deque(), threading.Lock()
        self.cooldown_until, self.limited_count = 0.0, 0

    # ---- plumbing -------------------------------------------------------
    def _mask(self, text):
        for s in (self.token, self.refresh_token):
            if s and len(s) > 6:
                text = text.replace(s, "***")
        # tokens in a reply that arrives BEFORE we store them (login / refresh answers)
        return re.sub(r'("(?:access_token|refresh_token)"\s*:\s*")[^"]+', r'\1***', text)

    def _gate(self, name):
        """Our own request budget: never send more than max_per_min data calls in a minute."""
        now = time.time()
        if name in DATA_CALLS and now < self.cooldown_until:
            raise RateLimited(f"Fyers limit reached - waiting {int(self.cooldown_until - now) + 1}s, showing last data")
        with self._rl_lock:
            while self._stamps and now - self._stamps[0] > 60:
                self._stamps.popleft()
            if name in DATA_CALLS and len(self._stamps) >= self.max_per_min:
                raise RateLimited("Fyers call budget used for this minute - showing last data")
            self._stamps.append(now)

    def _hit_limit(self):
        self.cooldown_until = time.time() + COOLDOWN_SEC
        self.limited_count += 1

    def calls_per_min(self):
        now = time.time()
        with self._rl_lock:
            return sum(1 for t in self._stamps if now - t <= 60)

    def limit_info(self):
        wait = max(0, int(self.cooldown_until - time.time()))
        return {"calls_per_min": self.calls_per_min(), "max_per_min": self.max_per_min,
                "limited_now": wait > 0, "wait_sec": wait, "limited_count": self.limited_count}

    def _call(self, name, method, url, body=None, raw=False, _retry=False):
        if not raw:
            self._gate(name)
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"{self.app_id}:{self.token}"
        try:
            code, text = self.transport(method, url, h, body)
        except Exception as e:
            raise BrokerError(f"Cannot reach Fyers: {type(e).__name__}: {e}")
        self.log.append((name, code, self._mask(text)[:600]))
        if not raw and name in DATA_CALLS and (
                code == 429 or ("limit of" in text.lower() and "request" in text.lower())):
            self._hit_limit()
            raise RateLimited(f"Fyers limit reached - waiting {COOLDOWN_SEC}s, showing last data")
        if raw:
            if code >= 400:
                raise BrokerError(f"{name}: HTTP {code}")
            return text
        try:
            d = json.loads(text)
        except ValueError:
            raise BrokerError(f"{name}: reply was not JSON (HTTP {code}): {self._mask(text)[:160]}")
        if name not in ("refresh", "login") and (
                code in (401, 403) or (isinstance(d, dict) and d.get("code") in (-16, -17, -15))):
            self.token = ""
            if self.renewer and not self._renewing and not _retry:
                self._renewing = True
                try:
                    renewed = bool(self.renewer())
                except Exception:
                    renewed = False
                finally:
                    self._renewing = False
                if renewed:                     # one automatic retry with the fresh token
                    return self._call(name, method, url, body, raw, _retry=True)
            raise BrokerError("Fyers session expired - the saved refresh token is missing or has expired; log in again")
        if isinstance(d, dict) and d.get("s") == "error":
            raise BrokerError(f"{name}: {d.get('message') or d.get('code')}")
        if code >= 400:
            raise BrokerError(f"{name}: HTTP {code}")
        return d

    # ---- login ----------------------------------------------------------
    def login(self, creds):
        """creds: app_id, secret_id + auth_code (new day) OR access_token (already have one today)."""
        self.app_id = str(creds.get("app_id", "")).strip()
        if not self.app_id:
            raise BrokerError("Fyers App ID is missing")
        tok = str(creds.get("access_token", "")).strip()
        code = extract_auth_code(creds.get("auth_code", ""))
        if code:
            secret = str(creds.get("secret_id", "")).strip()
            if not secret:
                raise BrokerError("Fyers Secret ID is missing")
            h = hashlib.sha256(f"{self.app_id}:{secret}".encode()).hexdigest()
            d = self._call("login", "POST", f"{API}/validate-authcode",
                           {"grant_type": "authorization_code", "appIdHash": h, "code": code})
            tok = d.get("access_token") or ""
            if not tok:
                raise BrokerError(f"Fyers login failed: {d.get('message') or d}")
            self.refresh_token = d.get("refresh_token") or self.refresh_token
        if not tok:
            raise BrokerError("Paste the auth code from the Fyers login page")
        self.token = tok
        return tok

    def refresh(self, creds):
        """Daily renewal without the browser: refresh_token + Fyers PIN -> new access token."""
        self.app_id = str(creds.get("app_id", "")).strip() or self.app_id
        secret = str(creds.get("secret_id", "")).strip()
        rt = str(creds.get("refresh_token", "")).strip() or self.refresh_token
        pin = str(creds.get("pin", "")).strip()
        if not (self.app_id and secret):
            raise BrokerError("Fyers App ID / Secret missing")
        if not rt:
            raise BrokerError("No saved refresh token - do the browser login once")
        if not pin:
            raise BrokerError("Fyers PIN is not saved - enter it once so the app can renew the login by itself")
        self.refresh_token = rt
        h = hashlib.sha256(f"{self.app_id}:{secret}".encode()).hexdigest()
        self.token = ""
        d = self._call("refresh", "POST", f"{API}/validate-refresh-token",
                       {"grant_type": "refresh_token", "appIdHash": h, "refresh_token": rt, "pin": pin})
        tok = d.get("access_token") or ""
        if not tok:
            raise BrokerError(f"Fyers refresh failed: {d.get('message') or d}")
        self.token = tok
        self.refresh_token = d.get("refresh_token") or rt
        return tok

    # ---- account --------------------------------------------------------
    def profile(self):
        d = self._call("profile", "GET", f"{API}/profile").get("data") or {}
        return {"name": d.get("name") or d.get("display_name") or "", "client_id": d.get("fy_id") or ""}

    def funds(self):
        """-> dict(total, used, available) in rupees (equity)."""
        rows = self._call("funds", "GET", f"{API}/funds").get("fund_limit") or []
        pick = lambda *names: next((float(r.get("equityAmount") or 0) for r in rows
                                    if str(r.get("title", "")).strip().lower() in names), None)
        return {"total": pick("total balance"), "used": pick("utilized amount"),
                "net_available": pick("available balance", "clear balance")}

    # ---- market data ----------------------------------------------------
    def quotes(self, symbols):
        """-> {symbol: {lp, prev_close, ch, chp}}"""
        d = self._call("quotes", "GET", f"{DATA}/quotes?" + urlencode({"symbols": ",".join(symbols)}))
        out = {}
        for r in d.get("d") or []:
            v = r.get("v") or {}
            if isinstance(v, dict) and v.get("lp") is not None:
                out[r.get("n")] = {"lp": float(v["lp"]), "prev_close": v.get("prev_close_price"),
                                   "ch": v.get("ch"), "chp": v.get("chp")}
        return out

    def history(self, symbol, resolution, d_from, d_to):
        """-> [(epoch_utc_seconds, o, h, l, c, v)] oldest first. d_from/d_to = date objects."""
        q = {"symbol": symbol, "resolution": str(resolution), "date_format": "1", "cont_flag": "1",
             "range_from": d_from.isoformat(), "range_to": d_to.isoformat()}
        d = self._call("history", "GET", f"{DATA}/history?" + urlencode(q))
        if d.get("s") not in (None, "ok", "no_data"):
            raise BrokerError(f"history: {d.get('message') or d.get('s')}")
        return [tuple(r) for r in d.get("candles") or []]

    def symbol_master(self, segment="NSE_FO"):
        return self._call("symbol_master", "GET", MASTER.format(seg=segment), raw=True)

    def logout(self):
        self.token = ""

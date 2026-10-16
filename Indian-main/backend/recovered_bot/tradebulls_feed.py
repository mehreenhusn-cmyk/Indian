"""tradebulls_feed.py - live prices from the Tradebulls / ODIN Price-Feed socket.

Three small, separate pieces:
  FeedSpec      every protocol detail in ONE editable place (message numbers, tag numbers,
                index tokens, price divisor). Override any of it in <data_dir>/india_feed_spec.json
                without touching code.
  TickCandles   builds candles from ticks: IST clock, 09:15 session anchor, 1-minute base bars
                that roll up to any timeframe, saved to disk so the strategy warms up over days.
  PriceFeed     socket client: login(101) -> subscribe(206) -> decode(209) -> last price per token.
  ContractBook  option contracts + tokens from a contract file (CSV) that YOU supply.

HONEST STATUS: the ODIN doc page we have is cut off, so the message/tag numbers below come from the
parts that were readable. Prices only need tag 8 (last price); candle time uses the phone clock, so
no time tag is needed. If a number is wrong the probe (tradebulls_feed_probe.py) shows the raw
packets and ONE value in FeedSpec fixes it. Nothing here places an order.
"""
import csv
import json
import logging
import os
import threading
import time
import zlib
from collections import deque
from datetime import date, datetime, timedelta

try:
    from .india_broker import BrokerError
    from .india_data import IST
    from . import india_calendar as cal
except ImportError:
    from india_broker import BrokerError
    from india_data import IST
    import india_calendar as cal

log = logging.getLogger("tradebulls_feed")

SESSION_OPEN = (9, 15)
SESSION_CLOSE = (15, 30)

SPEC_DEFAULT = {
    "header": "63=FT3.0|64={code}|65=84|66={time}",      # sample in the doc: 63=FT3.0|64=127|65=84|66=19:02:31|...
    "login_code": 101, "login_body": "1={user}|2={token}",
    "sub_code": 206, "sub_body": "1={seg}|7={tok}",      # one subscribe message per instrument
    "tick_codes": [209, 208, 207],                       # packets that carry prices
    "tag_seg": "1", "tag_token": "7", "tag_ltp": "8",
    "price_div": 0,                                      # 0 = auto (100 or 1, checked on the index)
    # NSE cash-segment index tokens: UNVERIFIED defaults - the probe prints what comes back
    "index_tokens": {"NIFTY": "1_26000", "BANKNIFTY": "1_26009", "FINNIFTY": "1_26037"},
    "sane": {"NIFTY": [5000, 60000], "BANKNIFTY": [10000, 120000], "FINNIFTY": [5000, 60000]},
    "fo_segment": 2,
}


def load_spec(data_dir=None):
    spec = json.loads(json.dumps(SPEC_DEFAULT))
    if data_dir:
        try:
            with open(os.path.join(data_dir, "india_feed_spec.json")) as f:
                spec.update(json.load(f))
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("bad india_feed_spec.json: %s", e)
    return spec


# ------------------------------------------------------------------ packets
def encode_packet(text):
    comp = zlib.compress(text.encode())
    return b"5" + b"%05d" % len(comp) + comp


def decode_packets(data):
    """bytes -> list of decoded text messages. Frame = '5' + 5-digit length + zlib text.
    Several frames can arrive in one socket message; plain text frames are passed through."""
    if isinstance(data, str):
        return [data]
    out, i, n = [], 0, len(data)
    while i < n:
        flag = data[i:i + 1]
        if flag == b"5" and i + 6 <= n and data[i + 1:i + 6].isdigit():
            ln = int(data[i + 1:i + 6])
            body = data[i + 6:i + 6 + ln]
            if len(body) < ln:
                break                                    # broken frame - wait for the next one
            try:
                out.append(zlib.decompress(body).decode(errors="replace"))
            except zlib.error:
                out.append("")
            i += 6 + ln
        else:
            out.append(data[i:].decode(errors="replace"))
            break
    return [m for m in out if m]


def parse_message(text):
    """'63=FT3.0|64=209|1=2|7=45001|8=13050' -> dict of tag -> value (last tag wins)."""
    d = {}
    for part in text.replace("$", "|").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
    return d


# ------------------------------------------------------------- tick candles
def _floor_bucket(t, tf):
    """Start of the candle containing t, anchored to 09:15 IST of that day."""
    open_t = t.replace(hour=SESSION_OPEN[0], minute=SESSION_OPEN[1], second=0, microsecond=0)
    mins = int((t - open_t).total_seconds() // 60)
    return open_t + timedelta(minutes=(mins // tf) * tf)


def in_session(t):
    hm = (t.hour, t.minute)
    return cal.is_trading_day(t.date()) and SESSION_OPEN <= hm < SESSION_CLOSE


class TickCandles:
    def __init__(self, path=None, keep_days=6):
        self.path, self.keep = path, timedelta(days=keep_days)
        self.m1 = {}                       # symbol -> list of dict(t, o, h, l, c, v) 1-minute bars
        self.lock = threading.Lock()
        self._saved = 0
        self._load()

    def add(self, sym, price, t=None):
        t = (t or datetime.now(IST)).astimezone(IST)
        if not in_session(t) or price <= 0:
            return False
        minute = t.replace(second=0, microsecond=0)
        with self.lock:
            bars = self.m1.setdefault(sym, [])
            if bars and bars[-1]["t"] == minute:
                b = bars[-1]
                b["h"], b["l"], b["c"], b["v"] = max(b["h"], price), min(b["l"], price), price, b["v"] + 1
            elif not bars or bars[-1]["t"] < minute:
                bars.append(dict(t=minute, o=price, h=price, l=price, c=price, v=1))
            else:
                return False               # out-of-order tick: ignore
            cut = minute - self.keep
            while bars and bars[0]["t"] < cut:
                bars.pop(0)
        if time.time() - self._saved > 60:
            self.save()
        return True

    def candles(self, sym, tf, limit=None):
        """Roll the 1-minute bars up to tf minutes (oldest first; last one may still be forming)."""
        with self.lock:
            bars = list(self.m1.get(sym, ()))
        out, cur = [], None
        for b in bars:
            k = _floor_bucket(b["t"], tf)
            if cur is not None and cur["t"] == k:
                cur["h"], cur["l"], cur["c"], cur["v"] = max(cur["h"], b["h"]), min(cur["l"], b["l"]), b["c"], cur["v"] + b["v"]
            else:
                cur = dict(t=k, o=b["o"], h=b["h"], l=b["l"], c=b["c"], v=b["v"])
                out.append(cur)
        return out[-limit:] if limit else out

    def save(self):
        self._saved = time.time()
        if not self.path:
            return
        with self.lock:
            data = {s: [dict(b, t=b["t"].isoformat()) for b in bs] for s, bs in self.m1.items()}
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except Exception:
            log.exception("save candles")

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path) as f:
                raw = json.load(f)
            for s, bs in raw.items():
                self.m1[s] = [dict(b, t=datetime.fromisoformat(b["t"])) for b in bs]
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("load candles")


# ---------------------------------------------------------------- the feed
class PriceFeed:
    """Socket client. `connector(url)` returns an object with send_binary(bytes), recv() -> bytes|str,
    close() - the default uses the websocket-client package (already in requirements_api.txt)."""

    def __init__(self, url, user_id, broadcast_token, spec=None, connector=None, on_tick=None):
        self.url, self.user, self.token = url, user_id, broadcast_token
        self.spec = spec or load_spec()
        self.connector = connector or self._default_connector
        self.on_tick = on_tick or (lambda tok, price, t: None)
        self.ltp, self.last_tick_at = {}, 0.0
        self.raw = deque(maxlen=40)                     # last decoded packets (masked) for the probe
        self.status, self.error = "idle", ""
        self.subs, self.ticks = set(), 0
        self._ws, self._stop = None, threading.Event()
        self._thread, self._lock = None, threading.Lock()

    @staticmethod
    def _default_connector(url):
        try:
            import websocket
        except ImportError:
            raise BrokerError("Install the websocket-client package:  pip install websocket-client")
        ws = websocket.create_connection(url, timeout=15)
        ws.settimeout(20)

        class W:
            def send_binary(self, b): ws.send_binary(b)
            def recv(self): return ws.recv()
            def close(self): ws.close()
        return W()

    # ---- messages
    def _msg(self, code, body):
        head = self.spec["header"].format(code=code, time=datetime.now(IST).strftime("%H:%M:%S"))
        return encode_packet(head + "|" + body)

    def _send(self, code, body):
        with self._lock:
            if self._ws is None:
                raise BrokerError("price feed not connected")
            self._ws.send_binary(self._msg(code, body))

    def subscribe(self, token):
        """token = '<segment>_<exchange token>', e.g. '1_26000' (NSE cash) or '2_45001' (NSE F&O)."""
        seg, tok = str(token).split("_", 1)
        self.subs.add(token)
        if self._ws is not None:
            self._send(self.spec["sub_code"], self.spec["sub_body"].format(seg=seg, tok=tok))

    # ---- lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="tradebulls_feed")
        self._thread.start()

    def stop(self):
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self.status = "stopped"

    def _run(self):
        delay = 2
        while not self._stop.is_set():
            try:
                self.status = "connecting"
                ws = self.connector(self.url)
                with self._lock:
                    self._ws = ws
                ws.send_binary(self._msg(self.spec["login_code"],
                                         self.spec["login_body"].format(user=self.user, token=self.token)))
                for t in sorted(self.subs):
                    seg, tok = t.split("_", 1)
                    ws.send_binary(self._msg(self.spec["sub_code"], self.spec["sub_body"].format(seg=seg, tok=tok)))
                self.status, self.error, delay = "connected", "", 2
                while not self._stop.is_set():
                    self._handle(ws.recv())
            except Exception as e:
                if self._stop.is_set():
                    break
                self.status, self.error = "reconnecting", f"{type(e).__name__}: {e}"[:200]
                with self._lock:
                    self._ws = None
                self._stop.wait(delay)
                delay = min(delay * 2, 30)           # 2,4,8,16,30s - no hammering the broker

    def _handle(self, data):
        for text in decode_packets(data):
            self.raw.append(text.replace(str(self.token), "***")[:300])
            d = parse_message(text)
            p = d.get(self.spec["tag_ltp"])
            tok = d.get(self.spec["tag_token"])
            if p is None or tok is None:
                continue
            try:
                price = float(p)
            except ValueError:
                continue
            key = f"{d.get(self.spec['tag_seg'], '?')}_{tok}"
            self.ltp[key] = price
            self.last_tick_at = time.time()
            self.ticks += 1
            self.on_tick(key, price, datetime.now(IST))


# ------------------------------------------------------------ contract book
ALIASES = {"token": ("token", "scripcode", "exchangetoken", "scrip_code", "instrument_token"),
           "symbol": ("symbol", "underlying", "name"),
           "expiry": ("expiry", "expirydate", "expiry_date"),
           "strike": ("strike", "strikeprice", "strike_price"),
           "type": ("optiontype", "option_type", "type", "cetype"),
           "lot": ("lotsize", "lot_size", "marketlot", "lot")}


def _norm(h):
    return h.strip().lower().replace(" ", "").replace("-", "_")


def _parse_date(s):
    s = s.strip()
    for f in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d%b%Y"):
        try:
            return datetime.strptime(s.title() if "%b" in f else s, f).date()
        except ValueError:
            pass
    if s.isdigit() and len(s) >= 9:                        # unix seconds, or 1980-based seconds
        ts = int(s)
        for off in (0, 315532800):
            d = datetime.fromtimestamp(ts + off, IST).date()
            if abs((d - date.today()).days) < 800:
                return d
    raise ValueError(f"unreadable expiry date: {s!r}")


class ContractBook:
    """Option contracts read from a CSV you provide (broker contract file). Needed ONLY to get real
    option premiums from the feed - without it the paper engine prices options with the model."""

    def __init__(self, fo_segment=2):
        self.rows, self.seg, self.source = [], fo_segment, ""

    def load_csv(self, path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            cols = {_norm(h): h for h in (rd.fieldnames or [])}
            pick = {k: next((cols[a] for a in al if a in cols), None) for k, al in ALIASES.items()}
            miss = [k for k, v in pick.items() if v is None]
            if miss:
                raise BrokerError(f"Contract file needs columns for: {', '.join(miss)} (found: {', '.join(cols)})")
            rows, bad = [], 0
            for r in rd:
                try:
                    ty = str(r[pick["type"]]).strip().upper()[:2]
                    if ty not in ("CE", "PE"):
                        continue
                    rows.append(dict(underlying=str(r[pick["symbol"]]).strip().upper(),
                                     expiry=_parse_date(r[pick["expiry"]]), strike=float(r[pick["strike"]]),
                                     type=ty, lot=int(float(r[pick["lot"]])), token=str(r[pick["token"]]).strip()))
                except (ValueError, KeyError):
                    bad += 1
        if not rows:
            raise BrokerError("Contract file had no usable CE/PE rows")
        self.rows, self.source = rows, os.path.basename(path)
        return len(rows), bad

    def contracts(self, underlying):
        out = []
        for r in self.rows:
            if r["underlying"] == underlying and r["expiry"] >= date.today():
                out.append(dict(underlying=underlying, expiry=r["expiry"], strike=r["strike"], type=r["type"],
                                lot=r["lot"], key=f"{underlying}-{r['expiry']}-{int(r['strike'])}{r['type']}",
                                feed_token=f"{self.seg}_{r['token']}"))
        return out

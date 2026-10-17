"""india_runtime.py - runs the India paper engine in the background so the Flutter
app can start/stop/watch it. Fully separate from the crypto bot (own thread, own
state, own settings file) - nothing here touches paper_trader / trades.json.

Source today = "demo" (synthetic candles replayed one candle per `speed_sec`).
Later a broker provider (Upstox/Dhan/...) replaces ReplayProvider; engine, bridge,
API and app stay as they are.
"""
import json
import logging
import os
import random
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta

try:
    from .strategy import ABCDStrategy
    from .india_data import ReplayProvider, synthetic_candles, demo_start, IST
    from .india_paper import IndiaPaperEngine
    from .india_bridge import IndiaStrategyRunner
    from . import india_chain, india_reports, india_broker, india_calendar as cal, india_indicators as ind
    from . import tradebulls_provider  # noqa: F401  (registers the Tradebulls broker)
    from . import fyers_provider  # noqa: F401  (registers the Fyers broker)
    from . import fyers_client, india_pricing
    from .india_paper import TRAIL_MODES, PRODUCTS, SL_TYPES
except ImportError:
    from strategy import ABCDStrategy
    from india_data import ReplayProvider, synthetic_candles, demo_start, IST
    from india_paper import IndiaPaperEngine
    from india_bridge import IndiaStrategyRunner
    import india_chain, india_reports, india_broker, india_calendar as cal, india_indicators as ind
    import tradebulls_provider  # noqa: F401  (registers the Tradebulls broker)
    import fyers_provider  # noqa: F401  (registers the Fyers broker)
    import fyers_client, india_pricing
    from india_paper import TRAIL_MODES, PRODUCTS, SL_TYPES

log = logging.getLogger("india_runtime")

ALL_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
START_PRICE = {"NIFTY": 22700, "BANKNIFTY": 55480, "FINNIFTY": 24500}
TF_CHOICES = (1, 3, 5, 15)          # minutes - bot timeframe and chart timeframe
DEFAULTS = {"underlyings": ["NIFTY", "BANKNIFTY"], "tf": 5, "lots": 1, "itm_depth": 1,
            "product": "INTRADAY", "target_level": 4, "breakeven": True,
            "trail_mode": "off", "fit_balance": True, "budget_pct": 0.95,
            "min_premium": 20.0, "pin_fallback": True, "emergency_pct": 0.0,
            "sl_type": "index", "premium_sl_pct": 30.0,
            "max_loss_pct": 0.0, "capital": 200000.0, "speed_sec": 1.0, "source": "demo", "poll_sec": 5.0,
            "auto_connect_fyers": True, "was_running": False,
            "tg_enabled": False, "tg_tf": 15}
# engine-side settings (applied live); the rest (capital/speed/underlyings) are runtime-side
ENGINE_KEYS = ("lots", "itm_depth", "product", "target_level", "breakeven", "trail_mode",
               "fit_balance", "budget_pct", "min_premium", "pin_fallback",
               "emergency_pct", "max_loss_pct", "sl_type", "premium_sl_pct")
NUM = {"lots": (int, 1, 50), "itm_depth": (int, 1, 5), "target_level": (int, 1, 4),
       "speed_sec": (float, 0.1, 60.0), "poll_sec": (float, 2.0, 60.0), "budget_pct": (float, 0.1, 1.0),
       "min_premium": (float, 0.0, 1000.0), "emergency_pct": (float, 0.0, 0.9), "premium_sl_pct": (float, 1.0, 90.0),
       "max_loss_pct": (float, 0.0, 100.0), "capital": (float, 1000.0, 1e9)}
BOOLS = ("breakeven", "fit_balance", "pin_fallback", "auto_connect_fyers", "tg_enabled")


def _ser(o):
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_ser(v) for v in o]
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return o


class IndiaRuntime:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.lock = threading.RLock()
        self._stop_evt = threading.Event()      # wakes the market-closed sleep when Stop is pressed
        self.thread = None
        self.running = False
        self._stop_evt.set()
        self.finished = False
        self.events = deque(maxlen=40)
        self.settings = dict(DEFAULTS)
        self._path = os.path.join(data_dir, "india_settings.json")
        try:
            with open(self._path) as f:
                self.settings.update(json.load(f))
        except Exception:
            pass
        cal.load_extra(os.path.join(data_dir, "india_holidays.txt"))
        self.settings["tf"] = self._tf_ok(self.settings.get("tf"))
        self.creds = india_broker.CredStore(data_dir)
        self.live = None            # connected LiveProvider with market data (None = demo)
        self.login_ok = None        # provider whose login worked but has no market data yet
        self.broker_error = ""
        self._fast_evt = threading.Event()   # set by the live price feed on every tick (see _wake_fast)
        self._fast_n, self._fast_last = 0, 0.0
        self._chain_last = {}       # last good chain per (underlying, expiry): shown when Fyers says 'too many requests'
        self.accounts = {}          # broker name -> last account/balance info (exchange-wise balance)
        if self.settings.get("source") != "demo":
            self.settings["source"] = "demo"   # a broker needs a fresh login after restart
        self._build()
        self._fast_thread = threading.Thread(target=self._fast_loop, daemon=True, name="india_fast_sl")
        self._fast_thread.start()
        self._auto_thread = None
        self._start_autoconnect()
        self.tg = None              # India Telegram signals: own watcher thread, never touches trading
        try:
            from .india_telegram import IndiaTelegram
        except ImportError:
            from india_telegram import IndiaTelegram
        try:
            self.tg = IndiaTelegram(self, data_dir)
        except Exception:
            log.exception("india telegram watcher could not start")

    # ----------------------------------------------------------- build ---
    @staticmethod
    def _tf_ok(v, default=5):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return default
        return v if v in TF_CHOICES else default

    def _state_file(self):
        return os.path.join(self.dir, f"india_paper_state_{self.settings['source']}.json")

    def _build(self):
        s = self.settings
        tf = self._tf_ok(s.get("tf"))
        live = self.live is not None
        if live:
            self.provider = self.live
            self.provider.set_tf(tf)
            self.provider.tick_hook = self._wake_fast       # live ticks wake the fast stop-loss check
        else:
            seed = random.randint(1, 10 ** 6)
            days = 30                                   # 1-minute base bars, merged to any timeframe
            st = demo_start(days)                       # history ends on the latest real trading day
            data = {u: synthetic_candles(START_PRICE[u], days, tf_min=1, seed=seed + k, start=st, holidays=True)
                    for k, u in enumerate(ALL_UNDERLYINGS)}
            self.provider = ReplayProvider(data, tf_min=tf, base_tf=1, start=210 * tf - 1)   # 210 candles of history
        self.engine = IndiaPaperEngine(
            self.provider, {"capital": float(s["capital"]), **{k: s[k] for k in ENGINE_KEYS}},
            state_path=self._state_file(), restore=live)   # demo is synthetic: never restored
        self.runner = IndiaStrategyRunner(
            self.provider, self.engine, ABCDStrategy(lookback_len=200, ema_length=50), tf_min=tf)
        self.finished = False
        self.events.clear()

    def _apply_tf(self, tf):
        """Switch the timeframe the bot trades on, without losing trades or positions."""
        self.settings["tf"] = tf
        self.provider.set_tf(tf)
        if hasattr(self.provider, "ensure_history"):
            self.provider.ensure_history(210)          # demo: jump to where 210 candles of this tf exist
        self.runner.tf = tf
        self.runner._last.clear()

    # ------------------------------------------------------------ loop ---
    def _prewarm(self, positions=(), unders=(), candles=False):
        """Network fetches done OUTSIDE self.lock. They only fill the provider cache (own lock), so the code that
        runs under self.lock later reads warm data and returns fast. Same calls the engine/runner make -> same data.
        Returns (limited, skip): skip = underlyings whose candles could not be fetched this round."""
        limited, skip, p = False, set(), self.provider
        if not getattr(p, "is_live", False):
            return limited, skip
        for pos in positions:
            try:
                u = pos["underlying"]
                p.get_spot(u)
                p.get_last_candle(u)
                p.get_option_ltp(pos["contract"])
            except india_broker.RateLimited:
                limited = True
            except Exception:
                pass                                   # engine.on_tick handles its own errors, as before
        if candles:
            for u in unders:
                try:
                    p.get_candles(u.upper(), self.runner.tf, self.runner.history)
                except india_broker.RateLimited:
                    limited = True
                    skip.add(u)
                except Exception as e:
                    log.exception("prewarm %s", u)
                    self.broker_error = f"{u}: {e}"[:200]
                    skip.add(u)
        return limited, skip

    def _loop(self):
        while True:
            t0 = time.time()
            with self.lock:                                   # short: no network, no sleep in here
                if not self.running:
                    break
                live = getattr(self.provider, "is_live", False)
                if not live and not self.provider.step():
                    self.engine.close_all("END")
                    self.running, self.finished = False, True
                    break
                closed = live and india_chain.market_status(self.provider.now()) == "CLOSED" and not self.engine.open
                poll = float(self.settings["poll_sec"])
            if live:
                self._keepalive()                             # outside the lock (may call the broker)
            if closed:
                self._stop_evt.wait(min(30.0, max(5.0, poll)))   # market closed: sleep WITHOUT the lock; Stop wakes it
                continue
            with self.lock:                                   # Stop / source switch may have happened meanwhile
                if not self.running:
                    break
                live = getattr(self.provider, "is_live", False)
                unders = list(self.settings["underlyings"])
                positions = list(self.engine.open.values())
            limited, skip = self._prewarm(positions, unders, candles=True)   # slow broker calls, no lock held
            with self.lock:
                if not self.running:
                    break
                try:
                    self.engine.on_tick()
                except india_broker.RateLimited:
                    limited = True
                except Exception as e:
                    log.exception("on_tick")
                    self.broker_error = str(e)[:200]
                for u in unders:
                    if u in skip:
                        continue
                    try:
                        r = self.runner.run(u)
                    except india_broker.RateLimited:
                        limited = True
                        continue
                    except Exception as e:
                        log.exception("runner %s", u)
                        self.broker_error = f"{u}: {e}"[:200]
                        continue
                    if r and "signal" in r:
                        sg = r["signal"]
                        self.events.appendleft({
                            "time": self.provider.now().isoformat(), "underlying": u,
                            "signal": sg.action, "ok": bool(r.get("ok")),
                            "note": "opened" if r.get("ok") else r.get("reason", "")})
                if limited:
                    self.broker_error = "Fyers limit reached - showing last data"
                elif self.broker_error.startswith("Fyers limit"):
                    self.broker_error = ""
                speed = float(self.settings["poll_sec" if live else "speed_sec"])
            time.sleep(max(0.02, speed - (time.time() - t0)))

    # ------------------------------------------------ tick-driven SL check ---
    def _wake_fast(self):
        """Called from the price-feed thread on every tick: must stay instant (just sets a flag)."""
        self._fast_evt.set()

    def _fast_loop(self):
        """Runs the engine's exit check right after live ticks (at most ~2-3 times a second) instead of waiting for
        the next poll_sec loop. Exit RULES are unchanged (engine.on_tick); only how soon they are looked at.
        The REST loop keeps running as the backup if the feed goes quiet."""
        while True:
            self._fast_evt.wait(2.0)
            self._fast_evt.clear()
            try:
                if not self.running or not getattr(self.provider, "is_live", False) or not self.engine.open:
                    continue
                gap = time.time() - self._fast_last
                if gap < 0.4:
                    time.sleep(0.4 - gap)
                self._fast_last = time.time()
                with self.lock:
                    pos = list(self.engine.open.values())
                self._prewarm(pos)                           # broker fetches outside the lock
                with self.lock:
                    if self.running and self.engine.open:
                        self.engine.on_tick()
                        self._fast_n += 1
            except india_broker.RateLimited:
                pass
            except Exception:
                log.exception("fast SL check")
                time.sleep(1.0)

    def _feed_age_ms(self):
        try:
            f = getattr(self.provider, "feed", None)
            t = float(getattr(f, "last_tick", 0) or getattr(f, "last_tick_at", 0) or 0)
            return int((time.time() - t) * 1000) if t else None
        except Exception:
            return None

    # --------------------------------------------------------- broker ---
    def broker_info(self):
        who = self.live or self.login_ok
        out = {"available": india_broker.available(), "connected": self.live is not None,
               "login_ok": self.login_ok is not None, "data_ready": self.live is not None,
               "account": who.account_info() if who is not None and hasattr(who, "account_info") else {},
               "name": getattr(who, "name", None), "error": self.broker_error,
               "saved": {n: self.creds.masked(n) for n in india_broker.available()},
               "accounts": dict(self.accounts)}
        out["auto_connect"] = bool(self.settings.get("auto_connect_fyers"))
        who2 = self.live or self.login_ok
        if who2 is not None and hasattr(who2, "auth_info"):
            out["auth"] = who2.auth_info()
        else:
            sv = self.creds.get("fyers")
            out["auth"] = {"auto_renew": bool(sv.get("refresh_token") and sv.get("pin")),
                           "note": getattr(self, "auto_note", ""), "refresh_days_left": None,
                           "needs_login_soon": not (sv.get("refresh_token") and sv.get("pin")), "hint": ""}
        if self.live is not None:
            out["feed_error"] = getattr(self.live, "last_error", "")
            if hasattr(self.live, "get_status"):
                out["feed"] = self.live.get_status()
        return out

    def connect_broker(self, name, creds=None):
        """Login (network, outside the lock), then switch to the live source.
        creds=None -> reuse the saved ones."""
        creds = {**self.creds.get(name), **{k: v for k, v in (creds or {}).items() if v not in (None, "")}}
        if not creds:
            raise india_broker.BrokerError("No API key saved yet - enter it first")
        prov = india_broker.make_provider(name)
        prov.data_dir = self.dir                      # lets a broker save candles / read its contract file
        prov.on_creds_changed = lambda c, _n=name: self._save_creds(_n, prov, c)
        try:
            prov.connect(creds)
        except india_broker.BrokerError as e:
            self.broker_error = str(e)
            raise
        except Exception as e:
            self.broker_error = f"{type(e).__name__}: {e}"[:300]
            raise india_broker.BrokerError(self.broker_error)
        if hasattr(prov, "account_info"):
            self.accounts[name] = {**prov.account_info(), "at": datetime.now(IST).isoformat()}
        self._save_creds(name, prov, creds)
        if name == "fyers":
            self.settings["auto_connect_fyers"] = True
            self._save_settings()
        with self.lock:
            self.running = False
            self._stop_evt.set()
            self._drop_session()
            if getattr(prov, "data_ready", True):
                self.live, self.login_ok, self.broker_error = prov, None, ""
                self.settings["source"] = name
            else:                       # login verified, but no market data yet -> stay on demo
                self.live, self.login_ok = None, prov
                self.broker_error = getattr(prov, "pending_note", "") or ""
                self.settings["source"] = "demo"
            self._build()
        return self.broker_info()

    def _save_creds(self, name, prov, creds):
        keep = getattr(prov, "persist", None)            # never store password / 2FA / one-time codes on disk
        self.creds.save(name, {k: v for k, v in creds.items() if keep is None or k in keep})

    def _save_settings(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self.settings, f)
        except Exception:
            log.exception("save india settings")

    # ---- Fyers: reconnect by itself after a restart / a new day (no daily login) ----
    def _start_autoconnect(self):
        saved = self.creds.get("fyers")
        if not (self.settings.get("auto_connect_fyers") and saved.get("refresh_token") and saved.get("pin")):
            return
        self._auto_thread = threading.Thread(target=self._autoconnect, daemon=True, name="fyers_auto")
        self._auto_thread.start()

    def _autoconnect(self):
        wait = 5
        while self.settings.get("auto_connect_fyers") and self.live is None:
            try:
                self.connect_broker("fyers")
                if self.settings.get("was_running"):
                    self.start()                     # trading resumes where it stopped
                self.auto_note = "Fyers reconnected automatically"
                return
            except Exception as e:
                self.broker_error = f"Auto-connect Fyers: {e}"[:200]
                log.warning("fyers auto-connect failed: %s", e)
                if "refresh token" in str(e).lower() or "pin" in str(e).lower():
                    return                           # needs a human (browser login / PIN) - do not hammer Fyers
                time.sleep(wait)
                wait = min(wait * 2, 300)

    def _keepalive(self):
        """Renew an expired Fyers session while running (cheap: the provider rate-limits itself)."""
        f = getattr(self.provider, "ensure_session", None)
        if f is not None:
            try:
                f()
            except Exception:
                log.exception("fyers keepalive")

    # ---- what if the real balance had been there? ----
    def broker_balance_value(self):
        a = self.accounts.get("fyers") or {}
        who = self.live or self.login_ok
        if who is not None and getattr(who, "name", None) == "fyers" and hasattr(who, "account_info"):
            a = who.account_info() or a
        for k in ("net_available", "total"):
            if a.get(k) is not None:
                return float(a[k]), True
        return 0.0, False

    def what_if(self, trades=None, balance=None):
        """Replays the closed paper trades against the REAL broker balance:
        a trade is only 'taken' if its cost fits the cash left at that moment."""
        trades = list(self.engine.closed if trades is None else trades)
        known = True
        if balance is None:
            balance, known = self.broker_balance_value()
        ev = []
        for t in trades:
            try:
                cost = t["entry_premium"] * t["qty"] + t["buy_fee"]
                ev.append((t["opened_at"], 0, t["id"], cost, t))
                ev.append((t["closed_at"], 1, t["id"], cost, t))
            except Exception:
                continue
        ev.sort(key=lambda e: (e[0], e[1]))
        cash, taken, skipped, pnl_taken, pnl_missed = float(balance), set(), 0, 0.0, 0.0
        out_cost, peak = 0.0, 0.0
        for when, kind, tid, cost, t in ev:
            if kind == 0:
                out_cost += cost
                peak = max(peak, out_cost)
                if cost <= cash:
                    cash -= cost
                    taken.add(tid)
                else:
                    skipped += 1
                    pnl_missed += t["pnl"]
            else:
                out_cost -= cost
                if tid in taken:
                    cash += cost + t["pnl"]
                    pnl_taken += t["pnl"]
        paper = round(sum(t["pnl"] for t in trades), 2)
        return {"balance": round(float(balance), 2), "balance_known": known, "trades": len(trades),
                "taken": len(taken), "skipped": skipped, "pnl_with_balance": round(pnl_taken, 2),
                "pnl_missed": round(pnl_missed, 2), "paper_pnl": paper,
                "paper_capital": float(self.settings["capital"]),
                "needed_for_all": round(peak, 2),
                "note": ("Paper trades use your paper capital. 'With balance' replays them against your real "
                         "Fyers cash: trades that did not fit would have been skipped.")}

    def refresh_balance(self, name):
        """Re-read balance of the CONNECTED broker `name` (fresh login is needed for the others)."""
        with self.lock:
            who = self.live or self.login_ok
            if who is None or getattr(who, "name", None) != name:
                raise india_broker.BrokerError(f"{name} is not connected - connect it first")
            if hasattr(who, "refresh_account"):
                who.refresh_account()
            self.accounts[name] = {**who.account_info(), "at": datetime.now(IST).isoformat()}
        return self.broker_info()

    def broker_login_url(self, name, app_id=None, redirect=None):
        if name != "fyers":
            raise india_broker.BrokerError("This broker has no login link")
        saved = self.creds.get("fyers")
        app_id, redirect = app_id or saved.get("app_id"), redirect or saved.get("redirect_url")
        if not app_id or not redirect:
            raise india_broker.BrokerError("Enter the Fyers App ID and redirect URL first")
        return {"url": fyers_client.auth_url(app_id, redirect)}

    def _drop_session(self):
        for p in (self.live, self.login_ok):
            try:
                if p is not None and hasattr(p, "disconnect"):
                    p.disconnect()
            except Exception:
                log.exception("broker logout")
        self.live = self.login_ok = None

    def disconnect_broker(self):
        self.settings["auto_connect_fyers"] = False      # user chose demo: do not reconnect behind their back
        self._save_settings()
        with self.lock:
            self.running = False
            self._stop_evt.set()
            self._drop_session()
            self.broker_error = ""
            self.settings["source"] = "demo"
            self._build()
        return self.broker_info()

    def forget_broker(self, name):
        self.creds.clear(name)
        return self.broker_info()

    # ------------------------------------------------------------- api ---
    def start(self):
        with self.lock:
            if self.finished:
                self._build()
            if self.running:
                return
            self._stop_evt.clear()
            self.running = True
            self.settings["was_running"] = True
            self._save_settings()
            if not (self.thread and self.thread.is_alive()):
                self.thread = threading.Thread(target=self._loop, daemon=True, name="india_paper")
                self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
            self._stop_evt.set()
            self.settings["was_running"] = False
            self._save_settings()

    def reset(self):
        with self.lock:
            self.running = False
            self._stop_evt.set()
            if self.live is not None:               # a reset must really clear the saved live trades
                try:
                    os.remove(self._state_file())
                except OSError:
                    pass
            self._build()

    def close_all(self):
        with self.lock:
            return _ser(self.engine.close_all("MANUAL"))

    def close_one(self, pos_id):
        with self.lock:
            return _ser(self.engine.close_one(pos_id))

    def update_settings(self, d):
        with self.lock:
            s = self.settings
            if "underlyings" in d:
                u = [x for x in map(str.upper, d["underlyings"]) if x in ALL_UNDERLYINGS]
                if u:
                    s["underlyings"] = u
            for k, (typ, lo, hi) in NUM.items():
                if k in d:
                    v = typ(d[k])
                    if lo <= v <= hi or (k == "capital" and v > 0):
                        s[k] = v
            for k in BOOLS:
                if k in d:
                    s[k] = bool(d[k])
            if "tg_tf" in d:
                try:
                    v = int(d["tg_tf"])
                except (TypeError, ValueError):
                    v = None
                if v not in (5, 15):
                    raise ValueError("Telegram timeframe must be 5 or 15 minutes")
                s["tg_tf"] = v
            if "tf" in d:
                tf = self._tf_ok(d["tf"], default=None)
                if tf is None:
                    raise ValueError("timeframe must be 1, 3, 5 or 15 minutes")
                if tf != s["tf"]:
                    self._apply_tf(tf)
            if str(d.get("product", "")).upper() in PRODUCTS:
                s["product"] = str(d["product"]).upper()
            if str(d.get("trail_mode", "")).lower() in TRAIL_MODES:
                s["trail_mode"] = str(d["trail_mode"]).lower()
            if str(d.get("sl_type", "")).lower() in SL_TYPES:
                s["sl_type"] = str(d["sl_type"]).lower()
            for k in ENGINE_KEYS:                      # live-applied (capital: next reset)
                self.engine.s[k] = s[k]
            try:
                with open(self._path, "w") as f:
                    json.dump(s, f)
            except Exception:
                log.exception("save india settings")
            return dict(s)

    # ---- option chain / pins / reports --------------------------------
    def chain(self, underlying, expiry=None, width=10):
        with self.lock:
            exp = date.fromisoformat(expiry) if expiry else None
            key = (str(underlying).upper(), expiry)
            try:
                out = _ser(india_chain.build_chain(self.engine, underlying, exp, width))
                self._chain_last[key] = out
                return out
            except india_broker.BrokerError as e:      # never a raw HTTP 500: show the last chain, or an empty one
                last = self._chain_last.get(key)
                if last:
                    return {**last, "stale": True, "error": str(e)[:160]}
                u = str(underlying).upper()
                return _ser({"underlying": u, "spot": 0.0, "atm": 0, "step": 0, "expiry": None,
                             "trade_expiry": None, "expiries": [], "lot": None, "budget": 0.0, "rows": [],
                             "has_oi": False, "pins": [], "day_mode": self.engine.day_mode,
                             "default_mode": {"mode": "ITM", "depth": int(self.settings["itm_depth"])},
                             "status": india_chain.market_status(self.provider.now()),
                             "as_on": self.provider.now(), "stale": True, "error": str(e)[:160]})

    def set_pin(self, underlying, side, spec):
        with self.lock:
            self.engine.set_pin(underlying, side, spec)
            return self._pins()

    def clear_pins(self, underlying=None, side=None):
        with self.lock:
            self.engine.clear_pins(underlying, side)
            return self._pins()

    def set_day_mode(self, mode, depth=1):
        with self.lock:
            self.engine.set_day_mode(mode, depth)
            return {"day_mode": self.engine.day_mode}

    def _pins(self):
        return [{"underlying": k[0], "side": k[1], **v} for k, v in self.engine.pins.items()]

    def _period_start(self, period):
        """'today' | '7d' | '30d' -> ISO start date, counted on the engine's own clock (not the phone's)."""
        today = self.provider.now().date()
        days = {"today": 0, "7d": 6, "30d": 29}.get(str(period or "").lower())
        return None if days is None else (today - timedelta(days=days)).isoformat()

    def report(self, start=None, end=None, underlying=None, period=None):
        with self.lock:
            if period and not start:
                start = self._period_start(period)
            tr = india_reports.filter_trades(self.engine.closed, start, end, underlying)
            cap = float(self.settings["capital"])
            return _ser({"totals": india_reports.totals(tr),
                         "daily": india_reports.daily_summary(tr),
                         "equity": india_reports.equity_curve(tr, cap),
                         "breakdown": india_reports.breakdown(tr)[:15],
                         "what_if": self.what_if(tr),
                         "trades": list(reversed(tr))[:200]})

    def trades_csv(self, start=None, end=None, underlying=None, period=None):
        with self.lock:
            if period and not start:
                start = self._period_start(period)
            return india_reports.trades_csv(
                india_reports.filter_trades(self.engine.closed, start, end, underlying))

    def status(self):
        with self.lock:
            p = self.provider
            return _ser({
                "running": self.running, "finished": self.finished,
                "source": self.settings["source"],
                "source_label": ("LIVE data: " + p.label + " (paper trades only)") if self.live
                else "DEMO replay of past trading days (synthetic candles) - no broker connected",
                "broker_connected": self.live is not None, "broker_error": self.broker_error,
                "feed": (p.feed_mode() if self.live is not None and hasattr(p, "feed_mode") else None),
                "feed_age_ms": self._feed_age_ms() if self.live is not None else None,
                "sl_check": {"mode": "tick" if (self.live is not None and self._feed_age_ms() is not None
                                                 and self._feed_age_ms() < 5000) else "poll",
                             "fast_checks": self._fast_n, "poll_sec": float(self.settings["poll_sec"])},
                "trading_mode": "PAPER",
                "trading_mode_note": "Paper bot: trades use your paper capital, even with 0 broker balance. Real orders are not enabled.",
                "feed_api": (p.client.limit_info() if self.live is not None and hasattr(getattr(p, "client", None), "limit_info") else None),
                "clock": p.now(), "progress": None if self.live else [p.i, p.n],
                "spots": {u: self._spot(u) for u in ALL_UNDERLYINGS},
                "ticker": india_chain.ticker(self.engine, ALL_UNDERLYINGS),
                "market": india_chain.market_status(p.now()),
                "market_note": cal.market_note(p.now().date()),
                "holidays": cal.upcoming_holidays(p.now().date()),
                "tf": int(self.settings["tf"]), "tf_choices": list(TF_CHOICES),
                "today": p.now().date().isoformat(),
                "periods": india_reports.period_summary(self.engine.closed, p.now().date()),
                "summary": self.engine.summary(), "pins": self._pins(),
                "day_mode": self.engine.day_mode,
                "settings": dict(self.settings), "stats": self.engine.stats(),
                "events": list(self.events)[:15]})

    def _spot(self, u):
        try:
            return round(self.provider.get_spot(u), 2)
        except Exception as e:          # live feed hiccup must not break the status call
            self.broker_error = f"{u} spot: {e}"[:200]
            return None

    def candles(self, underlying, limit=150, tf=None):
        """Chart data: closed candles + the forming one + indicator series + open-trade levels.
        tf = chart timeframe (1/3/5/15) - independent of the timeframe the bot trades on.
        Times are sent as IST text (lbl/day) and epoch seconds, so the app never converts time zones."""
        u = underlying.upper()
        if u not in ALL_UNDERLYINGS:
            raise ValueError("unknown underlying")
        with self.lock:
            pv = self.provider
            tf = self._tf_ok(tf, default=int(self.settings["tf"]))
            warm = 250                                    # extra history so SD/EMA match the strategy
            try:
                cs = list(pv.get_candles(u, tf, limit + warm))
                last = pv.get_forming_candle(u, tf)
            except Exception as e:                       # live feed hiccup: show what we have
                self.broker_error = f"{u} candles: {e}"[:200]
                cs, last = [], None
            n_closed, forming = len(cs), False
            if last and (not cs or last["t"] > cs[-1]["t"]):
                cs.append(last)
                forming = True
            cs, ics = self._pack(cs, n_closed, limit)
            lv = [{"id": x["id"], "action": x["action"], "entry": x["entry_spot"], "sl": x["sl_spot"],
                   "tps": list(x["tps"]), "target": x.get("target"), "tp_hit": x.get("tp_hit", 0)}
                  for x in self.engine.open.values() if x["underlying"] == u]
            out = {"underlying": u, "tf": tf, "bot_tf": int(self.settings["tf"]), "tf_choices": list(TF_CHOICES),
                   "live": self.live is not None, "forming": forming, "indicators": ics, "levels": lv,
                   "feed_mode": (self.provider.feed_mode()["mode"] if self.live is not None and hasattr(self.provider, "feed_mode") else None),
                   "candles": self._candle_rows(cs, ics)}
            return out

    def _pack(self, cs, n_closed, limit):
        """Indicators over warm-up + shown candles, then trim the warm-up part."""
        ics = ind.compute(cs, n_closed, lookback=200)
        skip = max(0, len(cs) - limit)
        for grp in ("sd", "ema", "tsi", "z"):
            for k, v in ics[grp].items():
                if isinstance(v, list):
                    ics[grp][k] = v[skip:]
        ics["markers"] = [{"i": m["i"] - skip, "side": m["side"]} for m in ics["markers"] if m["i"] >= skip]
        return cs[skip:], ics

    @staticmethod
    def _candle_rows(cs, ics):
        """Chart rows. `x50` = 1 when the candle crossed EMA50 (the app paints it black)."""
        hit = {m["i"] for m in ics["markers"]}
        return [{"ts": int(c["t"].timestamp()), "o": round(c["o"], 2), "h": round(c["h"], 2),
                 "l": round(c["l"], 2), "c": round(c["c"], 2), "x50": 1 if i in hit else 0,
                 "lbl": c["t"].astimezone(IST).strftime("%H:%M"),
                 "day": c["t"].astimezone(IST).strftime("%d %b"),
                 "date": c["t"].astimezone(IST).date().isoformat()} for i, c in enumerate(cs)]

    def option_candles(self, key, limit=200, tf=None):
        """Chart of one option contract (key from the chain) with the same indicators as the index chart."""
        with self.lock:
            pv = self.provider
            tf = self._tf_ok(tf, default=int(self.settings["tf"]))
            c = None
            for u in ALL_UNDERLYINGS:
                try:
                    c = next((x for x in pv.get_contracts(u) if x["key"] == key), None)
                except Exception:
                    c = None
                if c:
                    break
            if c is None:
                raise ValueError("contract not found - open the chain again")
            warm, source, err = 250, "MODEL", ""
            if hasattr(pv, "get_option_candles"):
                try:
                    cs, source = pv.get_option_candles(c, tf, limit + warm)
                except Exception as e:
                    cs, err = [], str(e)[:200]
            else:                                   # demo / Tradebulls: premium modelled from the index candles
                sp = list(pv.get_candles(c["underlying"], tf, limit + warm))
                last = pv.get_forming_candle(c["underlying"], tf)
                if last and (not sp or last["t"] > sp[-1]["t"]):
                    sp.append(last)

                def px(spot, t):
                    exp = datetime.combine(c["expiry"], datetime.min.time().replace(hour=15, minute=30), IST)
                    yrs = max((exp - t).total_seconds(), 60) / (365 * 86400)
                    return india_pricing.bs_price(spot, c["strike"], yrs, 0.15, c["type"])
                cs = []
                for k in sp:
                    vals = [px(k[f], k["t"]) for f in ("o", "h", "l", "c")]
                    cs.append(dict(t=k["t"], o=vals[0], h=max(vals), l=min(vals), c=vals[3], v=0))
            forming = bool(cs) and cs[-1]["t"] + timedelta(minutes=tf) > pv.now()
            n_closed = len(cs) - (1 if forming else 0)
            cs, ics = self._pack(cs, n_closed, limit)
            return {"key": key, "underlying": c["underlying"], "strike": c["strike"], "type": c["type"],
                    "expiry": c["expiry"].isoformat(), "tf": tf, "bot_tf": int(self.settings["tf"]),
                    "tf_choices": list(TF_CHOICES), "live": self.live is not None, "forming": forming,
                    "source": source, "error": err, "indicators": ics, "levels": [],
                    "candles": self._candle_rows(cs, ics)}

    def positions(self):
        with self.lock:
            out = []
            for pos in self.engine.open.values():
                out.append(_ser({**pos, **self.engine.mark(pos)}))
            return out

    def stats(self):
        """Numbers for the Stats tab (india_stats.py)."""
        with self.lock:
            closed = list(self.engine.closed)
            capital = float(self.settings["capital"])
        try:
            from . import india_stats
        except ImportError:
            import india_stats
        return india_stats.build(closed, capital)

    def doctor(self):
        """Strategy Doctor report for India trades (india_doctor.py) - read-only."""
        with self.lock:
            closed = list(self.engine.closed)
        try:
            from . import india_doctor
        except ImportError:
            import india_doctor
        return india_doctor.build(closed)

    def trades(self, limit=100):
        with self.lock:
            return _ser(list(reversed(self.engine.closed[-limit:])))


_rt = None
_rt_lock = threading.Lock()


def get_runtime(data_dir):
    global _rt
    with _rt_lock:
        if _rt is None:
            os.makedirs(data_dir, exist_ok=True)
            _rt = IndiaRuntime(data_dir)
        return _rt

"""Part 70 (V2-S0-MOCK): the two live Binance clients tested ONLY with fakes. The network is BLOCKED for the whole file: any real connection attempt
is recorded and fails the last test. No key is real, no order is real. NOT RUN in the delivery (owner rule).  Run: python3 test/test_v2_live_clients_mock.py
Covers: recovered_bot/binance_trader.py (the bot's live client) and recovered_bot/ai_live_client.py (the AI account client).
Characterizes today's behaviour only; it changes no trading code."""
import hashlib
import hmac
import json
import os
import socket
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import requests
from recovered_bot import ai_live_client as CL
from recovered_bot import binance_trader as BT

BLOCKED, _SAVED = [], {}


def _deny(*a, **k):
    BLOCKED.append(a[:2] if a else "network call")
    raise OSError("network blocked by test_v2_live_clients_mock")


def setUpModule():
    for obj, name in ((socket.socket, "connect"), (socket, "create_connection"), (socket, "getaddrinfo"), (requests.sessions.Session, "request"), (requests, "request")):
        _SAVED[(id(obj), name)] = (obj, name, getattr(obj, name))
        setattr(obj, name, _deny)


def tearDownModule():
    for obj, name, orig in _SAVED.values():
        setattr(obj, name, orig)


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body if body is not None else {}
        self.text = json.dumps(self._b)

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, resp=None):
        self.calls, self.resp = [], resp or FakeResp()

    def request(self, method, url, headers=None, timeout=None):
        self.calls.append((method, url, dict(headers or {}), timeout))
        return self.resp


class TraderTest(unittest.TestCase):
    def setUp(self):
        self.s = FakeSession()
        self._keep = (BT.get_session, BT.settings_store.get_all, BT.status.add_api_error)
        BT.get_session = lambda: self.s
        BT.settings_store.get_all = lambda: {"binance_api_key": "KEY123", "binance_api_secret": "SECRET456"}
        BT.status.add_api_error = lambda *a, **k: None

    def tearDown(self):
        BT.get_session, BT.settings_store.get_all, BT.status.add_api_error = self._keep

    def test_orders_are_refused_without_confirm_and_send_nothing(self):
        for fn, args in ((BT.place_market_order, ("BTCUSDT", "BUY", 1)), (BT.set_leverage, ("BTCUSDT", 10)), (BT.cancel_all_open_orders, ("BTCUSDT",))):
            with self.assertRaises(ValueError):
                fn(*args)
        self.assertEqual(self.s.calls, [])

    def test_missing_keys_stop_before_any_request(self):
        BT.settings_store.get_all = lambda: {}
        with self.assertRaises(BT.BinanceAPIError):
            BT._signed_request("GET", "/fapi/v2/account")
        self.assertEqual(self.s.calls, [])

    def test_signed_request_is_signed_and_hides_the_secret(self):
        BT.place_market_order("BTCUSDT", "BUY", 1, confirm=True)
        method, url, headers, _ = self.s.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.startswith(BT.BASE_URL + "/fapi/v1/order?"))
        qs, sig = url.split("?", 1)[1].rsplit("&signature=", 1)
        self.assertEqual(sig, hmac.new(b"SECRET456", qs.encode(), hashlib.sha256).hexdigest())
        self.assertNotIn("SECRET456", url)
        self.assertEqual(headers, {"X-MBX-APIKEY": "KEY123"})
        q = parse_qs(urlparse(url).query)
        self.assertIn("timestamp", q)
        self.assertEqual(q["type"], ["MARKET"])

    def test_a_refused_order_raises_binance_error(self):
        self.s.resp = FakeResp(400, {"code": -2019, "msg": "Margin is insufficient."})
        with self.assertRaises(BT.BinanceAPIError):
            BT.place_market_order("BTCUSDT", "BUY", 1, confirm=True)

    def test_query_string_is_stable(self):
        self.assertEqual(BT._sorted_urlencode({"b": 1, "a": 2}), BT._sorted_urlencode({"a": 2, "b": 1}))

    def test_hosts_are_only_the_two_binance_futures_hosts(self):
        self.assertIn(BT.BASE_URL, ("https://fapi.binance.com", "https://testnet.binancefuture.com"))
        self.assertEqual(CL.BASE, "https://fapi.binance.com")


class AiClientTest(unittest.TestCase):
    def make(self, resp=(200, "{}"), creds=("K", "SECRET456"), raises=None):
        calls = []

        def transport(method, url, headers, timeout):
            calls.append((method, url, dict(headers)))
            if raises:
                raise raises
            return resp
        self._keep = CL._default_transport
        CL._default_transport = lambda *a: self.fail("the default (real network) transport was used")
        return CL.Client(creds=lambda: creds, transport=transport), calls

    def tearDown(self):
        if hasattr(self, "_keep"):
            CL._default_transport = self._keep

    def test_market_order_is_signed_and_uses_the_given_transport(self):
        c, calls = self.make()
        c.market("BTCUSDT", "BUY", 1)
        method, url, headers = calls[0]
        qs, sig = url.split("?", 1)[1].rsplit("&signature=", 1)
        self.assertEqual((method, headers), ("POST", {"X-MBX-APIKEY": "K"}))
        self.assertEqual(sig, hmac.new(b"SECRET456", qs.encode(), hashlib.sha256).hexdigest())
        self.assertNotIn("SECRET456", url)

    def test_no_key_stops_before_the_transport(self):
        c, calls = self.make(creds=("", ""))
        with self.assertRaises(CL.ApiError):
            c.market("BTCUSDT", "BUY", 1)
        self.assertEqual(calls, [])

    def test_network_failure_becomes_api_error_code_0(self):
        c, _ = self.make(raises=OSError("down"))
        with self.assertRaises(CL.ApiError) as cm:
            c.market("BTCUSDT", "BUY", 1)
        self.assertEqual(cm.exception.code, 0)

    def test_refused_order_keeps_the_binance_code(self):
        c, _ = self.make(resp=(400, json.dumps({"code": -2019, "msg": "Margin is insufficient."})))
        with self.assertRaises(CL.ApiError) as cm:
            c.market("BTCUSDT", "BUY", 1)
        self.assertEqual((cm.exception.code, cm.exception.status), (-2019, 400))


class ZLastTest(unittest.TestCase):
    def test_zz_no_real_network_attempt_was_made(self):
        self.assertEqual(BLOCKED, [], "a test tried to reach the real network: %r" % (BLOCKED,))


if __name__ == "__main__":
    unittest.main()

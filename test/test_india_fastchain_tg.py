"""India: contract list saved on disk, chain warms outside the lock, Telegram token check + demo signal."""
import os
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from recovered_bot import fyers_provider as FP          # noqa: E402
from recovered_bot import india_runtime as R            # noqa: E402
from recovered_bot import india_telegram as T           # noqa: E402

MASTER = ("101,NIFTY 20 Dec 30 23000 CE,14,65,0.05,x,s,2026-10-16,1792486200,NSE:NIFTY30D2023000CE,10,11\n"
          "102,NIFTY 20 Dec 30 23000 PE,14,65,0.05,x,s,2026-10-16,1792486200,NSE:NIFTY30D2023000PE,10,11\n")


class FakeClient:
    token = "t"
    calls = 0

    def symbol_master(self, seg="NSE_FO"):
        FakeClient.calls += 1
        return MASTER


def test_master_saved_on_disk():
    d = tempfile.mkdtemp()
    p1 = FP.FyersProvider(client=FakeClient(), data_dir=d)
    p1._load_master()
    assert FakeClient.calls == 1 and p1._master["NIFTY"]
    assert os.path.exists(os.path.join(d, "fyers_master.json"))
    p2 = FP.FyersProvider(client=FakeClient(), data_dir=d)      # "restart": no second download
    p2._load_master()
    assert FakeClient.calls == 1, "contract list was downloaded again after restart"
    assert p2._master["NIFTY"][0]["expiry"] == date(2030, 12, 20)
    assert "contracts" in p2.timing


def test_chain_has_timing_and_no_lock_during_warm():
    d = tempfile.mkdtemp()
    rt = R.IndiaRuntime(d) if hasattr(R, "IndiaRuntime") else R.get_runtime(d)
    seen = {}
    orig = rt._warm_chain

    def spy(*a, **k):
        seen["locked"] = rt.lock._is_owned()
        return orig(*a, **k)

    rt._warm_chain = spy
    out = rt.chain("NIFTY")
    assert seen["locked"] is False, "chain warmed the broker while holding the runtime lock"
    assert "timing" in out and out["rows"]


def test_token_check_and_demo(monkeypatch=None):
    d = tempfile.mkdtemp()
    rt = R.IndiaRuntime(d) if hasattr(R, "IndiaRuntime") else R.get_runtime(d)
    tg = rt.tg
    sent = []

    class Resp:
        def __init__(self, code, js=None, text=""):
            self.status_code, self._js, self.text = code, js or {}, text

        def json(self):
            return self._js

    real_get, real_post = T.requests.get, T.requests.post
    try:
        T.requests.get = lambda url, **k: Resp(404, text="Not Found") if "BAD" in url else Resp(200, {"ok": True, "result": {"username": "ooowlbot"}})
        T.requests.post = lambda url, data=None, **k: (sent.append(data["text"]) or Resp(200))
        tg.save_creds(bot_token="BAD:TOKEN")
        assert tg.info()["token_check"]["ok"] is False and "wrong" in tg.info()["token_check"]["text"]
        assert "BAD:TOKEN" not in str(tg.info()["token_check"])
        tg.save_creds(bot_token="1:GOOD", chat_id="55")
        assert tg.info()["token_check"] == {"ok": True, "text": "Token OK: @ooowlbot"}
        ok, _ = tg.send_demo_signal()
        assert ok and sent and sent[-1].startswith("🧪 DEMO") and "TP4" in sent[-1] and "Stop Loss" in sent[-1]
        assert "after close" not in sent[-1] and "Option" not in sent[-1] and "Faisal sir" in sent[-1]
        tg.forget()
        assert tg.info()["token_check"]["ok"] is None
    finally:
        T.requests.get, T.requests.post = real_get, real_post


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)

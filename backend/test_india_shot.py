"""India Telegram signal photo: exactly ONE per signal, and a photo problem never stops the signal card."""
import json, os, random, sys, tempfile, threading, types
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "recovered_bot"))
sys.path.insert(0, os.path.dirname(__file__))


def _candles(opened, n=300, tf=5):
    random.seed(7)
    out, px = [], 24000.0
    for i in range(n):
        t = opened - timedelta(minutes=tf * (n - 1 - i))
        o = px
        c = o + random.uniform(-14, 14)
        out.append({"t": t, "o": o, "h": max(o, c) + random.uniform(0, 6), "l": min(o, c) - random.uniform(0, 6), "c": c, "v": 1000})
        px = c
    return out


def _sig(px):
    return types.SimpleNamespace(action="BUY", entry_price=px, stop_loss=px - 20, tp1=px + 10, tp2=px + 20, tp3=px + 30, tp4=px + 40)


def _tg(tmp, cs, sig):
    from recovered_bot import india_telegram as T
    live = types.SimpleNamespace(name="fyers", get_candles=lambda u, tf, n: list(cs))
    rt = types.SimpleNamespace(settings={"tg_enabled": True, "underlyings": ["NIFTY"], "itm_depth": 1, "tf": 5, "tg_tf": 5}, live=live)
    tg = T.IndiaTelegram.__new__(T.IndiaTelegram)
    tg.rt, tg.dir = rt, tmp
    tg._state_path = os.path.join(tmp, "india_telegram_state.json")
    tg._lock = threading.Lock()
    tg.strategy = types.SimpleNamespace(generate_signal=lambda c, u, tf_min=5: sig)
    tg._checked, tg._try_at = {}, {}
    tg.last = {"ok": None, "error": "", "at": None, "kind": "", "signal_at": None}
    tg.token_check, tg.note = {"ok": None, "text": ""}, ""
    tg._wake = threading.Event()
    tg.state = {"count": 0, "sent": [], "shots": []}
    tg._creds = lambda: ("TOKEN123", "42")
    tg.remind_login = lambda now=None: False
    tg.cards = []
    tg._post = lambda text, token, chat, kind: (tg.cards.append(text) or (True, "sent"))
    type(tg).enabled = property(lambda self: True)
    type(tg).tf = property(lambda self: 5)
    return tg, T


def _now():
    from recovered_bot.india_data import IST
    return datetime(2026, 10, 27, 11, 0, 30, tzinfo=IST)     # Tuesday, candle 10:55-11:00 just closed


def _wait_shots():
    for t in threading.enumerate():
        if t.name == "india_shot":
            t.join(10)


def test_claim_only_first_time():
    from recovered_bot import india_shot as S
    st, saves = {"shots": []}, []
    assert S.claim(st, threading.Lock(), lambda: saves.append(1), "a") is True
    assert S.claim(st, threading.Lock(), lambda: saves.append(1), "a") is False
    assert S.claim(st, threading.Lock(), lambda: saves.append(1), "b") is True
    assert len(saves) == 2 and st["shots"] == ["a", "b"]


def test_real_chart_is_a_png():
    from recovered_bot import india_shot as S
    now = _now()
    opened = now.replace(minute=55, second=0) - timedelta(hours=0)
    opened = now - timedelta(minutes=5, seconds=30)
    cs = _candles(opened)
    png = S.make_png("NIFTY", 5, cs, _sig(cs[-1]["c"]), opened)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 20000


def test_one_card_one_photo_even_if_signal_repeats():
    from recovered_bot import india_shot as S
    now = _now()
    opened = now - timedelta(minutes=5, seconds=30)
    cs = _candles(opened)
    sig = _sig(cs[-1]["c"])
    tmp = tempfile.mkdtemp()
    tg, T = _tg(tmp, cs, sig)
    tg._save_state = lambda: T.IndiaTelegram._save_state(tg)
    photos, seen_on_disk = [], []
    orig = S.post_photo
    def fake(png, cap, token, chat):
        seen_on_disk.append(json.load(open(tg._state_path))["shots"])     # id must already be on disk
        photos.append((png[:4], cap, token, chat))
        return True
    S.post_photo = fake
    try:
        tg.tick(now)
        _wait_shots()
        tg._checked.clear(); tg.tick(now)             # same candle again (e.g. restart of the watcher loop)
        tg._checked.clear(); tg.state["sent"].clear() # even if the card list forgot it, the photo list must not
        tg.tick(now)
        _wait_shots()
    finally:
        S.post_photo = orig
    assert len(photos) == 1, photos
    assert photos[0][0] == b"\x89PNG" and photos[0][2:] == ("TOKEN123", "42")
    assert len(seen_on_disk[0]) == 1
    assert len(tg.cards) == 2                            # card list was cleared on purpose in the 3rd tick
    # after a restart the saved ids still block a second photo
    st = json.load(open(tg._state_path))
    assert S.claim(st, threading.Lock(), lambda: None, st["shots"][0]) is False


def test_photo_failure_never_stops_the_card():
    from recovered_bot import india_shot as S
    now = _now()
    opened = now - timedelta(minutes=5, seconds=30)
    cs = _candles(opened)
    tg, T = _tg(tempfile.mkdtemp(), cs, _sig(cs[-1]["c"]))
    tg._save_state = lambda: None
    orig = S.make_png
    def boom(*a, **k):
        raise RuntimeError("chart exploded")
    S.make_png = boom
    try:
        sent = tg.tick(now)
        _wait_shots()
    finally:
        S.make_png = orig
    assert len(sent) == 1 and len(tg.cards) == 1        # card went out, no exception


def test_hook_itself_failing_never_stops_the_card():
    from recovered_bot import india_shot as S
    now = _now()
    opened = now - timedelta(minutes=5, seconds=30)
    cs = _candles(opened)
    tg, T = _tg(tempfile.mkdtemp(), cs, _sig(cs[-1]["c"]))
    tg._save_state = lambda: None
    orig = S.send_async
    def boom(*a, **k):
        raise RuntimeError("hook exploded")
    S.send_async = boom
    try:
        sent = tg.tick(now)
    finally:
        S.send_async = orig
    assert len(sent) == 1 and len(tg.cards) == 1


def test_send_error_is_quiet_and_hides_token():
    from recovered_bot import india_shot as S
    orig = S.requests.post
    def bad(*a, **k):
        raise RuntimeError("cannot reach https://api.telegram.org/botSECRET/sendPhoto")
    S.requests.post = bad
    try:
        assert S.post_photo(b"x", "cap", "SECRET", "42") is False
    finally:
        S.requests.post = orig


def test_no_token_means_no_photo():
    from recovered_bot import india_shot as S
    st = {"shots": []}
    assert S.send_async(st, threading.Lock(), lambda: None, "x", "NIFTY", 5, [], None, None, "", "") is False
    assert st["shots"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

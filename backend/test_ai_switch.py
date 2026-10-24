"""90% switch: a key that used 90% of its daily budget goes to the end of the line; real 429 still pauses a key."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import ai_vision, settings_store  # noqa: E402


def _setup(n_ok_main):
    settings_store.update(ai_api_key="k-main", ai_provider="gemini", ai2_api_key="k-two", ai2_provider="groq",
                          ai_switch_pct=90, ai_slot_day_limit=100)
    ai_vision._mon[:] = [(time.time(), "main", "ok", 1.0) for _ in range(n_ok_main)]
    ai_vision._pause.clear()


def test_below_90_keeps_normal_order():
    _setup(50)
    sl = {s["slot"]: s for s in ai_vision._slots()}
    assert not ai_vision._near_limit(sl["main"])


def test_at_90_main_goes_last():
    _setup(90)
    sl = {s["slot"]: s for s in ai_vision._slots()}
    assert ai_vision._near_limit(sl["main"])
    assert not ai_vision._near_limit(sl["backup"])


def test_call_order_uses_second_key_first():
    _setup(95)
    order = []

    def fake(sl, system, text, b64):
        order.append(sl["slot"])
        return '{"ok":1}', None, "m"

    ai_vision._try_gemini = fake
    ai_vision._try_oai = fake
    for _ in range(4):
        out, err = ai_vision._call_ai("s", "t")
        assert out and not err
    assert order and all(x == "backup" for x in order), order


def test_last_resort_when_second_is_paused():
    _setup(95)
    ai_vision._pause["backup:" + ai_vision._slot_models({"slot": "backup", "provider": "groq", "model": "", "auto": ""})[0]] = time.time() + 600
    order = []

    def fake(sl, system, text, b64):
        order.append(sl["slot"])
        return '{"ok":1}', None, "m"

    ai_vision._try_gemini = fake
    out, err = ai_vision._call_ai("s", "t")
    assert out and order == ["main"], order


def test_monitor_shows_limit():
    _setup(95)
    m = ai_vision.monitor()
    row = [x for x in m["slots"] if x["slot"] == "main"][0]
    assert row["day_limit"] == 100 and row["near_limit"] is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

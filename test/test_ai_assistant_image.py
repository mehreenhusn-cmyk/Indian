"""Assistant picture + mode test (no network): the picture really reaches the model in each provider's format, chat history keeps
clean text, unsupported providers get an honest error, and the mode picks its own brief.
Run: python3 test/test_ai_assistant_image.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_assistant as A, ai_app_brief as B, settings_store

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
sent = {}

class R:
    status_code = 200
    def __init__(self, data): self._d = data
    def json(self): return self._d

def fake_post(url, **kw):
    sent["url"], sent["json"] = url, kw.get("json")
    if "anthropic" in url:
        return R({"content": [{"type": "text", "text": "ok-claude"}]})
    if "generativelanguage" in url:
        return R({"candidates": [{"content": {"parts": [{"text": "ok-gemini"}]}}]})
    return R({"choices": [{"message": {"content": "ok-openai"}}]})

A.requests.post = fake_post
_store = {"ai_enabled": True, "ai_api_key": "k", "ai_provider": "openai"}
settings_store.get_all = lambda: dict(_store)
import recovered_bot.ai_keyid as K
K.guess = lambda k: (None, False)
A._build_context = lambda: "CTX"

def run(provider, mode=None, img=PNG, msg="how is this screen?"):
    _store["ai_provider"] = provider
    return A.ask(msg, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], mode, img)

# openai: image_url part
r = run("openai"); assert r["ok"] and r["reply"].startswith("ok-openai"), r
last = sent["json"]["messages"][-1]["content"]
assert last[1]["type"] == "image_url" and last[1]["image_url"]["url"].startswith("data:image/png;base64,"), last
# anthropic: image block, roles alternate
r = run("anthropic"); assert r["ok"], r
blocks = sent["json"]["messages"][-1]["content"]
assert blocks[1]["type"] == "image" and blocks[1]["source"]["media_type"] == "image/png", blocks
# gemini: inline_data
import recovered_bot.ai_assistant as AA
r = run("gemini"); assert r["ok"], r
parts = sent["json"]["contents"][-1]["parts"]
assert "inline_data" in parts[1], parts
# provider without picture support -> honest error, no call
sent.clear(); r = run("groq"); assert not r["ok"] and "cannot read pictures" in r["error"] and not sent, r
# too big
r = run("openai", img="A" * 7_000_000); assert not r["ok"] and "too big" in r["error"], r
# no picture: plain string content, still works
r = run("openai", img=None); assert r["ok"] and isinstance(sent["json"]["messages"][-1]["content"], str)
# modes pick their own brief
assert "MODE=backend" in B.for_mode("backend") and "MODE=app_ui" in B.for_mode("app_ui") and "MODE=" not in B.for_mode("general")
sys_txt = sent["json"]["messages"][0]["content"]
run("openai", mode="backend", img=None); assert "MODE=backend" in sent["json"]["messages"][0]["content"]
print("PASS test_ai_assistant_image")

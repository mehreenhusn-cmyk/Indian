"""Claude as AI-assistant provider, on a FAKE Anthropic endpoint. Run: python3 test/test_ai_claude_provider.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_assistant as A

sent = []


class R:
    def __init__(self, st, body):
        self.status_code, self._b, self.text = st, body, str(body)

    def json(self):
        return self._b


def post(url, headers=None, json=None, timeout=None):
    sent.append((url, headers, json))
    if json["model"] == "retired-model":
        return R(404, {"error": {"message": "model not found"}})
    if headers["x-api-key"] != "sk-ant-good":
        return R(401, {"error": {"message": "invalid x-api-key"}})
    return R(200, {"content": [{"type": "text", "text": "Hello "}, {"type": "text", "text": "trader"}]})


A.requests.post = post
msgs = [{"role": "system", "content": "SYS"}, {"role": "assistant", "content": "stray"},
        {"role": "user", "content": "a"}, {"role": "user", "content": "b"}, {"role": "assistant", "content": "c"},
        {"role": "user", "content": "d"}]
system, out = A._anthropic_messages(msgs)
assert system == "SYS" and [m["role"] for m in out] == ["user", "assistant", "user"] and out[0]["content"] == "a\n\nb"

reply, err = A._call_anthropic("sk-ant-good", msgs, "retired-model")      # 404 -> falls to the next model
assert reply == "Hello trader" and err is None, (reply, err)
assert sent[-1][0] == A._ANTHROPIC_URL and sent[-1][1]["anthropic-version"] and sent[-1][2]["system"] == "SYS"
assert sent[-1][2]["model"] == A._ANTHROPIC_MODELS[0] and len(sent) == 2
reply, err = A._call_anthropic("bad", msgs)
assert reply is None and "401" in err and "invalid" in err
print("claude provider test OK")

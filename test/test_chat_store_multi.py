"""Multi-chat store: create / rename / delete / modes / clean history. Run: python3 test/test_chat_store_multi.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_chat_store as S

d = tempfile.mkdtemp()
S.init(os.path.join(d, "chats.json"))
a = S.create_chat("backend", "Speed")
b = S.create_chat("app_ui", "")
ids = [c["id"] for c in S.list_chats()["chats"]]
assert a["id"] in ids and b["id"] in ids, ids
S.append_turn("why slow?", "because X", a["id"])
S.append_turn("[photo] (screenshot)", "looks fine", b["id"])
assert [m["content"] for m in S.get_history(10, a["id"])] == ["why slow?", "because X"]
assert "[mode=" not in str(S.get_history(10, a["id"]))
assert S.get_mode(a["id"]) == "backend" and S.get_mode(b["id"]) == "app_ui"
S.rename_chat(a["id"], "Renamed")
assert any(c["title"] == "Renamed" for c in S.list_chats()["chats"])
S.set_active(b["id"]); assert S.list_chats()["active"] == b["id"]
S.delete_chat(a["id"]); assert a["id"] not in [c["id"] for c in S.list_chats()["chats"]]
S.clear(b["id"]); assert S.get_history(10, b["id"]) == []
print("PASS test_chat_store_multi")

"""ai_chat_store.py - multi-conversation storage for the AI Assistant.

Each chat has:
  id, title, mode (trades | backend | app_ui | general), messages[], updated_at

Modes keep context focused:
  trades   - P&L, positions, strategy questions
  backend  - freezes, REST, data leak, Termux (uses ai_health)
  app_ui   - UI/UX trends, screenshots, app behaviour (uses ai_app_brief)
  general  - default mixed chat

API surface used by api_server:
  list_chats(), get_chat(id), create_chat(mode, title), rename_chat, delete_chat
  append_turn(chat_id, user, assistant), get_history(chat_id), clear_chat(chat_id)
  active_chat_id / set_active

Backward compatible: old single-list file migrates into one "General" chat.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from . import safe_io

_lock = threading.Lock()
_file = None
_chats = []          # list of chat dicts
_active = None       # chat id
MAX_MESSAGES = 400
MAX_CHATS = 40
MODES = ("trades", "backend", "app_ui", "general")


def init(path):
    global _file
    _file = path
    _load()


def _load():
    global _chats, _active
    if not _file:
        return
    data, _src = safe_io.read_json_safe(_file, "ai chat history")
    if not isinstance(data, dict):
        return
    with _lock:
        # New multi-chat format
        if isinstance(data.get("chats"), list) and data["chats"]:
            _chats = data["chats"]
            _active = data.get("active") or _chats[0].get("id")
            return
        # Legacy single-thread messages -> one chat
        msgs = data.get("messages") or []
        if msgs:
            cid = _new_id()
            _chats = [{
                "id": cid,
                "title": "Previous chat",
                "mode": "general",
                "messages": msgs[-MAX_MESSAGES:],
                "created_at": msgs[0].get("ts") if msgs else time.time(),
                "updated_at": msgs[-1].get("ts") if msgs else time.time(),
            }]
            _active = cid
            _save_unlocked()


def _new_id():
    return uuid.uuid4().hex[:12]


def _save_unlocked():
    if not _file:
        return
    try:
        payload = {"chats": list(_chats), "active": _active}
        safe_io.write_json_atomic(_file, json.dumps(payload))
    except Exception as e:
        print(f"[AIChatStore] save failed: {e}")


def _save():
    with _lock:
        _save_unlocked()


def _find(cid):
    for c in _chats:
        if c.get("id") == cid:
            return c
    return None


def list_chats():
    with _lock:
        rows = []
        for c in sorted(_chats, key=lambda x: x.get("updated_at") or 0, reverse=True):
            rows.append({
                "id": c["id"],
                "title": c.get("title") or "Chat",
                "mode": c.get("mode") or "general",
                "updated_at": c.get("updated_at"),
                "n_messages": len(c.get("messages") or []),
                "active": c["id"] == _active,
            })
        return {"chats": rows, "active": _active}


def get_chat(chat_id):
    with _lock:
        c = _find(chat_id) or (_find(_active) if _active else None)
        if not c and _chats:
            c = _chats[0]
        if not c:
            return {"id": None, "title": "", "mode": "general", "messages": []}
        return {
            "id": c["id"],
            "title": c.get("title") or "Chat",
            "mode": c.get("mode") or "general",
            "messages": list(c.get("messages") or [])[-MAX_MESSAGES:],
            "updated_at": c.get("updated_at"),
        }


def create_chat(mode="general", title=""):
    mode = mode if mode in MODES else "general"
    titles = {
        "trades": "Trades",
        "backend": "Backend & speed",
        "app_ui": "App & UI",
        "general": "New chat",
    }
    with _lock:
        if len(_chats) >= MAX_CHATS:
            # drop oldest inactive
            ordered = sorted(_chats, key=lambda x: x.get("updated_at") or 0)
            for old in ordered:
                if old.get("id") != _active:
                    _chats.remove(old)
                    break
        cid = _new_id()
        now = time.time()
        chat = {
            "id": cid,
            "title": (title or titles.get(mode, "New chat"))[:80],
            "mode": mode,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        _chats.append(chat)
        _active = cid
        _save_unlocked()
        return {"id": cid, "title": chat["title"], "mode": mode}


def rename_chat(chat_id, title):
    with _lock:
        c = _find(chat_id)
        if not c:
            return {"ok": False, "error": "chat not found"}
        c["title"] = str(title or "Chat")[:80]
        c["updated_at"] = time.time()
        _save_unlocked()
        return {"ok": True}


def delete_chat(chat_id):
    global _active
    with _lock:
        c = _find(chat_id)
        if not c:
            return {"ok": False, "error": "chat not found"}
        _chats.remove(c)
        if _active == chat_id:
            _active = _chats[0]["id"] if _chats else None
        _save_unlocked()
        return {"ok": True, "active": _active}


def set_active(chat_id):
    global _active
    with _lock:
        if not _find(chat_id):
            return {"ok": False, "error": "chat not found"}
        _active = chat_id
        _save_unlocked()
        return {"ok": True}


def append_turn(user_message, assistant_reply, chat_id=None):
    global _active
    now = time.time()
    with _lock:
        c = _find(chat_id) if chat_id else None
        if not c:
            c = _find(_active)
        if not c:
            # auto-create
            cid = _new_id()
            c = {
                "id": cid,
                "title": "Chat",
                "mode": "general",
                "messages": [],
                "created_at": now,
                "updated_at": now,
            }
            _chats.append(c)
            _active = cid
        if user_message:
            c["messages"].append({"role": "user", "content": user_message, "ts": now})
        if assistant_reply:
            c["messages"].append({"role": "assistant", "content": assistant_reply, "ts": now})
        # auto-title from first user message
        if (c.get("title") in ("New chat", "Chat", "Previous chat", "Trades", "Backend & speed", "App & UI")
                and user_message and len(c["messages"]) <= 2):
            c["title"] = str(user_message).strip().replace("\n", " ")[:48] or c["title"]
        del c["messages"][:-MAX_MESSAGES]
        c["updated_at"] = now
        _save_unlocked()


def get_history(limit=200, chat_id=None):
    with _lock:
        c = _find(chat_id) if chat_id else _find(_active)
        if not c:
            return []
        return list(c.get("messages") or [])[-limit:]


def get_mode(chat_id=None):
    with _lock:
        c = _find(chat_id) if chat_id else _find(_active)
        return (c.get("mode") if c else None) or "general"


def clear(chat_id=None):
    """Clear messages of one chat (or active). Does not delete the chat."""
    with _lock:
        c = _find(chat_id) if chat_id else _find(_active)
        if not c:
            return
        c["messages"] = []
        c["updated_at"] = time.time()
        _save_unlocked()


# Legacy alias used by older api_server paths
def clear_all():
    clear()

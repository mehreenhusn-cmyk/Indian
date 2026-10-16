"""ai_chat_store.py - persistent storage for the AI Assistant's chat history.

Previously the Flutter screen (ai_assistant_screen.dart) kept the whole
conversation only in its own widget State - closing the app (or even just
navigating away and back) lost it, since the backend (ai_assistant.ask) is
deliberately stateless per-request. This module gives the conversation a
home on disk (same JSON-file-behind-a-lock pattern as settings_store.py/
trade_store.py), so:
  - GET  /api/ai/history        returns the saved conversation on app start
  - POST /api/ai/ask            appends both the user's message and the
                                 assistant's reply here after every turn
  - POST /api/ai/history/clear  lets the user start a fresh conversation

Deliberately dumb and isolated, same spirit as ai_data_logger.py: wrapped in
try/except everywhere so a disk problem here can never break the chat itself
- worst case, history just doesn't persist that turn.
"""
import json
import os
import threading
import time
from . import safe_io

_lock = threading.Lock()
_file = None
_messages = []       # [{"role": "user"/"assistant", "content": str, "ts": float}, ...]
MAX_MESSAGES = 500    # generous cap - a chat screen this size would be unwieldy long before this


def init(path):
    global _file
    _file = path
    _load()


def _load():
    global _messages
    if not _file:
        return
    data, _src = safe_io.read_json_safe(_file, "ai chat history")
    if isinstance(data, dict):
        with _lock:
            _messages = data.get("messages", [])


def _save():
    if not _file:
        return
    try:
        with _lock:
            text = json.dumps({"messages": list(_messages)})
        safe_io.write_json_atomic(_file, text)
    except Exception as e:
        print(f"[AIChatStore] save failed: {e}")


def append_turn(user_message, assistant_reply):
    """Call once per completed ask() round-trip - stores both sides together
    so a crash between the two calls can never leave a dangling one-sided
    entry."""
    now = time.time()
    with _lock:
        if user_message:
            _messages.append({"role": "user", "content": user_message, "ts": now})
        if assistant_reply:
            _messages.append({"role": "assistant", "content": assistant_reply, "ts": now})
        del _messages[:-MAX_MESSAGES]
    _save()


def get_history(limit=200):
    with _lock:
        return list(_messages[-limit:])


def clear():
    with _lock:
        _messages.clear()
    _save()

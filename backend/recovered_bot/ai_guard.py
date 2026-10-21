"""
ai_guard.py - the SCORE LOCK.

Rule (owner's): the Strategy Health score and everything in ai_book.py is for the
OWNER'S EYES ONLY. No AI module may read it, import it, or base a decision on it.
AI modules learn from the raw closed trades and their patterns - nothing else.
The ML shadow log numbers (ai_ml.shadow_*, ai_ml.predict) must not reach the chat
AI either.

How it works: every file in AI_FILES is READ AS TEXT and parsed (never imported),
and these are flagged:
  - any import of ai_book
  - any use of the name/attribute `ai_book` or `_health`
  - any string key "health" (e.g. d["health"], d.get("health"))
  - in the chat-facing files (CHAT_FILES): any use of `shadow_stats` / `predict`
check() -> list of problems ([] = clean). enforce() raises RuntimeError with a loud
message at server start (set env OWL_AI_GUARD=warn to only print it).

Honest limit: a lock written in code cannot stop a person or another AI from editing
this file or the list below. What it does guarantee is that the breach is NOT silent:
the server refuses to start and the CI test (test/test_ai_isolation.py) fails.
"""
import ast
import os

AI_FILES = (
    "ai_stats.py", "ai_miner.py", "ai_assistant.py", "ai_ml.py", "ai_chat_store.py",
    "ai_data_logger.py", "ai_path_logger.py", "ai_sd_tracker.py", "ai_slope_tracker.py", "ai_ind_tracker.py", "ai_level_study.py", "ai_observer.py", "ai_digest.py", "ai_playbook.py", "ai_rules.py",
    "ai_ind_features.py", "ai_shadow_lab.py", "ai_learning.py", "ai_ab_board.py", "ai_reading.py", "ai_desk.py", "ai_coach.py", "ai_pick.py", "ai_vision.py", "ai_vision_lessons.py", "ai_pumpdump.py", "ai_vision_own.py", "ai_vision_exits.py",
)
CHAT_FILES = ("ai_assistant.py", "ai_chat_store.py", "ai_stats.py")   # what the chat AI can see
_FORBIDDEN_NAMES = ("ai_book", "_health")
_CHAT_FORBIDDEN = ("shadow_stats", "predict")


def check_source(src, fname="<src>", chat=False):
    """Problems found in one source text (list of strings)."""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{fname}: cannot parse ({e})"]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[-1] == "ai_book":
                    out.append(f"{fname}:{n.lineno} imports ai_book")
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[-1] == "ai_book" or any(a.name == "ai_book" for a in n.names):
                out.append(f"{fname}:{n.lineno} imports ai_book")
        elif isinstance(n, ast.Name) and n.id in _FORBIDDEN_NAMES:
            out.append(f"{fname}:{n.lineno} uses {n.id}")
        elif isinstance(n, ast.Attribute) and n.attr in _FORBIDDEN_NAMES:
            out.append(f"{fname}:{n.lineno} uses .{n.attr}")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.strip().lower() == "health":
            out.append(f"{fname}:{n.lineno} reads the 'health' score")
        if chat:
            if isinstance(n, ast.Name) and n.id in _CHAT_FORBIDDEN:
                out.append(f"{fname}:{n.lineno} (chat-facing) uses {n.id}")
            elif isinstance(n, ast.Attribute) and n.attr in _CHAT_FORBIDDEN:
                out.append(f"{fname}:{n.lineno} (chat-facing) uses .{n.attr}")
    return out


def check(folder=None):
    """Scan every AI file in `folder` (default: this folder). [] = clean."""
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    problems = []
    for fn in AI_FILES:
        p = os.path.join(folder, fn)
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as fh:
                problems += check_source(fh.read(), fn, chat=fn in CHAT_FILES)
        except Exception as e:
            problems.append(f"{fn}: cannot read ({e})")
    return problems


def enforce():
    """Call once at server start. Raises (server does not start) unless OWL_AI_GUARD=warn."""
    problems = check()
    if not problems:
        return
    msg = ("AI SCORE LOCK BROKEN - the health score / ai_book / ML numbers must stay out of AI files:\n  "
           + "\n  ".join(problems))
    print("\n" + "!" * 70 + "\n" + msg + "\n" + "!" * 70 + "\n")
    if os.environ.get("OWL_AI_GUARD", "").lower() != "warn":
        raise RuntimeError(msg)

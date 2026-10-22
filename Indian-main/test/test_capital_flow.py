"""The real _process_signal TAKE path must go through the capital gate for AI Own (and never for bot signals)."""
import os, sys, inspect
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_vision as V

src = inspect.getsource(V._process_signal)
assert "CAP.gate(sys.modules[__name__]" in src and "tr_new[\"invest\"]" in src
assert "sys" in V.__dict__, "ai_vision must import sys, or the gate call fails silently and trades bypass it"
assert "rec[\"grade\"]" in src and "AC.add(" in src
print("ALL test_capital_flow passed")

fix2 - Strategy Doctor "Loading" hardening (3 changed files + 1 new test)
Copy over the repo (same folder layout), rebuild the app, restart the backend.

1. backend/recovered_bot/strategy_doctor.py  : _num() ignores inf; new _finite() turns any inf/NaN in the report into None; crypto build() returns _finite(rep).
2. backend/recovered_bot/india_doctor.py     : 1 line, same safety net for India.
3. frontend/lib/screens/strategy_doctor_screen.dart (dashboard card only): shows "No answer" + the REAL reason (e.g. HTTP 500) instead of "Loading" for ever.
4. test/test_doctor_finite.py (new): proves a trade holding inf/NaN can no longer break the reply.
Why: one inf/NaN anywhere in the report makes FastAPI answer HTTP 500 -> the app gets nothing -> the card stays on "Loading".
This is the most likely cause, NOT proven on the real trades yet. If the card still says "No answer", read the reason text on the card.
Nothing here touches strategy, trades or any setting.

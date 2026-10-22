"""Read-only bridge: copies live bot signals into the ping tracker (TAKE / SKIP).

For every new Bot 1 signal in owl.db it asks the tracker "what did the ping look
like at that moment?" and records TAKE or SKIP. Later it finds that signal's real
trade result in closed_trades_archive.jsonl, so the Score tab can show
loss avoided vs profit missed.

Opens owl.db READ-ONLY. Never writes to any bot file. Never raises to the caller.
"""
import json
import os
import sqlite3
import time

# ---- constants (starting guesses) ----
POLL_SEC = 5.0
RESULT_CHECK_SEC = 60.0
RESULT_MAX_AGE_SEC = 12 * 3600      # stop looking for a result after this long
ARCHIVE_TAIL_BYTES = 600_000        # only the end of the archive is read
NEAR_BEFORE_SEC = 300               # trade opens right after the signal is saved
NEAR_AFTER_SEC = 1800


def _side(action):
    a = str(action or "").upper()
    if a in ("BUY", "LONG"):
        return "BUY"
    if a in ("SELL", "SHORT"):
        return "SELL"
    return None


class SignalBridge:
    def __init__(self, tracker, data_dir):
        self.tracker = tracker
        self.db_path = os.path.join(data_dir, "owl.db")
        self.archive_path = os.path.join(data_dir, "closed_trades_archive.jsonl")
        self._last_ts = time.time()   # only signals from now on (no ping data for older ones)
        self._last_result_check = 0.0
        self.status = "INIT"

    def poll(self, now=None):
        """Pick up new Bot 1 signals. Returns how many were added."""
        added = 0
        try:
            if not os.path.exists(self.db_path):
                self.status = "NO_DB"
                return 0
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=1.0)
            try:
                rows = con.execute(
                    "SELECT signal_no, symbol, action, recorded_at, opened FROM signals "
                    "WHERE recorded_at > ? AND (bot IS NULL OR bot != 'b2') ORDER BY recorded_at ASC LIMIT 200",
                    (self._last_ts,),
                ).fetchall()
            finally:
                con.close()
            for signal_no, symbol, action, rec_ts, opened in rows:
                self._last_ts = max(self._last_ts, float(rec_ts or 0))
                side = _side(action)
                if not side or not symbol:
                    continue
                self.tracker.note_bot_signal(str(symbol).upper(), side, float(rec_ts))
                if self.tracker.signal_rows:
                    r = self.tracker.signal_rows[-1]
                    r["signal_no"] = signal_no
                    r["recorded_at"] = float(rec_ts)
                    r["opened"] = bool(opened)
                added += 1
            self.status = "OK"
            if added:
                self.tracker._save()
        except Exception as e:
            self.status = f"ERR:{type(e).__name__}"
        return added

    def _read_archive_tail(self):
        try:
            size = os.path.getsize(self.archive_path)
            with open(self.archive_path, "rb") as f:
                if size > ARCHIVE_TAIL_BYTES:
                    f.seek(size - ARCHIVE_TAIL_BYTES)
                    f.readline()  # drop a partial first line
                data = f.read().decode("utf-8", "ignore")
        except OSError:
            return []
        out = []
        for line in data.splitlines():
            try:
                t = json.loads(line)
                if isinstance(t, dict):
                    out.append(t)
            except Exception:
                continue
        return out

    def match_results(self, now=None):
        """Fill trade_pnl for opened signals whose trade has closed. Returns how many."""
        now = now if now is not None else time.time()
        if now - self._last_result_check < RESULT_CHECK_SEC:
            return 0
        self._last_result_check = now
        pending = [r for r in self.tracker.signal_rows
                   if r.get("opened") and r.get("trade_pnl") is None
                   and r.get("recorded_at") and now - r["recorded_at"] < RESULT_MAX_AGE_SEC]
        if not pending:
            return 0
        closed = self._read_archive_tail()
        done = 0
        for r in pending:
            for t in reversed(closed):
                if t.get("symbol") != r.get("symbol") or t.get("signal_no") != r.get("signal_no"):
                    continue
                opened_ts = t.get("opened_at_ts")
                if not opened_ts:
                    continue
                d = float(opened_ts) - float(r["recorded_at"])
                if -NEAR_BEFORE_SEC <= d <= NEAR_AFTER_SEC and t.get("pnl_usdt") is not None:
                    r["trade_pnl"] = float(t["pnl_usdt"])
                    done += 1
                    break
        if done:
            self.tracker._save()
        return done

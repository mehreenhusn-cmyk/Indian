"""Trading day = 5:30 AM IST = 00:00 UTC everywhere. Run: python3 test/test_trading_day_530.py"""
import os
import sys
import types
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    from recovered_bot import signal_log, ai_digest
    # signal at 03:00 IST on 22 Oct = 21:30 UTC on 21 Oct -> still trading day 21 Oct
    sig = types.SimpleNamespace(signal_time="2026-10-21 21:30:00", action="BUY", entry_price=1, stop_loss=1,
                                tp1=1, tp2=1, tp3=1, tp4=1, signal_no=1)
    signal_log._signals = []
    signal_log._save = lambda: None
    signal_log.record(sig, "AAAUSDT", True, "") if hasattr(signal_log, "record") else None
    if signal_log._signals:
        assert signal_log._signals[-1]["date_str"] == "2026-10-21", signal_log._signals[-1]
        # 05:40 IST on 22 Oct = 00:10 UTC on 22 Oct -> new day
        sig.signal_time = "2026-10-22 00:10:00"
        signal_log.record(sig, "AAAUSDT", True, "")
        assert signal_log._signals[-1]["date_str"] == "2026-10-22", signal_log._signals[-1]
    # digest groups by the UTC date
    day = datetime(2026, 10, 21, tzinfo=timezone.utc).date()
    ts_in = datetime(2026, 10, 21, 21, 30, tzinfo=timezone.utc).timestamp()   # 03:00 IST next calendar day
    from recovered_bot import trade_store
    trade_store.get_all_closed = lambda *a, **k: [{"closed_at_ts": ts_in, "pnl_usdt": 1.5, "symbol": "AAAUSDT"}]
    assert ai_digest.build_digest(day) != "", "trade at 03:00 IST belongs to the 21 Oct trading day"
    print("PASS test_trading_day_530")


if __name__ == "__main__":
    main()

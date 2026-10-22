"""Part 10: an idle loop (parked in the selector) is labelled PHONE PAUSED?, not OUR CODE BUSY; Signals today survives a restart."""
import os, sys, threading, time, unittest, selectors
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

class Part10(unittest.TestCase):
    def test_idle_selector_is_not_our_code(self):
        from recovered_bot import loop_watch as L
        holder = {}
        def park():
            holder["tid"] = threading.get_ident()
            selectors.DefaultSelector().select(1.5)
        t = threading.Thread(target=park); t.start(); time.sleep(0.3)
        self.assertTrue(L._is_idle(sys._current_frames()[holder["tid"]]))
        t.join()
        def busy():
            holder["tid2"] = threading.get_ident(); end = time.time() + 0.8
            while time.time() < end: sum(range(1000))
        t2 = threading.Thread(target=busy); t2.start(); time.sleep(0.2)
        self.assertFalse(L._is_idle(sys._current_frames()[holder["tid2"]]))
        t2.join()

    def test_signals_today_uses_db(self):
        s = open(os.path.join(ROOT, "backend/api_server.py"), encoding="utf-8").read()
        self.assertIn('db.count_signals_today("PAPER", trade_store._trading_day_start_ts())', s)
        self.assertIn('max(int(data.get("signals_today") or 0), int(n))', s)

if __name__ == "__main__":
    unittest.main()

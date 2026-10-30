"""Part 28: static checks for the shared view-state rule (NOT RUN by owner rule; Dart is not compiled here)."""
import os, re, unittest
LIB = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'lib')
def rd(*p):
    return open(os.path.join(LIB, *p), encoding='utf-8').read()

class StateGate(unittest.TestCase):
    def test_rule_order_offline_before_error_before_loading(self):
        s = rd('models', 'view_state.dart')
        a, b, c, d = (s.index(x) for x in ('if (hasData)', 'if (offline)', 'if (hasError)', 'if (!firstLoadDone)'))
        self.assertTrue(a < b < c < d)
    def test_model_is_pure_dart(self):
        self.assertNotIn('import ', rd('models', 'view_state.dart'))
    def test_age_text_over_hour_is_hours_and_minutes(self):
        s = rd('models', 'view_state.dart')
        self.assertIn("'$h h $r min'", s)
    def test_three_screens_use_gate_and_watch_offline(self):
        for f in ('positions_screen.dart', 'signals_screen.dart', 'alerts_screen.dart'):
            s = rd('screens', f)
            self.assertIn('OwlStateGate(', s, f)
            self.assertIn("p.liveState == 'offline'", s, f)
if __name__ == '__main__':
    unittest.main()

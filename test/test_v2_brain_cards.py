"""Parts 67 + 68: static checks for the Brain Skip card and the Proposals card. NOT RUN in the delivery."""
import os
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "lib")


def _read(*p):
    with open(os.path.join(LIB, *p), encoding="utf-8") as f:
        return f.read()


class SkipCardTest(unittest.TestCase):
    def test_reads_only_learn_skip_keys_the_backend_makes(self):
        s = _read("widgets", "brain_skip_card.dart")
        for k in ("skipped_done", "skipped_open", "taken_done", "mean_skip", "mean_taken", "verdict", "min_n", "tf"):
            self.assertIn("'%s'" % k, s)

    def test_is_read_only(self):
        for f in (("widgets", "brain_skip_card.dart"), ("widgets", "brain_proposals_card.dart"), ("models", "brain_proposals.dart")):
            s = _read(*f)
            for bad in ("http.", "Dio(", "placeOrder", "closeAll", "onPressed", "onTap", "Switch("):
                self.assertNotIn(bad, s)


class ProposalsTest(unittest.TestCase):
    def test_gates_follow_the_ready_check(self):
        s = _read("models", "brain_proposals.dart")
        self.assertIn("'trust': 'Trust meter', 'luck': 'Luck test', 'whatif'", s)
        self.assertIn("{'exit': 'Exit advice hit-rate'}", s)
        self.assertIn("ProposalState.notMeasured", s)

    def test_model_is_pure_dart(self):
        self.assertNotIn("import", _read("models", "brain_proposals.dart"))

    def test_ready_keys_exist_in_the_backend(self):
        b = open(os.path.join(os.path.dirname(LIB), "..", "backend", "brain_ready.py"), encoding="utf-8").read()
        for k in ('"trust"', '"luck"', '"whatif"', '"exit"'):
            self.assertIn(k, b)

    def test_cards_are_wired_into_the_brain_view(self):
        v = _read("widgets", "smart_brain_view.dart")
        self.assertIn("BrainSkipCard(learn: _map(_st['learn']))", v)
        self.assertIn("BrainProposalsCard(ready: _map(_st['ready']))", v)


if __name__ == "__main__":
    unittest.main()

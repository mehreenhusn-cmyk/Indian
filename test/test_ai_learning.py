"""Lifecycle + evidence rules of ai_learning (no network, no files besides a temp dir).
Run: python3 test/test_ai_learning.py"""
import os, random, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_learning as AL  # noqa: E402


class Life(unittest.TestCase):
    def setUp(self):
        AL.init(tempfile.mkdtemp())
        AL._life.update(loaded=True, d={})

    def test_path_discovered_confirmed_stable_weakening_rejected(self):
        t = 1_000_000.0
        self.assertEqual(AL._advance("p", "UNTESTED", t)["status"], "DISCOVERED")
        self.assertEqual(AL._advance("p", "UNTESTED", t + 3600)["status"], "VALIDATING")
        self.assertEqual(AL._advance("p", "CONFIRMED", t + 7200)["status"], "CONFIRMED")
        self.assertEqual(AL._advance("p", "CONFIRMED", t + 7200 + 50 * 3600)["status"], "STABLE")
        self.assertEqual(AL._advance("p", "UNTESTED", t + 60 * 3600)["status"], "WEAKENING")
        self.assertEqual(AL._advance("p", "FAILED", t + 61 * 3600)["status"], "REJECTED")

    def test_confirmed_clock_resets_after_a_miss(self):
        t = 5_000_000.0
        AL._advance("q", "CONFIRMED", t)
        AL._advance("q", "UNTESTED", t + 100)
        self.assertEqual(AL._advance("q", "CONFIRMED", t + 60 * 3600)["status"], "CONFIRMED")   # not STABLE yet


class Assoc(unittest.TestCase):
    def rows(self, real, coins=6):
        random.seed(3)
        out = []
        for i in range(600):
            has = random.random() < 0.4
            p_bad = (0.8 if has else 0.4) if real else 0.5
            out.append({"tok": ("x=A fact",) if has else ("x=other",), "s": f"C{i % coins}",
                        "t": 1_700_000_000_000 + i * 3_600_000, "bad": random.random() < p_bad})
        return out

    def test_real_effect_is_confirmed_and_noise_is_not(self):
        real = AL._assoc(self.rows(True), lambda r: r["bad"], "x")
        top = [i for i in real["fails"] if i["label"] == "A fact"]
        self.assertTrue(top and top[0]["status"] == "CONFIRMED")
        noise = AL._assoc(self.rows(False), lambda r: r["bad"], "x")
        self.assertFalse([i for i in noise["fails"] + noise["works"] if i["status"] == "CONFIRMED"])

    def test_one_coin_can_never_be_confirmed(self):
        one = AL._assoc(self.rows(True, coins=1), lambda r: r["bad"], "x")
        self.assertFalse([i for i in one["fails"] if i["status"] == "CONFIRMED"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)

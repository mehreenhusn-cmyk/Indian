"""Part 71: static checks of .github/workflows/owl-tests.yml (the informational tests job). NOT RUN in the delivery (owner rule).  Run: python3 test/test_v2_ci_tests_job.py"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, ".github", "workflows", name), encoding="utf-8") as f:
        return f.read()


class TestsJobTest(unittest.TestCase):
    def test_only_a_manual_trigger(self):
        y = _read("owl-tests.yml")
        self.assertIn("workflow_dispatch:", y)
        for bad in ("push:", "pull_request:", "schedule:", "workflow_run:"):
            self.assertNotIn(bad, y)

    def test_a_failing_test_never_breaks_the_run(self):
        self.assertIn("continue-on-error: true", _read("owl-tests.yml"))

    def test_runs_every_v2_test_and_reports_each_result(self):
        y = _read("owl-tests.yml")
        self.assertIn("test/test_v2_*.py", y)
        self.assertIn("GITHUB_STEP_SUMMARY", y)
        self.assertIn("exit $fail", y)

    def test_has_a_time_limit_and_no_secrets(self):
        y = _read("owl-tests.yml")
        self.assertIn("timeout-minutes:", y)
        self.assertNotIn("secrets.", y)

    def test_the_apk_build_file_has_no_tests_job(self):
        b = _read("flutter-build.yml")
        self.assertNotIn("owl-tests", b)
        self.assertNotIn("test_v2_", b)


if __name__ == "__main__":
    unittest.main()

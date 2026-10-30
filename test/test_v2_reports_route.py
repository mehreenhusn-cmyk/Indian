"""Part 62 test: backend/api/v2_reports_route.py (fees + tax route). Offline; fastapi is replaced by a tiny stub, the data folder is a temp dir.
Questions: OFF by default, ONE GET route behind the token check, 'sources' not sent, secret-looking text refused, a failing build gives a short fixed text (no path), no write / network / order code.
Run:  python3 test/test_v2_reports_route.py"""
import ast
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from api import v2_data as D
from api import v2_reports_route as A

GOOD = {"tool": "t", "boxes": {"real_live": {"totals": {"trades": 0}}}, "tax": {"state": "TAX NOT CALCULATED"}, "sources": {"/secret/path": 1}}


class T(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2r_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def enable(self):
        with open(os.path.join(self.dir, D.FLAG_NAME), "w") as f:
            f.write("1")

    def test_off_by_default(self):
        self.assertEqual(A.answer(self.dir, build=lambda d, f: GOOD)[0], 404)

    def test_on_sends_report_without_sources(self):
        self.enable()
        st, body = A.answer(self.dir, build=lambda d, f: dict(GOOD))
        self.assertEqual(st, 200)
        self.assertNotIn("sources", body)
        self.assertEqual(body["tax"]["state"], "TAX NOT CALCULATED")

    def test_secret_text_refused(self):
        self.enable()
        bad = dict(GOOD, notes=["sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"])
        st, body = A.answer(self.dir, build=lambda d, f: bad)
        self.assertEqual(st, 503)
        self.assertNotIn("sk-", str(body))

    def test_build_error_is_short_fixed_text(self):
        self.enable()

        def boom(d, f):
            raise OSError("/data/data/secret/place")
        st, body = A.answer(self.dir, build=boom)
        self.assertEqual(st, 503)
        self.assertNotIn("/data", str(body))
        self.assertEqual(A.answer(self.dir, build=lambda d, f: {"error": "x"})[0], 503)

    def test_one_get_route_behind_token(self):
        class R:
            def __init__(s):
                s.routes = []

            def get(s, path, **kw):
                return lambda f: (s.routes.append((path, kw, f)), f)[1]
        fa, resp = types.ModuleType("fastapi"), types.ModuleType("fastapi.responses")
        fa.APIRouter, fa.Depends = R, lambda f: ("dep", f)
        resp.JSONResponse = lambda body, status_code=200: (status_code, body)
        for k, v in (("fastapi", fa), ("fastapi.responses", resp)):
            self.addCleanup(sys.modules.pop, k, None) if k not in sys.modules else None
            sys.modules[k] = v
        guard = lambda: None
        r = A.make_router(guard, self.dir)
        self.assertEqual([(p, kw["dependencies"]) for p, kw, _ in r.routes], [(A.PATH, [("dep", guard)])])
        self.assertFalse([m for m in dir(r) if m in ("post", "put", "delete", "patch")])

    def test_no_network_write_or_order_code(self):
        with open(os.path.join(ROOT, "backend", "api", "v2_reports_route.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(names & {"socket", "requests", "urllib", "http", "sqlite3", "recovered_bot", "exchange", "subprocess"})
        calls = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(calls & {"open", "write", "remove", "rename", "system"})


if __name__ == "__main__":
    unittest.main()

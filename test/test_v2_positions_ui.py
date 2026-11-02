"""Part 20 test: the Flutter half of the safe close preview (frontend/lib/screens/positions_live_view.dart + providers/app_provider_positions.dart).
HONEST LIMIT: Dart cannot be compiled in the build sandbox, so these are STATIC source checks (plus a check against the real backend answer) - the owner's own APK build is the compile proof.
Main questions: are the existing close calls byte-for-byte unchanged, does the real close still happen only after the confirm, does the panic dialog open at once (the preview is never awaited
before it), does the old preview stay as the fallback, do the keys the Dart code reads exist in the real backend answer, and are both dialogs showing the LIVE / PAPER badge?
Run:  python3 test/test_v2_positions_ui.py"""
import hashlib
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from api import preview_close as V

LIB = os.path.join(ROOT, "frontend", "lib")
SCREEN = open(os.path.join(LIB, "screens", "positions_live_view.dart"), encoding="utf-8").read()
PROV = open(os.path.join(LIB, "providers", "app_provider_positions.dart"), encoding="utf-8").read()
# fingerprints (first 16 hex of sha256) of the code as it was BEFORE Part 20 - a deliberate later change must update them
UNCHANGED_PROV = {"closePosition": "f0bdedb4df96e7c4", "closeAll": "0c136588357dea8b", "panicFlatten": "54d1bdfa2f13894d", "previewCloseAll": "c09df7d16354ba8d",
                  "closeAllProfit": "1cfd1f98397b04df", "closeAllLoss": "b88ff84abc336284"}
UNCHANGED_SCREEN = {"_closeAllAndNotify": "f76988cac432b946"}
IMPORTS = "a641afc31060e2a4"


def body(src, name):
    m = re.search(r"(?:Future<[^\n]*?>|void|Widget)\s+" + re.escape(name) + r"\(", src)
    assert m, name
    p, k = 1, m.end()
    while p:                                                    # skip the parameter list first: it may hold a {named: params} brace
        p += (src[k] == "(") - (src[k] == ")")
        k += 1
    d = 0
    for j in range(src.index("{", k), len(src)):
        d += (src[j] == "{") - (src[j] == "}")
        if d == 0:
            return src[m.start():j + 1]


def fp(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def balance(src):
    t = "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))
    return tuple(t.count(a) - t.count(b) for a, b in ("()", "{}", "[]"))


class TestNothingExistingChanged(unittest.TestCase):
    def test_existing_close_and_preview_functions_are_byte_identical(self):
        for n, h in UNCHANGED_PROV.items():
            self.assertEqual(fp(body(PROV, n)), h, n)
        for n, h in UNCHANGED_SCREEN.items():
            self.assertEqual(fp(body(SCREEN, n)), h, n)

    def test_imports_unchanged_and_no_new_post_or_close_route(self):
        self.assertEqual(fp("".join(l for l in SCREEN.splitlines(True) if l.startswith("import "))), IMPORTS)
        self.assertEqual(PROV.count("_postResilient("), 8)
        self.assertNotIn("http.post", SCREEN)
        self.assertEqual(PROV.count("'/api/v2/preview_close?"), 1)
        self.assertIn("_getResilient", body(PROV, "previewClose"))
        self.assertNotIn("_postResilient", body(PROV, "previewClose"))

    def test_brackets_balance_like_the_original(self):
        self.assertEqual((balance(SCREEN), balance(PROV)), ((0, 0, 0), (0, 0, 0)))

    def test_buttons_still_pass_the_real_close_calls(self):
        self.assertEqual(SCREEN.count("provider.closeAllProfit,"), 1)
        self.assertEqual(SCREEN.count("provider.closeAllLoss,"), 1)
        code = "\n".join(l for l in SCREEN.splitlines() if not l.strip().startswith("//"))
        self.assertEqual(code.count("provider.panicFlatten()"), 1)


class TestRealCloseOnlyAfterConfirm(unittest.TestCase):
    def test_profit_loss_close_comes_after_the_confirm_check(self):
        b = body(SCREEN, "_confirmAndCloseAll")
        self.assertEqual(b.count("await _closeAllAndNotify(context, doClose(), label);"), 1)
        self.assertLess(b.index("if (confirmed != true) return;"), b.index("doClose()"))
        self.assertLess(b.index("showDialog<bool>"), b.index("if (confirmed != true) return;"))

    def test_panic_close_comes_after_the_confirm_check(self):
        b = body(SCREEN, "_confirmPanicClose")
        self.assertLess(b.index("if (confirmed != true) return;"), b.index("await provider.panicFlatten()"))

    def test_panic_dialog_never_waits_for_the_preview(self):
        b = body(SCREEN, "_confirmPanicClose")
        self.assertEqual(b.count("previewClose('flatten')"), 1)
        self.assertNotIn("await provider.previewClose", b)
        self.assertLess(b.index("previewClose('flatten')"), b.index("showDialog<bool>"))
        self.assertIn("_PanicPreviewLine(future: previewFuture", b)
        self.assertNotIn("setBusy(true)", b[:b.index("if (confirmed != true) return;")])


class TestFallbackAndBadge(unittest.TestCase):
    def test_old_preview_only_when_the_new_route_is_missing(self):
        b = body(SCREEN, "_confirmAndCloseAll")
        self.assertEqual(b.count("previewCloseAll(mode)"), 1)
        self.assertRegex(b, r"if \(safe == null\) \{\s+preview = await provider\.previewCloseAll\(mode\);")
        self.assertIn("safe['unreachable'] == true ? null", b)
        pc = body(PROV, "previewClose")
        self.assertIn("if (res.statusCode != 200) return null;", pc)
        self.assertIn("{'ok': false, 'unreachable': true}", pc)

    def test_a_backend_error_blocks_the_close_with_a_clear_text(self):
        b = body(SCREEN, "_confirmAndCloseAll")
        self.assertRegex(b, r"Text\(previewError != null\s+\? 'Preview not available \(\$previewError\) - nothing closed'\s+: 'Could not reach backend - nothing closed'\)")
        self.assertLess(b.index("preview == null"), b.index("showDialog<bool>"))

    def test_badge_in_both_dialogs(self):
        self.assertIn("_modeBadge(previewMode,", body(SCREEN, "_confirmAndCloseAll"))
        self.assertIn("_modeBadge(safe == null", SCREEN)
        b = body(SCREEN, "_modeBadge")
        self.assertIn("'LIVE'", b)
        self.assertIn("'PAPER'", b)
        self.assertNotIn("provider", b)                        # display only


class TestMatchesTheRealBackendAnswer(unittest.TestCase):
    POS = [{"symbol": "AAAUSDT", "action": "BUY", "pnl_usdt": 1.5}, {"symbol": "BBBUSDT", "action": "SELL", "pnl_usdt": -2}]

    def test_every_key_the_dart_code_reads_exists_in_the_backend_answer(self):
        view = lambda bot: ([{"id": 1, "symbol": "P1USDT", "pnl_usdt": 3.0}], 2)
        for mode in V.MODES:
            for live in (True, False):
                got = V.preview(mode, "b1", live, lambda: list(self.POS), view)
                for k in ("ok", "mode", "count", "total_pnl_usdt", "positions", "parts"):
                    self.assertIn(k, got, (mode, live, k))
                for part in got["parts"].values():
                    self.assertIn("count", part)
                for row in got["positions"]:
                    self.assertIn("symbol", row)
                    self.assertIn("pnl_usdt", row)
        self.assertIn("error", V.preview("nope", "b1", True, lambda: [], view))
        for k in ("'count'", "'total_pnl_usdt'", "'positions'", "'parts'", "'mode'", "'error'", "'pnl_usdt'", "'symbol'"):
            self.assertIn(k, SCREEN, k)
        panic = SCREEN.split("class _PanicPreviewLine", 1)[1].split("/// Awaits", 1)[0]
        for k in ("safe['count']", "safe['total_pnl_usdt']", "safe['parts']", "parts[k]['count']", "safe['mode']", "safe['error']", "safe['ok']"):
            self.assertIn(k, panic, k)

    def test_the_dart_route_is_the_backend_route(self):
        with open(os.path.join(ROOT, "backend", "api", "preview_close.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"/api/v2/preview_close"', src)
        self.assertIn("'/api/v2/preview_close?mode=$mode&$botQuery'", PROV)
        for mode in ("profit", "loss", "flatten"):
            self.assertIn(mode, V.MODES)
        self.assertIn("previewClose(mode)", SCREEN)
        self.assertIn("previewClose('flatten')", SCREEN)


if __name__ == "__main__":
    unittest.main(verbosity=1)

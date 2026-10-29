"""Part 2 test: backend/v2_inv_redact.py (fail-closed secret scrubber). Offline, no network, no trading module.
All fake secrets are built here at run time (pieces joined), so no real-looking key is stored in the repo.
Run:  python3 test/test_v2_inv_redact.py"""
import ast
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_inv_redact as R

BIN = "aB3" * 21 + "x"                                   # 64 chars, like an exchange key
TG = "123456789" + ":" + "ABCdef123_-" * 4                # Telegram-style bot token
JWT = ".".join(["eyJ" + "hbGciOiJIUzI1", "eyJ" + "zdWIiOiIxMjM0NTY3", "SflKxwRJSMeKKF2QT4fw"])
SK = "sk-" + "ant-" + "api03-" + "Zq9" * 10
HEX = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SECRETS = {"binance": BIN, "telegram": TG, "jwt": JWT, "vendor": SK, "hex": HEX,
           "bearer": "Bearer " + "Tk3" * 8, "url_cred": "https://user:" + "p4ssw0rd" + "@host.example/x",
           "url_param": "https://api.example/x?symbol=BTC&signature=" + "d3adb33f" * 2 + "&a=1",
           "pem": "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END " + "PRIVATE KEY-----",
           "kv": "api_secret=" + "hunter2hunter2", "kv_json": '"password": "' + "Sw0rdf1sh" + '"'}


def secret_part(name):
    return {"bearer": "Tk3" * 8, "url_cred": "p4ssw0rd", "url_param": "d3adb33fd3adb33f", "pem": "MIIEvQIBADANBg",
            "kv": "hunter2hunter2", "kv_json": "Sw0rdf1sh"}.get(name, SECRETS[name])


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2r_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        self.addCleanup(setattr, socket, "socket", self._sock)


class Scrub(Base):
    def test_every_secret_kind_is_removed_from_text(self):
        for name, s in SECRETS.items():
            out = R.scrub_text("before " + s + " after")
            self.assertNotIn(secret_part(name), out, name)
            self.assertIn("[REDACTED:", out, name)
            self.assertEqual(R.find_secrets(out), set(), name)           # nothing survives a second look

    def test_url_param_keeps_the_name_not_the_value(self):
        out = R.scrub_text("https://x.io/p?symbol=BTCUSDT&api_key=" + BIN + "&limit=5")
        self.assertIn("symbol=BTCUSDT", out)
        self.assertIn("limit=5", out)
        self.assertIn("api_key=[REDACTED:url_param]", out)

    def test_structure_names_numbers_and_times_are_untouched(self):
        ok = ["brain_archive.db", "journey", "owl_data_ai_ping_state_2026_10_30_backup", "BTCUSDT_15m_FUTURES_Archive_Table_X",
              "trades", "closed_at", "2026-10-30T04:21:09Z", "rows=4440201", "journey_state_observation_rows_per_candle",
              "MIXED_BY_COLUMN", "copied snapshot (WAL database)", "price: 67123.55 USDT"]
        for s in ok:
            self.assertEqual(R.scrub_text(s), s)
            self.assertEqual(R.find_secrets(s), set(), s)

    def test_scrub_is_idempotent(self):
        once = R.scrub_text(" ".join(SECRETS.values()))
        self.assertEqual(R.scrub_text(once), once)


class Values(Base):
    def test_keys_values_nesting_lists_and_bytes(self):
        obj = {"tables": [{"name": "t", "cols": ["id", BIN]}], BIN: 1, "notes": {"x": "token=" + "zz9Yy8Xx7W"},
               "blob": b"\x00\x01\x02", "n": 3, "f": 1.5, "b": True, "none": None, "t": ("a", "b")}
        out = json.dumps(R.scrub_value(obj))
        for s in (BIN, "zz9Yy8Xx7W"):
            self.assertNotIn(s, out)
        self.assertIn("<bytes 3>", out)
        self.assertEqual(R.scrub_value(obj)["n"], 3)

    def test_secret_looking_key_loses_its_value(self):
        out = R.scrub_value({"telegram_token": "plain-looking-text", "api_secret": 12345, "empty_token": "", "note": "fine"})
        self.assertEqual(out["telegram_token"], "[REDACTED:by_key]")
        self.assertEqual(out["api_secret"], "[REDACTED:by_key]")
        self.assertEqual(out["empty_token"], "")
        self.assertEqual(out["note"], "fine")

    def test_unknown_types_and_non_text_keys_are_refused(self):
        for bad in ({"a": {1, 2}}, {"a": object()}, {1: "x"}):
            with self.assertRaises(R.RedactionFailed):
                R.safe_report(bad)

    def test_config_key_paths_never_show_values(self):
        cfg = {"binance": {"api_key": BIN, "api_secret": "s3cr3t-value", "testnet": False}, "telegram": {"chat": [1, {"id": 2}]}}
        paths = R.key_paths(cfg)
        self.assertEqual(paths, ["binance", "binance.api_key", "binance.api_secret", "binance.testnet", "telegram", "telegram.chat",
                                 "telegram.chat[].id"])
        self.assertNotIn(BIN, json.dumps(paths))


class FailClosed(Base):
    def test_clean_report_passes(self):
        text = R.safe_report({"db": "brain_archive.db", "tables": [{"name": "journey", "rows": 120}], "mode": "copied snapshot"})
        self.assertEqual(json.loads(text)["tables"][0]["rows"], 120)

    def test_report_with_secrets_is_scrubbed(self):
        text = R.safe_report({"note": "x " + TG + " y", "list": [SK]})
        self.assertNotIn(TG, text)
        self.assertNotIn(SK, text)

    def test_report_is_refused_when_a_pattern_survives(self):
        keep = R.scrub_value
        R.scrub_value = lambda v: v                                       # simulate a scrubber that misses everything
        try:
            with self.assertRaises(R.RedactionFailed) as cm:
                R.safe_report({"a": {"b": ["ok", "x" + BIN]}, "c": 1})
        finally:
            R.scrub_value = keep
        self.assertEqual(cm.exception.paths, ["$.a.b[1]"])               # only the field path
        self.assertNotIn(BIN, str(cm.exception))
        self.assertNotIn(BIN, repr(cm.exception.args))

    def test_secret_in_a_key_name_is_caught_by_the_verify_pass(self):
        keep = R.scrub_value
        R.scrub_value = lambda v: v
        try:
            with self.assertRaises(R.RedactionFailed) as cm:
                R.safe_report({BIN: 1})
        finally:
            R.scrub_value = keep
        self.assertEqual(cm.exception.paths, ["$.<key>"])

    def test_write_report_writes_atomically_and_refusal_leaves_nothing(self):
        out = os.path.join(self.dir, "inv.json")
        R.write_report({"ok": "yes"}, out)
        with open(out) as f:
            self.assertEqual(json.load(f)["ok"], "yes")
        self.assertEqual(oct(os.stat(out).st_mode & 0o777), "0o600")
        self.assertEqual(os.listdir(self.dir), ["inv.json"])             # no temp file left
        with open(out) as f:
            before = f.read()
        keep = R.scrub_value
        R.scrub_value = lambda v: v
        try:
            with self.assertRaises(R.RedactionFailed):
                R.write_report({"k": BIN}, out)
            fresh = os.path.join(self.dir, "new.json")
            with self.assertRaises(R.RedactionFailed):
                R.write_report({"k": BIN}, fresh)
        finally:
            R.scrub_value = keep
        with open(out) as f:
            self.assertEqual(f.read(), before)                           # old report untouched
        self.assertFalse(os.path.exists(fresh))
        self.assertEqual(sorted(os.listdir(self.dir)), ["inv.json"])


class Isolation(unittest.TestCase):
    def test_module_has_no_network_or_trading_imports(self):
        with open(os.path.join(ROOT, "backend", "v2_inv_redact.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        self.assertEqual(names, {"json", "math", "os", "re", "tempfile"})


if __name__ == "__main__":
    unittest.main(verbosity=1)

"""v2_inv_redact.py - Part 2: FAIL-CLOSED SECRET SCRUBBER for the inventory report (used by Part 3).

Question it answers: "can this report leave the phone without any key, token, password or secret link inside it?"
Two passes: (1) scrub - every string AND every key name is cleaned, secret-looking dictionary keys lose their value;
(2) verify - the cleaned report is scanned again, leaf by leaf. If ANY secret pattern is still there, or a value has a type
this module does not know, the report is REFUSED: RedactionFailed carries only the FIELD PATHS, never a value. No partial file is written.
Plain Python (re, json, os, math, tempfile): no network, no trading module, no database, no setting.

Known limit (fail-closed on purpose): a long hex string (32+ characters, e.g. a file hash) counts as a secret and refuses the report.
Run nothing here by hand: it is a library. Tests: python3 test/test_v2_inv_redact.py
"""
import json
import math
import os
import re
import tempfile

MARK = "[REDACTED:%s]"
NOT_MARKED = r"(?!\[REDACTED)"
SENSITIVE_KEY = re.compile(r"(?i)(secret|token|passw|api[_-]?key|apikey|private|credential|signature|authorization|session)")
_PARAM = r"(?:api[_-]?key|apikey|key|token|access[_-]?token|secret|signature|sig|password|passwd|auth|authorization|x-api-key|listenkey|session|sid)"
PATTERNS = [                                   # (kind, compiled regex, replacement template)
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), None),
    ("bearer", re.compile(r"(?i)\bbearer\s+" + NOT_MARKED + r"[A-Za-z0-9._~+/=-]{8,}"), None),
    ("basic_auth", re.compile(r"(?i)\bbasic\s+" + NOT_MARKED + r"[A-Za-z0-9+/=]{12,}"), None),
    ("url_credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]*@"), None),
    ("url_param", re.compile(r"(?i)([?&;]" + _PARAM + r"=)" + NOT_MARKED + r"[^&\s#\"']+"), r"\1" + MARK % "url_param"),
    ("telegram_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"), None),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), None),
    ("vendor_key", re.compile(r"\b(?:sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|nvapi-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
                              r"|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[abprs]-[A-Za-z0-9-]{10,})"), None),
    ("keyvalue", re.compile(r"(?i)\b([A-Za-z0-9_.-]*(?:secret|token|passw(?:or)?d|api[_-]?key|apikey|private[_-]?key|credential|signature)"
                            r"[A-Za-z0-9_.-]*[\"']?\s*[=:]\s*[\"']?)" + NOT_MARKED + r"[^\s\"',;&]{4,}"), r"\1" + MARK % "keyvalue"),
    ("hex_token", re.compile(r"\b[0-9a-fA-F]{32,}\b"), None),
]
_TOKEN = re.compile(r"[A-Za-z0-9_+=-]{28,}")


class RedactionFailed(Exception):
    """The report was refused. args[0] is a list of field paths only (no values, no secrets)."""

    def __init__(self, paths):
        self.paths = list(paths)
        Exception.__init__(self, "report refused, secret pattern or unknown type at: " + ", ".join(self.paths[:20]))


def _entropy(t):
    return -sum(t.count(c) / len(t) * math.log2(t.count(c) / len(t)) for c in set(t))


def _long_token(t):
    """Random-looking long token? Names made of plain words / numbers joined by _ or - (e.g. ping_state_2026_10_30_backup) never count."""
    if all(re.fullmatch(r"[a-z]+|[A-Z]+|[A-Z][a-z]+|\d+[a-zA-Z]?", seg) for seg in re.split(r"[_-]+", t.strip("_-=+")) if seg):
        return False
    classes = bool(re.search(r"[a-z]", t)) + bool(re.search(r"[A-Z]", t)) + bool(re.search(r"\d", t))
    return classes == 3 or (classes == 2 and _entropy(t) >= 4.0)


def find_secrets(s):
    """Set of secret kinds still present in string `s` (empty = clean). Used by the verify pass."""
    kinds = {k for k, rx, _ in PATTERNS if rx.search(s)}
    if any(_long_token(t) for t in _TOKEN.findall(s)):
        kinds.add("long_token")
    return kinds


def scrub_text(s):
    """Replace every secret-looking piece of `s` with [REDACTED:kind]."""
    for kind, rx, rep in PATTERNS:
        s = rx.sub(rep if rep else MARK % kind, s)
    return _TOKEN.sub(lambda m: MARK % "long_token" if _long_token(m.group(0)) else m.group(0), s)


def scrub_value(v):
    """Recursive scrub of str / list / tuple / dict (keys too). bytes become '<bytes N>'. Unknown types raise TypeError."""
    if isinstance(v, str):
        return scrub_text(v)
    if isinstance(v, (bytes, bytearray)):
        return "<bytes %d>" % len(v)
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, (list, tuple)):
        return [scrub_value(x) for x in v]
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if not isinstance(k, str):
                raise TypeError("non-text key")
            sk = scrub_text(k)
            sensitive = SENSITIVE_KEY.search(k) and not isinstance(x, (dict, list, tuple))
            out[sk] = MARK % "by_key" if sensitive and x not in (None, "", 0, False) else scrub_value(x)
        return out
    raise TypeError("unknown type " + type(v).__name__)


def _leaves(v, path="$"):
    """Yield (path, text) for every key name and every string value."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, list):
        for i, x in enumerate(v):
            for p in _leaves(x, "%s[%d]" % (path, i)):
                yield p
    elif isinstance(v, dict):
        for k, x in v.items():
            yield path + ".<key>", k
            for p in _leaves(x, path + "." + k[:40]):
                yield p


def safe_report(obj):
    """Scrub, verify, and return the report as JSON text. Raises RedactionFailed (paths only) instead of returning anything unsafe."""
    try:
        clean = scrub_value(obj)
    except (TypeError, RecursionError):
        raise RedactionFailed(["$ (unknown type or too deep)"])
    bad = sorted({p for p, t in _leaves(clean) if find_secrets(t)})
    text = json.dumps(clean, ensure_ascii=True, sort_keys=True, indent=1)
    if not bad and find_secrets(text):
        bad = ["$ (whole report)"]
    if bad:
        raise RedactionFailed(bad)
    return text


def write_report(obj, path):
    """Write the verified report atomically (temp file + rename, mode 0600). On refusal NO file is created or changed."""
    text = safe_report(obj)
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".rep_", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return text


def key_paths(obj, prefix=""):
    """Config JSON -> sorted list of key paths only (no values). Names go through scrub_text. Lists show as '[]'."""
    out = []
    if isinstance(obj, dict):
        for k, x in obj.items():
            p = prefix + "." + scrub_text(str(k)) if prefix else scrub_text(str(k))
            out.append(p)
            out.extend(key_paths(x, p))
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            out.extend(key_paths(x, prefix + "[]"))
    return sorted(set(out))

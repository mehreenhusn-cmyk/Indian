#!/usr/bin/env python3
"""tools/review_drop.py - checks a folder (or .zip) of AI-written files BEFORE they are pushed. Plain python, no packages.
Usage:   python3 tools/review_drop.py drop/                 (a folder, searched recursively)
         python3 tools/review_drop.py drop.zip
         python3 tools/review_drop.py drop/ --repo .        (also warns when a file would REPLACE a bigger working repo file)
Exit code 0 = no FAIL, 1 = at least one FAIL. WARN = look at it, may be fine.
It catches the mistakes seen in earlier drafts: files over 350 lines, stray CJK / Devanagari characters in code, python syntax errors, relative imports,
numpy / pandas / sklearn / optuna, the non-existent table candles_5m, mock / placeholder data, hard-coded model weights, CHoCH / BOS used in code,
Dart imports without .dart, unbalanced brackets, localhost URLs, icon / widget names that do not exist, and wholesale overwrites of working files.
It does NOT compile Dart and does NOT run the code: the GitHub / APK build and the tests are the real proof."""
import ast
import io
import os
import re
import sys
import tokenize
import zipfile

MAX_LINES = 350
CODE_EXT = (".py", ".dart")
BAD_PY_IMPORTS = ("numpy", "pandas", "sklearn", "optuna", "scipy", "torch", "tensorflow")
PROTECTED = ("owl_sniper_feed.py", "owl_sniper_prob.py", "owl_sniper_engine.py", "sniper.py", "sniper_panels.dart", "sniper_screen.dart", "api_server.py", "main.dart")
BAD_DART = ("Icons.g_and_t_execute", "BoxCrossAxisAlignment", "initWithState", "Icons.shield_check")
BAD_ANY = ((r"candles_5m|candles_3m|candles_15m", "table does not exist (the table is `candles`, column interval)"),
           (r"mock_|_mock\b|placeholder|lorem", "mock / placeholder data"),
           (r"\bTODO\b|\bFIXME\b|NotImplemented", "unfinished marker"))
NON_ENGLISH = re.compile("[\u0900-\u097F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]")   # Devanagari, kana, CJK, Hangul


def read_files(path):
    """-> {relative name: text}. Folder or zip."""
    out = {}
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not n.endswith("/") and n.lower().endswith(CODE_EXT + (".md",)):
                    out[n] = z.read(n).decode("utf-8", "replace")
        return out
    for root, _d, files in os.walk(path):
        for f in files:
            if f.lower().endswith(CODE_EXT + (".md",)):
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    out[os.path.relpath(p, path)] = fh.read()
    return out


def py_code_names(text):
    """Python source with comments and strings removed (so docstrings that say 'CHoCH is excluded' are fine) -> list of NAME tokens."""
    names = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME:
                names.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return names


def dart_strip(text):
    """Dart source without comments and string literals (enough for bracket counting)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"'''.*?'''|\"\"\".*?\"\"\"", "''", text, flags=re.S)
    text = re.sub(r"r?'(?:\\.|[^'\\\n])*'", "''", text)
    return re.sub(r'r?"(?:\\.|[^"\\\n])*"', '""', text)


def check_python(name, text, res):
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        res.append(("FAIL", name, "python syntax error line %s: %s" % (e.lineno, e.msg)))
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            res.append(("FAIL", name, "relative import at line %d (backend uses absolute imports)" % node.lineno))
        mods = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
        for m in mods:
            if m.split(".")[0] in BAD_PY_IMPORTS:
                res.append(("FAIL", name, "heavy library import '%s' (pure python only)" % m))
    names = py_code_names(text)
    if any(re.search(r"(choch|(^|_)bos($|_))", n, re.I) for n in names):
        res.append(("FAIL", name, "CHoCH / BOS used in code (must stay excluded)"))
    if re.search(r"weights\s*=\s*\[\s*-?\d", text) and "fit" not in text and "train" not in text.lower():
        res.append(("WARN", name, "hard-coded weights without any fitting code"))
    if re.search(r"weights\s*=\s*\[\s*-?\d+\.\d+\s*,", text) and re.search(r"is_trained\s*=\s*True", text):
        res.append(("WARN", name, "weights set to fixed numbers and model marked trained: is it really trained?"))
    if "is_armed" in text and "confirm" not in text.lower():
        res.append(("WARN", name, "arm switch without a confirm step (needs a deliberate 2-step arm)"))


def check_dart(name, text, res):
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"\s*(?:import|export|part)\s+'([^']+)'", line)
        if m and not m.group(1).startswith("dart:") and not m.group(1).endswith(".dart"):
            res.append(("FAIL", name, "line %d: import '%s' has no .dart" % (i, m.group(1))))
        if re.match(r"\s*import\s+'[^']*';\s*$", line) is None and re.match(r"\s*import\s", line) and "'" not in line:
            res.append(("FAIL", name, "line %d: malformed import" % i))
    for bad in BAD_DART:
        if bad in text:
            res.append(("FAIL", name, "'%s' does not exist in Flutter" % bad))
    if re.search(r"https?://(localhost|127\.0\.0\.1)", text):
        res.append(("FAIL", name, "hard-coded localhost URL (use the app's backend client with its token)"))
    code = dart_strip(text)
    for o, c in ("()", "{}", "[]"):
        if code.count(o) != code.count(c):
            res.append(("FAIL", name, "unbalanced %s%s: %d open, %d close" % (o, c, code.count(o), code.count(c))))
    if re.search(r"Color\(0xFF(00E676|FF1744|00FF[0-9A-F]{2}|39FF14)\)", text):
        res.append(("WARN", name, "neon colour (design rule: calm emerald / muted crimson, use context.palette)"))
    if "http.get(" in text and "token" not in text.lower() and "fetch" not in text:
        res.append(("WARN", name, "direct http.get without a token (other screens use AppProvider fetch helpers)"))


def review(files, repo=None):
    res = []
    for name in sorted(files):
        text = files[name]
        base = os.path.basename(name)
        n = len(text.splitlines())
        if base.lower().endswith(CODE_EXT):
            if n > MAX_LINES:
                res.append(("FAIL", name, "%d lines (ceiling is %d)" % (n, MAX_LINES)))
            if NON_ENGLISH.search(text):
                res.append(("FAIL", name, "stray non-English / CJK character in code (e.g. a pasted character inside a dict)"))
            for pat, why in BAD_ANY:
                m = re.search(pat, text, flags=re.I)
                if m:
                    res.append(("FAIL" if "candles_" in pat else "WARN", name, "%s ('%s')" % (why, m.group(0))))
            (check_python if base.endswith(".py") else check_dart)(name, text, res)
            if repo and base in PROTECTED:
                for root, _d, fs in os.walk(repo):
                    if base in fs and "node_modules" not in root:
                        old = sum(1 for _ in open(os.path.join(root, base), encoding="utf-8", errors="replace"))
                        if n < 0.6 * old:
                            res.append(("WARN", name, "replaces a working file of %d lines with %d lines: PATCH it instead" % (old, n)))
                        break
        res.append(("OK", name, "%d lines" % n)) if not any(r[1] == name and r[0] == "FAIL" for r in res) else None
    return res


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    repo = argv[argv.index("--repo") + 1] if "--repo" in argv else None
    files = read_files(argv[1])
    if not files:
        print("no .py / .dart / .md files found in", argv[1])
        return 2
    res = review(files, repo)
    order = {"FAIL": 0, "WARN": 1, "OK": 2}
    for lvl, name, msg in sorted(res, key=lambda r: (order[r[0]], r[1])):
        print("%-4s  %-48s %s" % (lvl, name[-48:], msg))
    fails = sum(1 for r in res if r[0] == "FAIL")
    warns = sum(1 for r in res if r[0] == "WARN")
    print("\n%d file(s) read, %d FAIL, %d WARN. %s" % (len(files), fails, warns, "FIX THE FAILS BEFORE PUSH." if fails else "No FAIL. Dart still needs the real build."))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""R16 wiring: puts the Books strip (widgets/brain_strip.dart) on the Dashboard. Run ONCE from the repo folder (the one that holds frontend/):  python3 tools/owl_r16_wire.py
Safe to run twice. It edits ONLY frontend/lib/screens/dashboard_screen.dart:
  1) adds the import of brain_strip.dart
  2) if the old 'const CompareBooks()' table is there it becomes 'const BrainStrip()', else BrainStrip is added under the result verdict line
  3) removes the old 'const DualBotTile()' (the Dual line of the strip replaces it)
It saves a copy first: dashboard_screen.dart.bak_r16"""
import os, re, shutil, sys

root = sys.argv[1] if len(sys.argv) > 1 else "."
p = os.path.join(root, "frontend", "lib", "screens", "dashboard_screen.dart")
if not os.path.isfile(p):
    sys.exit("dashboard_screen.dart not found: run this from the repo folder (the one with frontend/).")
s = open(p, encoding="utf-8").read()
if "const BrainStrip()" in s:
    print("already wired, nothing to do")
    sys.exit(0)
shutil.copyfile(p, p + ".bak_r16")
imp = "import '../widgets/brain_strip.dart';\n"
if imp not in s:
    s = s.replace("import '../widgets/btc_live_tile.dart';\n", imp + "import '../widgets/btc_live_tile.dart';\n", 1) if "btc_live_tile.dart" in s else imp + s
how = ""
if re.search(r"const\s+CompareBooks\(\)", s):
    s = re.sub(r"const\s+CompareBooks\(\)", "const BrainStrip()", s, count=1)
    how = "replaced the old CompareBooks table"
else:
    m = re.search(r"([ \t]*)const _ResultsVerdictLine\(\),\n", s)
    if not m:
        shutil.copyfile(p + ".bak_r16", p)
        sys.exit("anchor '_ResultsVerdictLine' not found: nothing changed. Send me dashboard_screen.dart.")
    ind = m.group(1)
    s = s[:m.end()] + ind + "const SizedBox(height: AppSpacing.cardGap),\n" + ind + "const BrainStrip(),\n" + s[m.end():]
    how = "added BrainStrip under the verdict line"
s, n = re.subn(r"[ \t]*const\s+DualBotTile\(\),\n", "", s)
if "AppSpacing" in s and "theme/app_spacing.dart" not in s and "app_theme.dart" not in s:
    pass
open(p, "w", encoding="utf-8").write(s)
print("done: %s; removed %d old Dual tile. Backup: %s" % (how, n, p + ".bak_r16"))

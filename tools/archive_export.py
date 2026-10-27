#!/usr/bin/env python3
"""Write the archive's finished trades to a CSV file. Read-only. Run: python3 tools/archive_export.py [days] [out.csv]
(Without Termux: open http://localhost:8000/api/archive_export in the phone browser instead.)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import archive_tools as AT

days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
out = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/storage/downloads/owl_archive.csv")
text = AT.export_csv(days=days)
with open(out, "w", encoding="utf-8", newline="") as f:
    f.write(text)
print("wrote", max(0, text.count("\n") - 1), "trades to", out)

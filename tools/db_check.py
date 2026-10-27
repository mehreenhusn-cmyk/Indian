#!/usr/bin/env python3
"""Does the permanent archive hold every finished trade of dual_lab_data.json? Read-only. Run: python3 tools/db_check.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import archive_tools as AT

r = AT.check()
print(r["state"].upper(), "-", r["text"])
print("json finished:", r["json_closed"], "| archive finished:", r["db_closed"], "| missing in archive:", r["missing"])

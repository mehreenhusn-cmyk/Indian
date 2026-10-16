"""AI data backup: zip, keep newest, safe restore at start-up (no network, temp folder only)."""
import os, sys, tempfile, zipfile, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_backup as B

root = tempfile.mkdtemp()
ai = os.path.join(root, "ai")
os.makedirs(ai)
open(os.path.join(ai, "ai_exit_learn.json"), "w").write(json.dumps({"v": 1}))
open(os.path.join(ai, "ai_coach.json"), "w").write(json.dumps({"v": 1}))
open(os.path.join(ai, "half.tmp"), "w").write("x")                       # temp files are never saved
B.init(ai)

r = B.run("manual")
assert r["ok"] and r["files"] == 2, r
assert [b["name"] for b in B.list_backups()] == [r["name"]]
with zipfile.ZipFile(os.path.join(root, "ai_backups", r["name"])) as z:
    assert sorted(z.namelist()) == ["ai_coach.json", "ai_exit_learn.json"], z.namelist()
print("run ok")

# the data changes, then the backup is restored: queued first, applied only by apply_pending (start-up)
open(os.path.join(ai, "ai_exit_learn.json"), "w").write(json.dumps({"v": 2}))
q = B.restore(r["name"])
assert q["ok"] and B.status()["pending_restore"], q
assert json.load(open(os.path.join(ai, "ai_exit_learn.json")))["v"] == 2      # nothing changed while the AI is running
assert any(b["name"].endswith("_prerestore.zip") for b in B.list_backups())  # a way back exists
assert B.apply_pending(ai) is True
assert json.load(open(os.path.join(ai, "ai_exit_learn.json")))["v"] == 1
assert not B.status()["pending_restore"]
print("restore ok")

# bad names and path tricks are refused; a zip can never write outside the folder
assert not B.restore("../../etc/passwd")["ok"] and not B.restore("ai_9999.zip")["ok"]
evil = os.path.join(ai, "_restore_pending.zip")
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("../escaped.txt", "bad")
    z.writestr("ai_ok.json", "{}")
B.apply_pending(ai)
assert not os.path.exists(os.path.join(root, "escaped.txt")) and os.path.exists(os.path.join(ai, "ai_ok.json"))
print("safe ok")

# only the newest KEEP automatic zips stay
for k in range(B.KEEP + 3):
    p = os.path.join(root, "ai_backups", "ai_2026-01-%02d_0100.zip" % (k + 1))
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("a.json", "{}")
    os.utime(p, (time.time() - 1000 + k, time.time() - 1000 + k))
B._prune()
auto = [b for b in B.list_backups() if not b["name"].endswith(("_manual.zip", "_prerestore.zip"))]
assert len(auto) == B.KEEP, len(auto)
print("prune ok")
print("ALL OK")

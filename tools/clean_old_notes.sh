#!/bin/sh
# Deletes the OLD notes files (their content is inside README.md now). Run once from anywhere:  bash tools/clean_old_notes.sh
# Safe: does nothing unless README.md contains the marker "OWL MASTER NOTES". Never touches code.
cd "$(dirname "$0")/.." || exit 1
if ! grep -q "OWL MASTER NOTES" README.md 2>/dev/null; then
  echo "README.md is not the master notes file - nothing deleted."; exit 1
fi
for f in docs/PROJECT_STATUS.md docs/BACKEND_AUDIT.md docs/PHASE4_DESIGN.md CHANGES*.md NOTES*.md notes*.md; do
  [ -f "$f" ] && rm -f "$f" && echo "deleted $f"
done
rmdir docs 2>/dev/null && echo "removed empty docs/"
echo "done. Only README.md is left as notes."

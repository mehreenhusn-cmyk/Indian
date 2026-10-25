#!/bin/sh
# Checks if the old Kivy files backend/main.py and backend/config.py are still used. Default = look only, nothing changes.
#   bash tools/old_check.sh          -> report only
#   bash tools/old_check.sh move     -> if nothing uses them, MOVE them to backend/_old/ (never deletes)
cd "$(dirname "$0")/.." || exit 1
used=0
for f in main config; do
  hits=$(grep -rnE "^[[:space:]]*(import[[:space:]]+$f([[:space:]]|$|,)|from[[:space:]]+$f[[:space:]]+import)" backend --include=*.py | grep -v "^backend/$f.py:")
  if [ -n "$hits" ]; then used=1; echo "USED: backend/$f.py is imported here:"; echo "$hits"; else echo "not imported by any python file: backend/$f.py"; fi
done
echo "--- scripts and files that mention main.py or config.py (check your Termux scripts too, they live on the phone):"
grep -rnE "(^|[^a-zA-Z_])(main|config)\.py" backend android pubspec.yaml web_update.sh --include=*.sh --include=*.py --include=*.yaml --include=*.gradle --include=*.kts 2>/dev/null | grep -v "^backend/main.py:" | grep -v "^backend/config.py:" | grep -v "^backend/test_" | head -20
if [ "$1" = "move" ]; then
  if [ "$used" = "1" ]; then echo "NOT moved: something still imports them."; exit 1; fi
  mkdir -p backend/_old && mv backend/main.py backend/config.py backend/_old/ && echo "Moved to backend/_old/ (nothing deleted)."
else
  echo "Report only. Nothing changed. Run 'bash tools/old_check.sh move' to move them to backend/_old/."
fi

#!/usr/bin/env bash
# OWL Part 20 (29 Nov 2026): MOVE (never delete) the Dart files that nothing imports into frontend/no_use/.
# Why a script: the auto-deploy watcher only ADDS files from a zip, it cannot remove the old ones. This script does the move with `git mv` inside the phone's repo and pushes it.
# Run ONCE, after owl_Part20.zip was applied:   bash ~/Indian-main/tools/owl_no_use_move.sh        (dry run first: add the word  dry )
# The list is tools/no_use_list.txt (paths under frontend/lib/). Safe to run again: files already moved are skipped. To bring a file back: git mv it back to frontend/lib/.
set -u
REPO="$HOME/Indian-main"; [ -d "$REPO/.git" ] || REPO="$HOME/Indian-cleanup"
[ -d "$REPO/.git" ] || { echo "No git repo found (looked for ~/Indian-main and ~/Indian-cleanup)."; exit 1; }
LIST="$REPO/tools/no_use_list.txt"
[ -f "$LIST" ] || { echo "List not found: $LIST (is owl_Part20.zip pushed and pulled?)"; exit 1; }
DRY=0; [ "${1:-}" = "dry" ] && DRY=1
cd "$REPO" || exit 1
git pull -q --rebase --autostash origin main 2>/dev/null || echo "note: git pull did not work, going on with the local copy"
moved=0; skipped=0; missing=0
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  src="frontend/lib/$rel"; dst="frontend/no_use/$rel"
  if [ -f "$dst" ] && [ ! -f "$src" ]; then skipped=$((skipped+1)); continue; fi
  if [ ! -f "$src" ]; then missing=$((missing+1)); echo "missing: $src"; continue; fi
  if [ "$DRY" = 1 ]; then echo "would move: $rel"; moved=$((moved+1)); continue; fi
  mkdir -p "$(dirname "$dst")"
  if git mv "$src" "$dst" 2>/dev/null; then :; else mv "$src" "$dst"; fi
  moved=$((moved+1))
done < "$LIST"
echo "moved $moved | already moved $skipped | missing $missing"
[ "$DRY" = 1 ] && { echo "dry run: nothing changed"; exit 0; }
[ "$moved" -gt 0 ] || { echo "nothing to push"; exit 0; }
git add -A frontend >/dev/null 2>&1
ident=(); git config user.email >/dev/null 2>&1 || ident=(-c user.name=owl-auto -c user.email=owl-auto@users.noreply.github.com)
git "${ident[@]}" commit -q -m "Part 20: move $moved unused Dart files to frontend/no_use (nothing deleted)" || { echo "commit failed"; exit 1; }
if git push -q origin main 2>/dev/null || { git pull -q --rebase --autostash origin main && git push -q origin main; }; then echo "pushed. GitHub builds the app now."; else echo "push FAILED: run  cd $REPO && git push origin main"; exit 1; fi

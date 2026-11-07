#!/data/data/com.termux/files/usr/bin/bash
# OWL push-only v1 (7 Nov 2026). ONE job: a new Indian-main/ zip in Download -> GitHub.
# It NEVER starts or stops a backend (the backend runs on the VPS; the VPS pulls GitHub by itself every 2 min).
#   bash ~/owl_push_only.sh          run the loop (every 3 min)
#   bash ~/owl_push_only.sh once     one pass now, then exit
#   bash ~/owl_push_only.sh status   is it running + last log lines
export GIT_TERMINAL_PROMPT=0
LOG="$HOME/owl_push.log"; DONE="$HOME/.owl_push_only_done"; LAST="$HOME/.owl_push_only_last"
LOCKD="$HOME/.owl_push_only.lock"; INTERVAL=180

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; [ -t 1 ] && echo "$*"; return 0; }
stamp() { stat -c '%n %s %Y' "$1" 2>/dev/null; }
dl_dirs() { for d in "$HOME/storage/downloads" "$HOME/storage/shared/Download" "/sdcard/Download"; do [ -d "$d" ] && (cd "$d" && pwd -P); done | awk '!s[$0]++'; }
find_repo() { for g in "$HOME/Indian-main" "$HOME/Indian-cleanup" "$HOME/Indian"; do [ -d "$g/.git" ] && { echo "$g"; return 0; }; done; return 1; }
list_zips() { dl_dirs | while read -r d; do for f in "$d"/*.zip; do [ -f "$f" ] && stat -c '%Y|%n' "$f"; done; done | sort -t'|' -k1,1n | cut -d'|' -f2-; }

if [ "$1" = "status" ]; then
  others="$(pgrep -f owl_push_only.sh | grep -vx "$$")"
  if [ -n "$others" ]; then echo "PUSH SCRIPT: RUNNING"; else echo "PUSH SCRIPT: NOT RUNNING -> bash ~/owl_push_only.sh"; fi
  tail -n 8 "$LOG" 2>/dev/null; exit 0
fi

push_zip() {   # 0 = finished (pushed / nothing new / ignored), 1 = try again next round
  local zip="$1" name out ident=()
  PUSHED=0
  name="$(basename "$zip")"
  python3 - "$zip" <<'PY' || { log "ignored (not an Indian-main/ zip, or broken): $name"; return 0; }
import sys, zipfile
try: z = zipfile.ZipFile(sys.argv[1])
except Exception: sys.exit(1)
n = [x for x in z.namelist() if not x.endswith("/")]
sys.exit(0 if n and all(x.startswith("Indian-main/") for x in n) else 1)
PY
  if ! git -C "$REPO" pull -q --rebase --autostash origin main >>"$LOG" 2>&1; then log "git pull failed - $name NOT pushed (retry in 3 min)"; return 1; fi
  out="$(python3 - "$zip" "$REPO" <<'PY'
import os, sys, zipfile
zp, repo = sys.argv[1:3]
z = zipfile.ZipFile(zp)
ALLOWED = {"backend","frontend","tools","test","scanner","android",".github","README.md","README2.md","README4.md","README5.md","README6.md","README_CHOP.md","README_VPS.md","pubspec.yaml","pubspec.lock","analysis_options.yaml","web_update.sh",".gitignore",".metadata","docs","PLAN_400.md","FILE_INDEX.md","CLAUDE_HANDOFF.md","AI_HANDOFF_BRIEF.md"}
BLOCKED = (".apk",".aab",".ipa",".zip",".so",".jks",".keystore")
ok = 0; skipped = []
for n in z.namelist():
    if n.endswith("/"): continue
    rel = n[len("Indian-main/"):]
    if rel.split("/")[0] not in ALLOWED or rel.lower().endswith(BLOCKED) or z.getinfo(n).file_size > 20*1024*1024: skipped.append(rel); continue
    if rel.startswith("docs/") and not (rel.startswith("docs/mockups/") and rel.lower().endswith((".jpg",".jpeg",".png",".md"))): skipped.append(rel); continue
    if (not rel or rel.startswith("/") or ".." in rel.split("/") or rel.startswith(".git/") or "__pycache__" in rel or rel.endswith(".pyc") or rel == "backend/.env"): continue
    dst = os.path.join(repo, rel); os.makedirs(os.path.dirname(dst) or repo, exist_ok=True)
    open(dst, "wb").write(z.read(n)); ok += 1
print(("OK %d" % ok) + ((" (skipped %d: %s)" % (len(skipped), ", ".join(skipped[:6]))) if skipped else "")) if ok else print("NONE")
PY
)"
  case "$out" in OK*) ;; *) log "no code files for the repo in $name (nothing pushed)"; return 0 ;; esac
  git -C "$REPO" add -A >>"$LOG" 2>&1
  if git -C "$REPO" diff --cached --quiet; then log "nothing new in $name (GitHub already has it)"; return 0; fi
  git -C "$REPO" config user.email >/dev/null 2>&1 || ident=(-c user.name=owl-push -c user.email=owl-push@users.noreply.github.com)
  git -C "$REPO" "${ident[@]}" commit -q -m "auto: $name" >>"$LOG" 2>&1 || { log "commit failed for $name"; return 1; }
  if git -C "$REPO" push -q origin main >>"$LOG" 2>&1 || { git -C "$REPO" pull -q --rebase --autostash origin main >>"$LOG" 2>&1 && git -C "$REPO" push -q origin main >>"$LOG" 2>&1; }; then
    log "PUSHED $name ${out#OK } files - the VPS takes it within ~2 min and restarts the backend"
    PUSHED=1; return 0
  fi
  log "PUSH FAILED for $name (login or network). Files are committed in $REPO. Retry in 3 min."
  return 1
}

run_pass() {
  REPO="$(find_repo)" || { log "no git repo found (~/Indian-main)"; return; }
  local tmp="$HOME/.owl_push_list" f s1 s2 m last
  list_zips > "$tmp"
  if [ ! -f "$DONE" ]; then   # first run: every zip already in Download counts as old, EXCEPT owl_push_only*.zip (the one that installs this script)
    : > "$DONE"; last=0
    while IFS= read -r f; do
      case "$(basename "$f")" in owl_push_only*) continue ;; esac
      stamp "$f" >> "$DONE"; m="$(stat -c '%Y' "$f")"; [ "$m" -gt "$last" ] && last="$m"
    done < "$tmp"
    echo "$last" > "$LAST"; log "first run: marked old zips as done, will not push them"
  fi
  last="$(cat "$LAST" 2>/dev/null || echo 0)"
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    s1="$(stamp "$f")"; grep -qxF "$s1" "$DONE" 2>/dev/null && continue
    sleep 3; s2="$(stamp "$f")"; [ "$s1" = "$s2" ] || continue      # still downloading
    m="$(stat -c '%Y' "$f")"
    if [ "$m" -lt "$last" ]; then log "skipped $(basename "$f"): older than the last pushed zip"; echo "$s1" >> "$DONE"; continue; fi
    if push_zip "$f"; then echo "$s1" >> "$DONE"; [ "$PUSHED" = 1 ] && [ "$m" -gt "$last" ] && { last="$m"; echo "$m" > "$LAST"; }; fi
  done < "$tmp"
}

if [ "$1" = "once" ]; then run_pass; exit 0; fi

# loop mode: only ONE copy may run
if ! mkdir "$LOCKD" 2>/dev/null; then
  if [ -f "$LOCKD/pid" ] && kill -0 "$(cat "$LOCKD/pid")" 2>/dev/null; then echo "already running"; exit 0; fi
  rm -rf "$LOCKD"; mkdir "$LOCKD" || exit 1
fi
echo $$ > "$LOCKD/pid"; trap 'rm -rf "$LOCKD"' EXIT
tail -n 400 "$LOG" > "$LOG.tmp" 2>/dev/null && mv -f "$LOG.tmp" "$LOG"
log "push-only watcher started (v1). It never starts a backend."
while true; do run_pass; sleep "$INTERVAL"; done

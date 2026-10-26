#!/data/data/com.termux/files/usr/bin/bash
# OWL auto-deploy v5e (2026-10-27) for Termux.
#
#   bash ~/owl_auto.sh            start the watcher (only ONE can run; a 2nd copy refuses)
#   bash ~/owl_auto.sh status     full report -> screen + ~/owl_status.txt + Download/owl_status.txt
#   bash ~/owl_auto.sh restart    kill every old backend, start the live code again
#   bash ~/owl_auto.sh stop       stop watcher + backend
#   bash ~/owl_auto.sh logs       last lines of all logs (backend, ping, this script)
#   bash ~/owl_auto.sh ping       start / restart ONLY the Ping Lab worker
#   bash ~/owl_auto.sh install-boot   one-time: start OWL by itself after the phone is switched on
#   bash ~/owl_auto.sh ping-reset     clear Ping Lab saved results (Score / Lead / Bot) and restart the worker
#
# What it does
#  1. Watches Download for a NEW  Indian-main*.zip  (full repo zip) -> unpacks, swaps it in
#     as ~/owl_code (old one kept as ~/owl_code_prev), restarts the backend.
#  2. NEW: any other zip (india_part1..., vision_...) that is NEWER than the deployed full
#     zip and holds backend/ files is copied on top (backend files only, with backup and a
#     compile check; a bad file is rolled back by itself).
#  3. NEW: before every start it kills old python/uvicorn/start_forever processes and checks
#     that port 8000 is really free (an old backend still holding the port was the usual
#     reason for "the new zip is not used").
#  4. NEW: data folder is protected. If your history lived in Internal storage/owl_data and
#     that folder is not reachable (e.g. after a phone restart), the backend is NOT started
#     on an empty folder; the log says what to do.
#  5. NEW: one status file shows which zip is live, which data folder, restarts, last errors.
#  6. NEW v3: the Ping Lab worker (backend/ping_worker.py) is started, stopped, restarted and
#     checked by this same script - no second Termux window needed. It starts after the backend,
#     is killed together with it, and is started again by the watcher if it ever dies.
#     Its log: ~/owl_ping.log . If a zip has no ping_worker.py it is simply skipped.
#  7. NEW v4: install-boot writes ~/.termux/boot/owl_boot.sh (needs the Termux:Boot app, opened once).
#     After a phone restart it waits for storage, then starts this watcher, which starts the
#     backend + Ping worker and keeps picking up the newest Indian-main*.zip / overlay zips.
#  8. NEW v4: if Android kills Termux, the next start writes "previous session ended without stop"
#     with the last time it was alive, so you can see how often it happens (also in status).
#  9. NEW v4.2: after a phone restart the OLD process numbers (pids) can belong to some other app. The lock file and
#     ~/.owl_backend.pid are now only trusted when that pid really is owl_auto.sh / start_forever.sh. Before, a reused
#     number could make the boot start say "already running" and quit, or kill an unrelated process.
# 10. NEW v4.3: fixes "live folder MISSING / no backend/start_forever.sh in owl_code". Two copies of this script
#     (an old one still running + a new one) could deploy the same zip at the same moment; one moved the other's fresh
#     code away and the script still printed DEPLOYED. Now: one deploy at a time, own temp folder, every step checked
#     (a failed deploy puts the old code back), a missing live folder heals itself (newest zip is deployed again),
#     and a starting watcher stops any other old watcher copy. install-boot also removes the old owl-boot.sh.
# 11. NEW v4.4: ONE download does everything. A new overlay zip (backend + frontend files) is
#     (a) applied to the backend and the backend restarts (as before), then
#     (b) copied into the GitHub repo folder ~/Indian-cleanup, committed and pushed (so GitHub builds the app), and
#     (c) about every 3 minutes the watcher checks if GitHub finished a NEW browser build (branch web-build);
#         if yes it downloads it into ~/owl_web by itself (first time it also restarts the backend so /app exists).
#     The browser then only needs a normal refresh (the old-file cache is switched off).
#     Total time: about 10 minutes after the zip lands (GitHub needs time to build). Log lines: "github sync", "browser app updated".
# 12. NEW v5: a new zip now really replaces EVERYTHING that runs. The Brain, Dual Bot, Price Action and Volume workers are
#     separate python processes that the backend starts itself; the old script left them running, so an old Brain kept
#     writing old numbers after a deploy. Now every restart stops each python process that lives in the OWL code folders
#     (found by its folder, not by its name), and every ~5 minutes the watcher checks that no worker is older than the code
#     (a stale one is stopped and the backend starts it again). Git sync now uses ~/Indian-main (one repo) when it exists.
# 13. NEW v5c: (a) GitHub push filter: only code zips are pushed (backend/, frontend/, tools/, test/, scanner/, android/,
#     .github/, README.md, pubspec*). An APK / release-apk.zip / any other zip is never pushed (v5 pushed a 66 MB APK once),
#     and a single file over 20 MB is skipped. (b) Self-update: a zip (or the repo zip) that holds tools/owl_auto.sh with a
#     higher BUILD number replaces ~/owl_auto.sh and the watcher restarts itself, so this script never needs a manual copy again.
# 14. NEW v5d: ONE repo only. The owner also downloads zips of other repos/projects into the same Download folder. Only a zip
#     whose files ALL sit in the top folder Indian-main/ (Claude zips and the GitHub zip of this repo) is used for overlay,
#     self-update or GitHub push; every other zip is ignored (logged once as "zip ignored").
# Settings / trades live outside the code folder, so a new zip never touches them.
# Needs once:  termux-setup-storage

BUILD=40    # self-update number: a zip replaces this script only if its BUILD is a bigger whole number (v5c=2, v5d=3, v5e=40)
VERSION="v5e 2026-10-27"
DL_LIST() {   # every Download folder that exists (no duplicates)
  for d in "$OWL_DL" "$HOME/storage/downloads" "$HOME/storage/shared/Download" "/sdcard/Download" "/storage/emulated/0/Download"; do
    [ -n "$d" ] && [ -d "$d" ] && echo "$(cd "$d" 2>/dev/null && pwd -P)"
  done | awk '!s[$0]++'
}
LIVE="$HOME/owl_code"            # live code folder (contains backend/ and frontend/)
PREV="$HOME/owl_code_prev"       # one old copy for rollback
MARK="$HOME/.owl_last_zip"       # "path size mtime" of the full zip already deployed
OVDONE="$HOME/.owl_overlays_done"
LOG="$HOME/owl_auto.log"
BLOG="$HOME/owl_backend.log"
PIDF="$HOME/.owl_backend.pid"
LOCKD="$HOME/.owl_auto.lock"
DDFILE="$HOME/.owl_data_dir"
STATUS="$HOME/owl_status.txt"
PORT=8000
PLOG="$HOME/owl_ping.log"
PINGT="$HOME/.owl_ping_last_start"   # time of the last ping start (stops a restart storm)
HBF="$HOME/.owl_heartbeat"           # last time the watcher was alive (epoch seconds)
CLEANF="$HOME/.owl_clean_stop"       # exists only after an explicit "bash owl_auto.sh stop"
BOOTF="$HOME/.termux/boot/owl_boot.sh"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
stamp() { stat -c '%n %s %Y' "$1" 2>/dev/null; }
pid_is() {   # pid_is <pid> <word>: 0 only if that pid is alive AND its command line contains <word> (pids are reused after a reboot)
  [ -n "$1" ] && kill -0 "$1" 2>/dev/null && [ -r "/proc/$1/cmdline" ] && tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -q "$2"
}

# ---------------------------------------------------------------- helpers
port_open() {  # 0 = something answers on the backend port
  python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(); s.settimeout(1.5)
try:
    s.connect(("127.0.0.1", int(sys.argv[1]))); sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

http_code() {
  python3 - "$PORT" <<'PY' 2>/dev/null
import sys, urllib.request, urllib.error
try:
    r = urllib.request.urlopen("http://127.0.0.1:%s/api/status" % sys.argv[1], timeout=4)
    print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)          # 401/403 still means "alive"
except Exception as e:
    print("no answer (%s)" % type(e).__name__)
PY
}

pick_data_dir() {
  if [ -n "$OWL_DATA_DIR" ]; then echo "$OWL_DATA_DIR"; return; fi
  if [ -d "$HOME/storage/shared/owl_data" ]; then echo "$HOME/storage/shared/owl_data"; return; fi
  echo "$HOME/owl_data"
}

newest_full_zip() {   # newest Indian-main*.zip over all Download folders, by modified time
  DL_LIST | while read -r d; do
    for f in "$d"/Indian-main*.zip; do [ -f "$f" ] && stat -c '%Y|%n' "$f"; done
  done | sort -t'|' -k1,1 -rn | head -n 1 | cut -d'|' -f2-
}

ping_running() { pgrep -f "ping_worker.py" >/dev/null 2>&1; }

kill_ping() {
  pkill -f "ping_worker.py" 2>/dev/null
  sleep 1
  ping_running && pkill -9 -f "ping_worker.py" 2>/dev/null
  return 0
}

start_ping() {   # Ping Lab worker: paper only, own process, never touches the bot
  [ -f "$LIVE/backend/ping_worker.py" ] || return 0          # this zip has no ping files
  local dd now last; dd="$(pick_data_dir)"; now="$(date +%s)"; last="$(cat "$PINGT" 2>/dev/null || echo 0)"
  [ $((now - last)) -ge 30 ] || return 0                        # started less than 30 s ago
  echo "$now" > "$PINGT"
  ping_running && kill_ping
  tail -n 1500 "$PLOG" > "$PLOG.tmp" 2>/dev/null && mv "$PLOG.tmp" "$PLOG"
  ( cd "$LIVE/backend" && OWL_DATA_DIR="$dd" PYTHONUNBUFFERED=1 nohup python ping_worker.py >> "$PLOG" 2>&1 & )
  log "ping worker started | data folder: $dd | log: ~/owl_ping.log"
}

# v5: stop every python script that runs inside the OWL code folders (backend, Brain, Dual Bot, PA, Vol, ping), whatever its name is.
_kill_cwd() {   # _kill_cwd <signal> : prints how many were signalled
  python3 - "$1" "$HOME" <<'PY' 2>/dev/null
import os, sys, signal
sig = signal.SIGKILL if sys.argv[1] == "9" else signal.SIGTERM
home = sys.argv[2]
roots = (home + "/owl_code", home + "/Indian-main", home + "/Indian-cleanup")
me, n = os.getpid(), 0
for d in os.listdir("/proc"):
    if not d.isdigit() or int(d) == me:
        continue
    try:
        cwd = os.readlink("/proc/%s/cwd" % d)
        args = open("/proc/%s/cmdline" % d, "rb").read().replace(b"\0", b" ").decode("utf-8", "ignore")
    except Exception:
        continue
    if not any(cwd.startswith(r) for r in roots):
        continue
    if "python" in args and (".py" in args or "uvicorn" in args):
        try:
            os.kill(int(d), sig); n += 1
        except Exception:
            pass
print(n)
PY
}

kill_workers() {
  local n; n="$(_kill_cwd 15)"
  if [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null; then
    sleep 3; _kill_cwd 9 >/dev/null
    log "stopped $n old python process(es) from the OWL code folders (Brain / Dual Bot / backend workers)"
  fi
}

# v5: a worker that started BEFORE the newest backend .py file is running old code -> stop it (the backend starts it again by itself)
stale_check() {
  [ -d "$LIVE/backend" ] || return 0
  local out; out="$(python3 - "$LIVE" <<'PY' 2>/dev/null
import os, sys, time, signal
live = sys.argv[1]
newest = 0.0
for root, dirs, files in os.walk(os.path.join(live, "backend")):
    dirs[:] = [x for x in dirs if x not in ("__pycache__", "data", "_old")]
    for f in files:
        if f.endswith(".py"):
            try: newest = max(newest, os.path.getmtime(os.path.join(root, f)))
            except Exception: pass
try:
    up = float(open("/proc/uptime").read().split()[0])
except Exception:
    sys.exit(0)
boot = time.time() - up
hz = os.sysconf("SC_CLK_TCK")
bad = []
for d in os.listdir("/proc"):
    if not d.isdigit():
        continue
    try:
        cwd = os.readlink("/proc/%s/cwd" % d)
        args = open("/proc/%s/cmdline" % d, "rb").read().replace(b"\0", b" ").decode("utf-8", "ignore")
        st = open("/proc/%s/stat" % d).read().rsplit(")", 1)[1].split()
        start = boot + float(st[19]) / hz
    except Exception:
        continue
    if not cwd.startswith(os.path.join(live, "backend")) or "python" not in args or ".py" not in args:
        continue
    if "start.py" in args:                       # the API itself: handled by deploy / restart
        continue
    if newest > start + 5:
        bad.append(d + ":" + args.strip().split("/")[-1][:40])
        try: os.kill(int(d), signal.SIGTERM)
        except Exception: pass
print(" ".join(bad))
PY
)"
  [ -n "$out" ] && log "stale check: stopped worker(s) running OLD code: $out (the backend starts them again, up to ~3 min)"
  return 0
}

kill_old() {
  kill_ping
  if [ -f "$PIDF" ] && pid_is "$(cat "$PIDF")" start_forever; then kill "$(cat "$PIDF")" 2>/dev/null; fi
  pkill -f "start_forever.sh" 2>/dev/null
  pkill -f "python[0-9.]* start.py" 2>/dev/null
  pkill -f "uvicorn api_server" 2>/dev/null
  kill_workers
  sleep 2
  if port_open; then
    pkill -9 -f "start_forever.sh" 2>/dev/null
    pkill -9 -f "python[0-9.]* start.py" 2>/dev/null
    pkill -9 -f "uvicorn api_server" 2>/dev/null
    sleep 2
  fi
}

stop_backend() {
  kill_old
  if port_open; then
    log "WARNING: port $PORT is STILL busy after killing old backends. Another app/session holds it. Close Termux sessions or restart Termux."
    return 1
  fi
  log "old backends stopped, port $PORT is free"
  return 0
}

start_backend() {
  [ -f "$LIVE/backend/start_forever.sh" ] || { log "no backend/start_forever.sh in $LIVE"; return 1; }
  local dd last; dd="$(pick_data_dir)"; last="$(cat "$DDFILE" 2>/dev/null)"
  if [ -n "$last" ] && [ "$last" != "$dd" ] && [ ! -d "$last" ]; then
    log "STOPPED: your data folder was $last but it is not reachable now (using $dd would look like EMPTY history)."
    log "  -> run: termux-setup-storage   (allow storage), then: bash ~/owl_auto.sh restart"
    log "  -> if you really moved the data on purpose: rm ~/.owl_data_dir"
    return 1
  fi
  [ -d "$dd" ] || mkdir -p "$dd" 2>/dev/null
  echo "$dd" > "$DDFILE"
  if port_open; then
    log "port $PORT already busy, cleaning old backends first"
    stop_backend || return 1
  fi
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
  ( cd "$LIVE/backend" && OWL_DATA_DIR="$dd" PYTHONUNBUFFERED=1 nohup bash start_forever.sh >/dev/null 2>&1 & echo $! > "$PIDF" )
  log "backend started | data folder: $dd | code: $LIVE | log: ~/owl_backend.log"
  sleep 6
  if port_open; then log "backend answers on port $PORT"; else log "backend not answering yet (heavy first start can take ~20s). Check: bash ~/owl_auto.sh status"; fi
  rm -f "$PINGT"
  start_ping
}

deploy_full() {   # one deploy at a time
  local dl="$HOME/.owl_deploy.lock" rc
  if ! mkdir "$dl" 2>/dev/null; then
    if [ -n "$(find "$dl" -maxdepth 0 -mmin +5 2>/dev/null)" ]; then rm -rf "$dl"; mkdir "$dl" 2>/dev/null || return 1
    else log "another deploy is running right now - skipped"; return 1; fi
  fi
  deploy_full_inner "$1"; rc=$?
  rmdir "$dl" 2>/dev/null
  return $rc
}

deploy_full_inner() {
  local zip="$1" tmp="$HOME/.owl_tmp_extract.$$"
  rm -rf "$HOME"/.owl_tmp_extract* 2>/dev/null; mkdir -p "$tmp"
  if ! python3 -m zipfile -e "$zip" "$tmp" >>"$LOG" 2>&1; then
    log "zip is broken or still downloading: $zip"; rm -rf "$tmp"; return 1
  fi
  local root
  root="$(find "$tmp" -maxdepth 3 -type d -name backend -printf '%h\n' 2>/dev/null | head -n 1)"
  if [ -z "$root" ] || [ ! -f "$root/backend/start.py" ]; then
    log "no backend/start.py inside $zip - skipped"; rm -rf "$tmp"; return 1
  fi
  stop_backend
  rm -rf "$PREV"
  [ -d "$LIVE" ] && mv "$LIVE" "$PREV"
  if ! mv "$root" "$LIVE" || [ ! -f "$LIVE/backend/start.py" ]; then
    log "DEPLOY FAILED (could not move the new code in) - putting the old code back"
    rm -rf "$LIVE"; [ -d "$PREV" ] && mv "$PREV" "$LIVE"
    rm -rf "$tmp"; return 1
  fi
  rm -rf "$tmp"
  stamp "$zip" > "$MARK"
  : > "$OVDONE"
  log "DEPLOYED full zip: $zip  ($(stat -c '%y' "$zip" | cut -d. -f1))"
  start_backend
}

# overlay: copy backend/ files of a partial zip on top of the live code (backup + compile check)
overlay_zip() {
  local zip="$1" bk="$HOME/owl_overlay_backup/$(date +%m%d_%H%M%S)" out
  out="$(python3 - "$zip" "$LIVE" "$bk" <<'PY'
import os, shutil, sys, zipfile, py_compile
zp, live, bk = sys.argv[1:4]
try:
    z = zipfile.ZipFile(zp)
except Exception as e:
    print("BROKEN", e); sys.exit(2)
names = [n for n in z.namelist() if not n.endswith("/")]
pref = set()
for n in names:
    parts = n.split("/")
    if "backend" in parts[:3]:
        pref.add("/".join(parts[:parts.index("backend")]))
if not pref:
    print("NOBACKEND"); sys.exit(3)
p = sorted(pref, key=len)[0]
pre = (p + "/" if p else "") + "backend/"
done = []
for n in names:
    if not n.startswith(pre): continue
    rel = n[len(pre):]
    if (not rel or "__pycache__" in rel or rel.endswith(".pyc") or rel == ".env"
            or rel.startswith("data/") or rel.startswith("..") or rel.startswith("/")): continue
    dst = os.path.join(live, "backend", rel)
    existed = os.path.exists(dst)
    if existed:
        b = os.path.join(bk, rel); os.makedirs(os.path.dirname(b), exist_ok=True); shutil.copy2(dst, b)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f: f.write(z.read(n))
    done.append((rel, existed))
bad = []
for rel, _ in done:
    if rel.endswith(".py"):
        try: py_compile.compile(os.path.join(live, "backend", rel), doraise=True)
        except Exception as e: bad.append(rel)
if bad:
    for rel, existed in done:
        dst = os.path.join(live, "backend", rel)
        if existed: shutil.copy2(os.path.join(bk, rel), dst)
        else:
            try: os.remove(dst)
            except OSError: pass
    print("BAD " + ",".join(bad)); sys.exit(4)
print("OK %d files: %s" % (len(done), ", ".join(r for r, _ in done)[:300]))
PY
  )"; local rc=$?
  case "$out" in
    OK*)        log "OVERLAY applied from $(basename "$zip"): ${out#OK }"; return 0 ;;
    NOBACKEND*) log "overlay skipped (no backend/ files inside): $(basename "$zip")"; return 5 ;;
    BAD*)       log "OVERLAY REJECTED (python compile error, rolled back): $(basename "$zip") -> ${out#BAD }"; return 4 ;;
    *)          log "overlay failed for $(basename "$zip"): $out (code $rc)"; return 1 ;;
  esac
}

# v5c: self-update. A zip with tools/owl_auto.sh of a higher BUILD number replaces this script; the main loop then restarts the watcher.
self_update_file() {
  local new="$1" me="$HOME/owl_auto.sh" nb cb
  [ -f "$new" ] || return 0
  head -n 3 "$new" | grep -q "OWL auto-deploy" || return 0
  bash -n "$new" 2>/dev/null || { log "self-update: the new owl_auto.sh has a syntax error - NOT used"; return 0; }
  nb="$(sed -n 's/^BUILD=\([0-9][0-9]*\).*/\1/p' "$new" | head -n 1)"; cb="$(sed -n 's/^BUILD=\([0-9][0-9]*\).*/\1/p' "$me" | head -n 1)"
  [ "${nb:-0}" -gt "${cb:-0}" ] 2>/dev/null || return 0
  cp "$new" "$me.new" && mv "$me.new" "$me" && : > "$HOME/.owl_self_update" && log "self-update: owl_auto.sh BUILD ${cb:-0} -> $nb, the watcher restarts itself"
}

self_update_zip() {
  local zip="$1" tmp="$HOME/.owl_auto.new"
  python3 - "$zip" "$tmp" <<'PY' 2>/dev/null
import sys, zipfile
try:
    z = zipfile.ZipFile(sys.argv[1])
    for n in z.namelist():
        if n.endswith("tools/owl_auto.sh") and ".." not in n.split("/"):
            open(sys.argv[2], "wb").write(z.read(n)); break
except Exception:
    pass
PY
  [ -f "$tmp" ] && { self_update_file "$tmp"; rm -f "$tmp"; }
  return 0
}

is_owl_zip() {   # v5d: 0 only if every file in the zip is inside the top folder Indian-main/
  python3 - "$1" <<'PY' 2>/dev/null
import sys, zipfile
try:
    names = [n for n in zipfile.ZipFile(sys.argv[1]).namelist() if n.strip("/")]
    ok = bool(names) and all(n.split("/")[0] == "Indian-main" for n in names)
except Exception:
    ok = False
sys.exit(0 if ok else 1)
PY
}

check_overlays() {
  [ -f "$MARK" ] || return 0
  [ -d "$LIVE/backend" ] || return 0
  local full_m; full_m="$(awk '{print $NF}' "$MARK")"
  local applied=0
  DL_LIST | while read -r d; do
    for f in "$d"/*.zip; do
      [ -f "$f" ] || continue
      case "$(basename "$f")" in Indian-main*) continue ;; esac
      local m s1 s2 key
      m="$(stat -c '%Y' "$f")"
      [ "$m" -gt "$full_m" ] || continue
      s1="$(stamp "$f")"; key="$s1"
      grep -qxF "$key" "$OVDONE" 2>/dev/null && continue
      sleep 3; s2="$(stamp "$f")"
      [ "$s1" = "$s2" ] || continue          # still downloading
      echo "$key" >> "$OVDONE"
      is_owl_zip "$f" || { log "zip ignored (not an Indian-main/ zip, so not this repo): $(basename "$f")"; continue; }
      self_update_zip "$f"
      overlay_zip "$f"; orc=$?
      [ "$orc" -eq 0 ] && echo applied > "$HOME/.owl_overlay_flag"
      case "$orc" in 0|5) sync_repo "$f" ;; esac       # good backend overlay, or a frontend-only zip -> GitHub
    done
  done
  if [ -f "$HOME/.owl_overlay_flag" ]; then
    rm -f "$HOME/.owl_overlay_flag"
    stop_backend; start_backend
  fi
}

# >>> v4.4 github + browser auto-update
REPO="$HOME/Indian-cleanup"          # old git clone
[ -d "$HOME/Indian-main/.git" ] && REPO="$HOME/Indian-main"   # v5: ONE repo - the same folder as your manual unzip + push
WEBDIR="$HOME/owl_web"               # browser app, served by the backend at /app/
WEBHASH="$HOME/.owl_web_hash"        # which web-build commit is already in ~/owl_web

git_ok() { [ -d "$REPO/.git" ] && command -v git >/dev/null 2>&1; }

# sync_repo <zip>: put the zip's files into the repo folder, commit, push. GitHub then builds the app + the browser version.
sync_repo() {
  local zip="$1" out
  git_ok || { log "github sync skipped: no git repo at $REPO"; return 1; }
  if ! git -C "$REPO" pull -q --rebase --autostash origin main >>"$LOG" 2>&1; then
    log "github sync: git pull failed (see ~/owl_auto.log) - $(basename "$zip") NOT pushed"; return 1
  fi
  out="$(python3 - "$zip" "$REPO" <<'PY'
import os, sys, zipfile
zp, repo = sys.argv[1:3]
try:
    z = zipfile.ZipFile(zp)
except Exception as e:
    print("BROKEN", e); sys.exit(2)
names = [n for n in z.namelist() if not n.endswith("/")]
tops = {n.split("/")[0] for n in names}
pre = ""
if len(tops) == 1 and list(tops)[0] not in ("backend", "frontend", ".github", "test", "scanner") and all("/" in n for n in names):
    pre = list(tops)[0] + "/"          # one wrapper folder (like Indian-main/) -> strip it
ALLOWED = {"backend", "frontend", "tools", "test", "scanner", "android", ".github", "README.md", "pubspec.yaml",
           "pubspec.lock", "analysis_options.yaml", "web_update.sh", ".gitignore", ".metadata"}
BLOCKED_EXT = (".apk", ".aab", ".ipa", ".zip", ".so", ".jks", ".keystore")
n_ok = 0
n_skip = 0
for n in names:
    rel = n[len(pre):] if n.startswith(pre) else n
    if rel and (rel.split("/")[0] not in ALLOWED or rel.lower().endswith(BLOCKED_EXT) or z.getinfo(n).file_size > 20 * 1024 * 1024):
        n_skip += 1
        continue
    if (not rel or rel.startswith("/") or ".." in rel.split("/") or rel.startswith(".git/")
            or "__pycache__" in rel or rel.endswith(".pyc") or rel == "backend/.env"):
        continue
    dst = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(dst) or repo, exist_ok=True)
    with open(dst, "wb") as f:
        f.write(z.read(n))
    n_ok += 1
print("OK", n_ok) if n_ok else print("NONE", n_skip)
PY
  )"
  case "$out" in
    OK*) ;;
    NONE*) log "github sync skipped: $(basename "$zip") has no code files for the repo (APK / other zips are never pushed)"; return 0 ;;
    *) log "github sync: could not unpack $(basename "$zip"): $out"; return 1 ;;
  esac
  git -C "$REPO" add -A >>"$LOG" 2>&1
  if git -C "$REPO" diff --cached --quiet; then log "github sync: nothing new in $(basename "$zip") (repo already has it)"; return 0; fi
  local ident=()
  git -C "$REPO" config user.email >/dev/null 2>&1 || ident=(-c user.name=owl-auto -c user.email=owl-auto@users.noreply.github.com)
  git -C "$REPO" "${ident[@]}" commit -q -m "auto: $(basename "$zip")" >>"$LOG" 2>&1 || { log "github sync: commit failed"; return 1; }
  if git -C "$REPO" push -q origin main >>"$LOG" 2>&1 || { git -C "$REPO" pull -q --rebase --autostash origin main >>"$LOG" 2>&1 && git -C "$REPO" push -q origin main >>"$LOG" 2>&1; }; then
    log "github sync: pushed $(basename "$zip") ${out#OK } files - GitHub is building now, the browser app follows in ~10 min (automatic)"
    return 0
  fi
  log "github sync: PUSH FAILED for $(basename "$zip") (login/network?). Files are committed in $REPO; run: cd $REPO && git push origin main"
  return 1
}

# web_check: new browser build on GitHub (branch web-build)? -> download it into ~/owl_web (no backend restart needed).
web_check() {
  git_ok || return 0
  local url rh old tmp had
  url="$(git -C "$REPO" remote get-url origin 2>/dev/null)" || return 0
  rh="$(timeout 40 git ls-remote "$url" refs/heads/web-build 2>/dev/null | cut -f1)"
  [ -n "$rh" ] || return 0                                   # no network / no web-build branch yet
  old="$(cat "$WEBHASH" 2>/dev/null)"
  if [ "$rh" = "$old" ] && [ -f "$WEBDIR/index.html" ]; then return 0; fi
  tmp="$HOME/.owl_web_tmp"; rm -rf "$tmp"
  if ! timeout 240 git clone -q --depth 1 -b web-build "$url" "$tmp" >>"$LOG" 2>&1 || [ ! -f "$tmp/index.html" ]; then
    log "browser update: download failed (will try again in a few minutes)"; rm -rf "$tmp"; return 1
  fi
  rm -rf "$tmp/.git"
  # Flutter web keeps an old copy in the browser (service worker). This tiny file clears it and removes itself,
  # so after the next refresh the browser always shows the newest build.
  cat > "$tmp/flutter_service_worker.js" <<'SW'
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.registration.unregister(); }));
});
SW
  had=0; [ -f "$WEBDIR/index.html" ] && had=1
  rm -rf "$WEBDIR"
  if ! mv "$tmp" "$WEBDIR"; then log "browser update: could not move the new build in"; return 1; fi
  echo "$rh" > "$WEBHASH"
  log "browser app updated (build ${rh:0:7}) - just refresh the browser page"
  if [ "$had" = 0 ] && pgrep -f "start_forever.sh" >/dev/null 2>&1; then
    log "first browser build: restarting the backend once so it serves /app/"
    stop_backend; start_backend
  fi
  return 0
}

web_check_bg() {   # runs web_check in the background, never two at once (a stale lock is cleaned after 10 min)
  local wl="$HOME/.owl_web.lock"
  if ! mkdir "$wl" 2>/dev/null; then
    [ -n "$(find "$wl" -maxdepth 0 -mmin +10 2>/dev/null)" ] && rm -rf "$wl"
    return 0
  fi
  ( web_check; rmdir "$wl" 2>/dev/null ) >/dev/null 2>&1 &
}
# <<< v4.4

# ---------------------------------------------------------------- report
status_report() {
  {
    echo "===== OWL STATUS  $(date '+%F %T')  (owl_auto.sh $VERSION) ====="
    if [ -f "$LOCKD/pid" ] && pid_is "$(cat "$LOCKD/pid")" owl_auto; then echo "watcher        : RUNNING (pid $(cat "$LOCKD/pid"))"; else echo "watcher        : NOT running  -> bash ~/owl_auto.sh"; fi
    if [ -f "$HBF" ]; then echo "last alive     : $(date -d @"$(cat "$HBF")" '+%F %T' 2>/dev/null)"; fi
    echo "boot start     : $( [ -f "$BOOTF" ] && echo 'installed (needs the Termux:Boot app opened once)' || echo 'NOT installed -> bash ~/owl_auto.sh install-boot')"
    echo "unexpected ends: $(grep -c 'previous session ended without stop' "$LOG" 2>/dev/null) (times Android/phone closed Termux; see ~/owl_auto.log)"
    echo
    echo "--- which code is live ---"
    if [ -f "$MARK" ]; then echo "full zip used  : $(sed 's/ [0-9]* [0-9]*$//' "$MARK")"; echo "zip modified   : $(date -d @"$(awk '{print $NF}' "$MARK")" '+%F %T' 2>/dev/null)"; else echo "full zip used  : none deployed yet"; fi
    echo "live folder    : $LIVE  ($( [ -d "$LIVE/backend" ] && echo ok || echo MISSING ))"
    [ -f "$LIVE/backend/recovered_bot/ai_vision_lessons.py" ] && echo "vision notebook: in live code" || echo "vision notebook: NOT in live code (ai_vision_lessons.py missing)"
    [ -f "$LIVE/backend/recovered_bot/india_runtime.py" ] && grep -q "ticks" "$LIVE/backend/india_api.py" 2>/dev/null && echo "india fast data: in live code (/api/india/ticks)" || echo "india fast data: NOT in live code"
    echo "overlays done  : $( [ -f "$OVDONE" ] && wc -l < "$OVDONE" || echo 0 )"
    echo
    echo "--- newest zips in Download (what the script can see) ---"
    DL_LIST | while read -r d; do echo "folder: $d"; ls -t "$d"/*.zip 2>/dev/null | head -n 6 | while read -r f; do echo "   $(stat -c '%y' "$f" | cut -d. -f1)  $(stat -c '%s' "$f") B  $(basename "$f")"; done; done
    echo
    echo "--- data folder (history/settings) ---"
    local dd; dd="$(pick_data_dir)"
    echo "in use         : $dd  ($( [ -d "$dd" ] && echo exists || echo MISSING ))"
    echo "remembered     : $(cat "$DDFILE" 2>/dev/null || echo -)"
    for fn in settings.json trades.json positions.json owl.db; do if [ -f "$dd/$fn" ]; then echo "   $fn  $(stat -c "%s B, changed %y" "$dd/$fn" | cut -d. -f1)"; else echo "   $fn  missing"; fi; done
    echo "   corrupt copies: $(ls "$dd"/*.corrupt-* 2>/dev/null | wc -l)"
    [ -d "$HOME/owl_data" ] && [ "$dd" != "$HOME/owl_data" ] && echo "   NOTE: a second, different folder ~/owl_data also exists (not used)"
    echo
    echo "--- GitHub + browser ---"
    echo "repo folder    : $REPO  ($( [ -d "$REPO/.git" ] && echo ok || echo MISSING ))"
    echo "browser app    : $( [ -f "$WEBDIR/index.html" ] && echo "in ~/owl_web, build $(cut -c1-7 "$WEBHASH" 2>/dev/null)" || echo 'not downloaded yet (waits for the first GitHub web build)' )"
    echo "github/browser log:"; grep -E 'github sync|browser (app|update)' "$LOG" 2>/dev/null | tail -n 4 | sed 's/^/   /'
    echo
    echo "--- backend ---"
    echo "port $PORT      : $(port_open && echo OPEN || echo CLOSED)"
    echo "http answer    : $(http_code)"
    echo
    echo "--- Ping Lab worker ---"
    if [ -f "$LIVE/backend/ping_worker.py" ]; then
      echo "ping worker    : $(ping_running && echo RUNNING || echo NOT running)"
      local pst; pst="$(pick_data_dir)/ai/ping_state.json"
      if [ -f "$pst" ]; then echo "ping snapshot  : updated $(( $(date +%s) - $(stat -c %Y "$pst") )) s ago (should be under 10)"; else echo "ping snapshot  : none yet (wait ~1 min after start)"; fi
      echo "ping log tail  :"; tail -n 5 "$PLOG" 2>/dev/null | sed 's/^/   /'
    else
      echo "ping worker    : not in live code (no backend/ping_worker.py)"
    fi
    echo
    echo "--- backend ---"
    echo "processes      :"; ps -e -o pid,etime,args 2>/dev/null | grep -E "start_forever|start.py|uvicorn|ping_worker|smart_brain|dual_lab|pa_layer|vol_layer" | grep -v grep | sed 's/^/   /' || true
    echo "starts in log  : $(grep -c 'starting backend' "$BLOG" 2>/dev/null)   (crash-loop warnings: $(grep -c 'CRASH LOOP' "$BLOG" 2>/dev/null))"
    echo "last exits     :"; grep 'exited with code' "$BLOG" 2>/dev/null | tail -n 5 | sed 's/^/   /'
    echo "                 (137/143 = Android killed it, 1 = python error, traceback is above that line)"
    command -v termux-battery-status >/dev/null 2>&1 && echo "battery        : $(termux-battery-status 2>/dev/null | tr -d '\n ' | cut -c1-120)"
    grep -E 'MemAvailable|MemTotal' /proc/meminfo 2>/dev/null | sed 's/^/ram            : /'
    echo
    echo "--- last 25 lines: backend log (~/owl_backend.log) ---"
    tail -n 25 "$BLOG" 2>/dev/null
    echo
    echo "--- last 20 lines: this script (~/owl_auto.log) ---"
    tail -n 20 "$LOG" 2>/dev/null
  } > "$STATUS" 2>&1
  cat "$STATUS"
  DL_LIST | head -n 1 | while read -r d; do cp "$STATUS" "$d/owl_status.txt" 2>/dev/null && echo "(copy saved: $d/owl_status.txt)"; done
}

# ---------------------------------------------------------------- commands
case "$1" in
  status)  status_report; exit 0 ;;
  logs)    echo "--- backend ---"; tail -n 40 "$BLOG" 2>/dev/null; echo "--- ping ---"; tail -n 20 "$PLOG" 2>/dev/null; echo "--- script ---"; tail -n 30 "$LOG" 2>/dev/null; exit 0 ;;
  ping)    rm -f "$PINGT"; kill_ping; start_ping; exit 0 ;;
  ping-reset)
    dd="$(pick_data_dir)"; kill_ping
    # also the .bak / .tmp copies - the worker reloads from .bak if only the main file is gone
    rm -f "$dd"/ai/ping_lead.json* "$dd"/ai/ping_trades.json* "$dd"/ai/ping_events.jsonl* "$dd"/ai/ping_state.json*
    log "ping results cleared in $dd/ai"; rm -f "$PINGT"; start_ping; exit 0 ;;
  install-boot)
    mkdir -p "$HOME/.termux/boot" || exit 1
    rm -f "$HOME/.termux/boot/owl-boot.sh"      # old boot file from termux_boot_setup.sh (would start a second backend)
    cat > "$BOOTF" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
# Written by owl_auto.sh install-boot. Runs by itself after the phone starts (Termux:Boot).
termux-wake-lock
# wait (max ~10 min) until phone storage can be read; it can be locked until first unlock
for i in $(seq 1 120); do
  ls /sdcard/Download >/dev/null 2>&1 && break
  sleep 5
done
[ -f "$HOME/owl_auto.sh" ] || exit 0
nohup bash "$HOME/owl_auto.sh" >> "$HOME/owl_boot.log" 2>&1 &
BOOT
    chmod +x "$BOOTF"
    echo "Boot file written: $BOOTF"
    echo "Now do this ONCE: open the Termux:Boot app (it shows a short message), then keep it installed."
    echo "Also set Android battery for Termux AND Termux:Boot to Unrestricted."
    echo "Test: restart the phone, wait 2-3 minutes, then run: bash ~/owl_auto.sh status"
    exit 0 ;;
  stop)
    if [ -f "$LOCKD/pid" ] && pid_is "$(cat "$LOCKD/pid")" owl_auto; then kill "$(cat "$LOCKD/pid")" 2>/dev/null; fi
    rm -rf "$LOCKD"; date +%s > "$CLEANF"
    for p in $(pgrep -f 'owl_auto\.sh' 2>/dev/null); do   # any stray watcher copy too
      [ "$p" = "$$" ] && continue
      cl="$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null)"
      case "$cl" in *owl_auto.sh\ ) kill "$p" 2>/dev/null ;; esac
    done
    kill_old; log "stopped watcher + backend"; exit 0 ;;
  restart)
    kill_old; start_backend; exit 0 ;;
esac

# ---------------------------------------------------------------- single instance
if ! mkdir "$LOCKD" 2>/dev/null; then
  sleep 1                                   # the other copy may not have written its pid yet
  if [ -f "$LOCKD/pid" ] && pid_is "$(cat "$LOCKD/pid")" owl_auto; then
    echo "owl_auto.sh is ALREADY running (pid $(cat "$LOCKD/pid")). Only one is allowed."
    echo "See what it does:  bash ~/owl_auto.sh status      Stop it:  bash ~/owl_auto.sh stop"
    exit 1
  fi
  rm -rf "$LOCKD"; mkdir "$LOCKD" || exit 1
fi
echo $$ > "$LOCKD/pid"
trap 'rm -rf "$LOCKD"; exit 0' INT TERM EXIT
for p in $(pgrep -f 'owl_auto\.sh' 2>/dev/null); do   # stop any OTHER old watcher copy (only plain "bash owl_auto.sh", not status/stop/...)
  [ "$p" = "$$" ] && continue
  [ "$p" = "$PPID" ] && continue
  cl="$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null)"
  case "$cl" in *owl_auto.sh\ ) kill "$p" 2>/dev/null; log "stopped another owl_auto.sh watcher copy (pid $p)" ;; esac
done
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
if [ -f "$HBF" ] && [ ! -f "$CLEANF" ]; then
  log "previous session ended without stop (last alive $(date -d @"$(cat "$HBF")" '+%F %T' 2>/dev/null)) - Android or the phone closed Termux"
fi
rm -f "$CLEANF"

log "watcher $VERSION started | download folders: $(DL_LIST | tr '\n' ' ') | live code: $LIVE | data: $(pick_data_dir)"
[ -n "$(DL_LIST)" ] || log "WARNING: no Download folder reachable - run termux-setup-storage"

n=0
LAST_BTRY=0
while true; do
  date +%s > "$HBF"
  if [ -f "$MARK" ] && [ ! -f "$LIVE/backend/start.py" ]; then
    if [ -z "$(newest_full_zip)" ] && [ -f "$PREV/backend/start.py" ]; then
      mv "$PREV" "$LIVE" && log "live code folder was missing - restored the previous copy"
    else
      log "live code folder is missing/broken - the newest Indian-main zip will be deployed again"
      rm -f "$MARK"
    fi
  fi
  z="$(newest_full_zip)"
  if [ -n "$z" ]; then
    s1="$(stamp "$z")"; sleep 3; s2="$(stamp "$z")"        # size stable = download finished
    if [ "$s1" = "$s2" ] && [ "$s1" != "$(cat "$MARK" 2>/dev/null)" ]; then
      log "new full zip found: $z"
      deploy_full "$z"
      self_update_file "$LIVE/tools/owl_auto.sh"
      status_report >/dev/null 2>&1
    fi
  fi
  check_overlays
  if [ -f "$HOME/.owl_self_update" ]; then        # v5c: a newer owl_auto.sh was installed by a zip -> restart this watcher with it
    rm -f "$HOME/.owl_self_update"; date +%s > "$CLEANF"; rm -rf "$LOCKD"
    log "watcher restarts itself with the new owl_auto.sh"
    exec bash "$HOME/owl_auto.sh"
  fi
  [ $((n % 18)) -eq 0 ] && web_check_bg                 # about every 3 min: new browser build on GitHub? -> ~/owl_web
  # backend not running (first start, phone killed it)? start it
  if [ -d "$LIVE/backend" ] && ! pgrep -f "start_forever.sh" >/dev/null 2>&1; then
    nowt="$(date +%s)"
    if [ $((nowt - LAST_BTRY)) -ge 30 ]; then      # at most one try per 30 s (no log spam if storage is not ready)
      LAST_BTRY="$nowt"
      log "backend was not running - starting it"
      start_backend
    fi
  fi
  # ping worker died (or was never started)? start it again (only while the backend is up)
  if [ -f "$LIVE/backend/ping_worker.py" ] && pgrep -f "start_forever.sh" >/dev/null 2>&1 && ! ping_running; then
    log "ping worker was not running - starting it"
    start_ping
  fi
  [ $((n % 30)) -eq 15 ] && stale_check               # v5: about every 5 min: no worker may run older code than the files
  n=$((n+1)); [ $((n % 30)) -eq 0 ] && status_report >/dev/null 2>&1   # fresh status file about every 5 min
  sleep 10
done

#!/data/data/com.termux/files/usr/bin/bash
# OWL backend keep-alive for Termux.
#  - keeps the phone CPU awake (wake lock)
#  - restarts the backend automatically if it exits/crashes
#  - writes WHY it stopped to ~/owl_backend.log  (exit code 137/143 = Android killed it,
#    1 = Python error - the traceback is just above that line)
# Use:  cd <this folder> && bash start_forever.sh
cd "$(dirname "$0")" || exit 1
LOG="$HOME/owl_backend.log"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
echo "[$(date '+%F %T')] watchdog started" >> "$LOG"
while true; do
  echo "[$(date '+%F %T')] starting backend" >> "$LOG"
  python start.py >> "$LOG" 2>&1
  code=$?
  echo "[$(date '+%F %T')] backend exited with code $code" >> "$LOG"
  # keep the log small (last ~2000 lines)
  tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  sleep 3
done

#!/data/data/com.termux/files/usr/bin/bash
# OWL backend keep-alive for Termux (v2: no more 3-second crash loop).
#  - keeps the phone CPU awake (wake lock)
#  - restarts the backend automatically if it exits/crashes
#  - if it dies again and again within 30 s, it waits longer (30s, 40s ... max 120s) instead of
#    burning battery/CPU every 3 s, and writes "CRASH LOOP" + the likely reason to ~/owl_backend.log
#  - exit code 137/143 = Android killed it, 1 = Python error (traceback is just above that line)
cd "$(dirname "$0")" || exit 1
LOG="$HOME/owl_backend.log"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
echo "[$(date '+%F %T')] watchdog started (data folder: ${OWL_DATA_DIR:-default ~/owl_data})" >> "$LOG"
fails=0
while true; do
  t0=$(date +%s)
  echo "[$(date '+%F %T')] starting backend" >> "$LOG"
  python start.py >> "$LOG" 2>&1
  code=$?
  ran=$(( $(date +%s) - t0 ))
  echo "[$(date '+%F %T')] backend exited with code $code after ${ran}s" >> "$LOG"
  if [ "$ran" -lt 30 ]; then fails=$((fails+1)); else fails=0; fi
  wait_s=3
  if [ "$fails" -ge 3 ]; then
    wait_s=$((fails*10)); [ "$wait_s" -gt 120 ] && wait_s=120
    echo "[$(date '+%F %T')] CRASH LOOP: died ${fails}x within 30s, waiting ${wait_s}s" >> "$LOG"
    if tail -n 40 "$LOG" | grep -qi "address already in use\|errno 98"; then
      echo "[$(date '+%F %T')]   reason: port 8000 is held by an OLD backend -> run: bash ~/owl_auto.sh restart" >> "$LOG"
    fi
  fi
  tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  sleep "$wait_s"
done

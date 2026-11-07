# README_VPS - phone, GitHub and VPS (7 Nov 2026)

## RULE for any Claude
The owner is not technical. Reply in very simple English, short. ONE step at a time, ONE question at a time. Termux commands = ONE ready block, no placeholders. Never ask for passwords.

## Where things run now
- **Backend: on the VPS only.** Cloud On Fire, Ubuntu 22.04, IP 222.167.207.31, user root. The phone backend is OFF for good (the phone was too hot and used too much battery and internet).
- **Never run the phone backend and the VPS backend together.** Orders would double.
- **Do NOT run `bash ~/owl_auto.sh`.** It starts the phone backend. Its boot file is renamed to `~/.termux/boot/owl-start.sh.off`.
- **App -> VPS:** Tailscale ON on the phone, and in the Owl app Settings the Backend URL is `http://100.85.188.83:8000`. Android Private DNS must be OFF. Port 8000 is closed to the internet.
- VPS data folder: `/home/owl/owl_data`. Code: `/home/owl/Indian-main`. Termux logs in with an ssh key (no password).
- VPS python packages use the tuna mirror (`/etc/pip.conf`) because pypi.org is blocked there.

## How a new zip reaches the VPS
1. Download the zip (top folder `Indian-main/`) on the phone.
2. `~/owl_push_only.sh` (in Termux) sees it within ~3 min and pushes it to GitHub. It never starts a backend.
3. The VPS checks GitHub every 2 min (`owl-update.timer`), pulls, restarts the backend, and rolls back if Python has a compile error.

## How to check each step
- Push script running + last lines: `bash ~/owl_push_only.sh status`
- Push now, once: `bash ~/owl_push_only.sh once`
- Push log: `cat ~/owl_push.log` (look for "PUSHED")
- VPS update log: `ssh root@222.167.207.31 "tail -5 /home/owl/owl_update.log"`
- VPS backend: `ssh root@222.167.207.31 "systemctl is-active owl-backend owl-ping"` (two lines: active)
- Phone backend off: `pgrep -af "start.py|start_forever.sh|ping_worker.py" || echo "PHONE BACKEND OFF"`

## About owl_push_only.sh
- Starts by itself every time Termux opens (one line in `~/.bashrc`). If Android closes Termux, open Termux once.
- First run marks every zip already in Download as old (not pushed). Only newer zips are pushed.
- Only zips whose files ALL sit in `Indian-main/` are pushed. Same filter as before (backend, frontend, tools, test, scanner, android, .github, README files, pubspec). `backend/.env`, APK and big files are never pushed.
- Known limit: a re-downloaded OLD zip gets a new file time, so it would be pushed. Delete old zips instead of re-downloading them.

## Still open
- Syncthing: daily data copy VPS -> phone (send-only on VPS, receive-only on phone). Not set up yet.
- `API_TOKEN` is still OFF (the app does not send a token). Keep port 8000 closed; use Tailscale only.
- Later: make the repo Private and use a read-only deploy key on the VPS. `backend/.env` is tracked in the repo.

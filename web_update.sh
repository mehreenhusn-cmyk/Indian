#!/data/data/com.termux/files/usr/bin/bash
# Pull the latest browser build (made by GitHub) into ~/owl_web, then restart the backend.
set -e
REPO="$HOME/Indian-cleanup"
URL="$(git -C "$REPO" remote get-url origin)"
rm -rf "$HOME/owl_web"
git clone --depth 1 -b web-build "$URL" "$HOME/owl_web"
rm -rf "$HOME/owl_web/.git"
echo "Browser app ready in ~/owl_web"
bash "$HOME/owl_auto.sh" restart
IP="$(ip -4 addr show wlan0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2)"
echo "Open in browser:  http://${IP:-<phone-wifi-ip>}:8000/app/"

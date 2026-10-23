#!/bin/zsh
# Refresh the data, then serve the dashboard to any device on the current Wi-Fi.
# Works the same at home and at the office: the .local address follows this Mac
# whichever network it joins.
cd "$(dirname "$0")"
PORT=8000

./update.sh || echo "Data refresh failed; serving the last dashboard."

HOST="$(scutil --get LocalHostName).local"
IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
echo ""
echo "Dashboard is live on this Wi-Fi:"
echo "  http://$HOST:$PORT   (same address at home and office - bookmark this)"
echo "  http://$IP:$PORT   (fallback if the one above doesn't load)"
echo "Press Ctrl+C to stop."
.venv/bin/python -m http.server $PORT --bind 0.0.0.0 --directory docs

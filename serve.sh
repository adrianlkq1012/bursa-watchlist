#!/bin/zsh
# Serve the dashboard to any device on your home Wi-Fi
cd "$(dirname "$0")"
IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
echo "Open on your phone/laptop: http://$IP:8000"
.venv/bin/python -m http.server 8000 --bind 0.0.0.0 --directory docs

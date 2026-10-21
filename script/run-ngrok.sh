#!/bin/sh
set -eu

service_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user
mkdir -p "$service_dir"
cat > "$service_dir/anki-ngrok.service" <<'EOF'
[Unit]
Description=ngrok tunnel for Anki Deck
After=network-online.target

[Service]
Type=simple
ExecStart=ngrok http 11000
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now anki-ngrok.service
printf 'ngrok user service enabled and started. Check logs with: journalctl --user -u anki-ngrok -f\n'

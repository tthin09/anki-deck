#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# run as the host user so the container can write to data-dev/
ANKI_UID="$(id -u)" ANKI_GID="$(id -g)" docker compose -f compose.dev.yaml up --build -d

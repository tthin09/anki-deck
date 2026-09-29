#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose -f compose.dev.yaml up --build -d

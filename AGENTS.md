# Git commits

After every update to code, create a Git commit that includes that code change.

# Dev server

After every feature or code change, rebuild and restart the dev stack so it runs the new code:

```
script/run-dev.sh
```

The script runs the container as your user so it can write to `data-dev/`; a plain `docker compose up` would use uid 10001 and conversions would fail.

It serves on port 12000 (`http://100.109.137.65:12000/`). Leave the production stack (`compose.prod.yaml`) alone unless asked.

Production runs as uid 10001 (`script/run-prod.sh`), so `data/history/` must be owned by 10001:10001. If conversions fail at "Đóng gói", check that ownership first.

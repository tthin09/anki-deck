# Git commits

After every update to code, create a Git commit that includes that code change.

# Dev server

After every feature or code change, rebuild and restart the dev stack so it runs the new code:

```
docker compose -f compose.dev.yaml up -d --build
```

It serves on port 12000 (`http://100.109.137.65:12000/`). Leave the production stack (`compose.prod.yaml`) alone unless asked.

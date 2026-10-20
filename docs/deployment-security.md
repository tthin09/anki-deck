# Conversion safety and non-root deployment

## Before starting the updated container

The image runs as UID/GID `10001:10001`, not root. Both Compose files use this default; `ANKI_UID` and `ANKI_GID` can override it. Existing host data must be accessible to that numeric user.

From the repository root, stop the old service, back up `data/`, then run:

```sh
docker compose -f compose.prod.yaml stop
sudo mkdir -p data
sudo chown -R 10001:10001 data
./script/run-prod.sh
```

If you override the UID/GID, use those values in the ownership command. Do not delete `data/` when rebuilding. Backups may require elevated permissions after this change.

## Persistence

`./data:/data` remains a host bind mount. Completed packages stay in `data/history/`, along with `conversions.csv`. Package bytes are fsynced before atomic publication, and the CSV and containing directory are fsynced before success is reported. A failed/cancelled conversion is not published. An abrupt process crash can leave an unfinished `.apkg.part` file; it is not downloadable and can be removed while the service is stopped. A crash between publishing a file and committing the CSV can leave an unrecorded package. Files and CSV are not a transactional database.

This is local persistence, not an off-machine backup. Disk failure and storage devices that do not honor flushes are outside this guarantee. Back up the host directory separately.

## Conversion lifecycle

- There is no login. Each browser gets an anonymous `session` cookie that scopes its jobs and downloads; clearing cookies abandons them.
- One server worker per browser; further submissions during an uncancelled conversion return HTTP 409 with a wait message.
- Refresh, navigation, close, and frontend connection failures request cancellation. Only the originating tab tracks its job. Refresh also retries cancellation using its session-storage job ID.
- The tab sends a heartbeat every 5 seconds. A server-side timer cancels the job after 30 seconds without one; provider calls already in progress are allowed to return before further work stops. Background-tab browser throttling can also trigger this timeout.
- Cancellation prevents subsequent work and publication; in-flight provider calls can still finish or incur charges. A replacement is accepted immediately but waits for the old worker to return. There is at most one pending replacement; cancel it before submitting its successor.
- These locks and job state are process-local. Keep Uvicorn at one worker. Restarting cancels unfinished work but does not remove completed files.

## Validation and deck HTML

All `/api/` request bodies must be strictly smaller than 8192 bytes, including JSON overhead. Oversized bodies return HTTP 413 before parsing. After trimming each vocabulary line, a word may contain no whitespace and must be at most 50 Unicode characters. Blank lines and case-insensitive duplicates are ignored; the conversion maximum remains 100 words. Invalid words return HTTP 422 naming the line.

Generated card HTML allows only `br`, `i`, and `b`, without attributes. Scripts and other active elements are removed. Reverse-card plain text is escaped. Application-generated audio controls are appended separately.

## Still deferred

This is not a complete public-deployment security solution. HTTPS/private backend access, secure cookies, audio-host restrictions, daily/global Gemini quotas, and storage-retention limits remain deferred. Anyone who can reach the app can spend Gemini quota; per-browser serialization does not limit sequential spending, new cookies, or total work across browsers.

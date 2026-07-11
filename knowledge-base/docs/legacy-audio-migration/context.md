### [2026-07-11] - legacy audio migration
* **Status:** Completed.
* **Changed:** Added idempotent `tag:ai-vocab` discovery, DictionaryAPI resolution, media-first storage, verified field updates, autoplay, and per-note reporting.
* **Context:** Normal audio targets Front; reverse audio targets Back with safe common-inflection fallback to a unique normal base.
* **Touched:** `src/migrate_audio.py`, `README.md`, `HUONG-DAN.txt`, `migrate.exe`
* **Interfaces:** Migration report is UTF-8 `bao-cao-migrate.txt`; double-click requires Y confirmation.
* **Verified:** Source self-test and mocked AnkiConnect migration with second-run no-op.
* **Follow-ups:** Live collection testing remains pending because AnkiConnect was not listening.

### [2026-07-11] - migration word preview
* **Status:** Completed.
* **Changed:** Added a per-note preview list before the summary and Y confirmation.
* **Context:** Reverse entries expose the selected base pronunciation when fallback differs from the displayed answer.
* **Touched:** `src/migrate_audio.py`, `README.md`, `migrate.exe`
* **Interfaces:** Preview format is `word (thẻ thường|thẻ đảo)` with optional `→ audio: base`.
* **Verified:** Source and packaged self-tests.
* **Follow-ups:** None.

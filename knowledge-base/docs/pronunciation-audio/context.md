### [2026-07-11] - pronunciation audio and timed logging
* **Status:** Completed.
* **Changed:** Added cached HTTPS DictionaryAPI lookups with US/UK/any priority, exact reverse-answer lookup with base fallback, compact license attribution, and elapsed-time logs.
* **Context:** AnkiConnect downloads deterministic media filenames directly; the app creates text-only cards when audio is unavailable.
* **Touched:** `src/anki_deck.py`, `README.md`, `HUONG-DAN.txt`, `run.exe`
* **Interfaces:** Optional card audio metadata maps to AnkiConnect `{url, filename, fields}`; diagnostics now probe DictionaryAPI.
* **Verified:** `py_compile`, source/package `--self-test`, live word/phrase/404 requests, packaged `--diagnose`.
* **Follow-ups:** Full live Anki media download was not run because the workspace has a placeholder Gemini key.

### [2026-07-11] - deployment diagnostics
* **Status:** Completed.
* **Changed:** Added companion-file, input, Excel, write-access, Gemini, and AnkiConnect checks; added save-and-close warning and safer error messages.
* **Context:** `run.exe` depends on the full extracted folder. Diagnostics are non-destructive except for writing the report and a temporary write probe.
* **Touched:** `src/anki_deck.py`, `KIEM-TRA.cmd`, `src/config.json`, `HUONG-DAN.txt`
* **Interfaces:** `--diagnose` performs one minimal live Gemini request and never adds Anki notes.
* **Verified:** `python -m py_compile`, `--self-test`, and packaged `--diagnose` with placeholder-key failure.
* **Follow-ups:** Revoke the formerly distributed key and replace the placeholder with a per-user key.

### [2026-07-11] - Anki startup preflight
* **Status:** Completed.
* **Changed:** Normal runs check AnkiConnect before reading input or calling Gemini.
* **Context:** Users receive a direct Vietnamese instruction when Anki is closed or AnkiConnect is unavailable.
* **Touched:** `src/anki_deck.py`, `run.exe`
* **Interfaces:** Added startup AnkiConnect `version` probe.
* **Verified:** Source and packaged self-tests.
* **Follow-ups:** None.

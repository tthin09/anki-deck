### [2026-07-11] - deployment diagnostics
* **Status:** Completed.
* **Changed:** Added user-run deployment diagnostics and clearer Vietnamese startup failures.
* **Context:** Recipients can generate a shareable report without adding cards or exposing their API key.
* **Touched:** `src/anki_deck.py`, `KIEM-TRA.cmd`, `HUONG-DAN.txt`
* **Interfaces:** Added `run.exe --diagnose`; report output is `bao-cao-kiem-tra.txt`.
* **Verified:** Source self-test and packaged executable diagnostics.
* **Follow-ups:** Each user must configure their own Gemini API key.

### [2026-07-11] - Anki startup preflight
* **Status:** Completed.
* **Changed:** Added an immediate Vietnamese Anki/AnkiConnect warning before card generation.
* **Context:** A closed Anki instance now stops the run before Gemini quota or workbook work is used.
* **Touched:** `src/anki_deck.py`, `run.exe`
* **Interfaces:** Normal startup now requires a successful AnkiConnect version check.
* **Verified:** Source self-test and packaged executable self-test.
* **Follow-ups:** None.

### [2026-07-11] - [native audio autoplay](audio-autoplay/context.md)
* **Status:** Completed.
* **Changed:** Removed visible audio attribution and enabled native Anki autoplay on the configured deck preset.
* **Context:** Vocabulary audio plays on the front and reverse audio on the back without source text or custom players.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Audio metadata is `{url, filename}`; startup may set deck config `autoplay=true` before adding notes.
* **Verified:** Audio payload/autoplay unit checks plus source and packaged self-tests.
* **Follow-ups:** Existing cards are unchanged; shared deck presets also inherit autoplay.

### [2026-07-11] - [Anki audio field list](audio-field-list/context.md)
* **Status:** Completed.
* **Changed:** Corrected AnkiConnect audio `fields` from a string to a one-item list.
* **Context:** AnkiConnect now inserts `[sound:...]` into Front/Back, enabling native replay buttons and autoplay.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Audio payload uses `fields: ["Front"]` or `fields: ["Back"]`.
* **Verified:** Front/back payload assertions and source/package self-tests.
* **Follow-ups:** Existing cards created without sound markers are unchanged.

### [2026-07-11] - [centered replay button](replay-button-layout/context.md)
* **Status:** Completed.
* **Changed:** Added field-local CSS to place Anki's native replay button on a centered new line.
* **Context:** Audio playback remains native while normal-front and reverse-back layouts no longer place the button beside text.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Audio target fields include `.replay-button` layout CSS before AnkiConnect appends `[sound:...]`.
* **Verified:** Front/back/no-audio layout assertions plus source and packaged self-tests.
* **Follow-ups:** Existing cards require regeneration to receive the style.

### [2026-07-11] - [legacy audio migration](legacy-audio-migration/context.md)
* **Status:** Completed.
* **Changed:** Added a preview/confirm migration script and `migrate.exe` for tagged legacy notes without audio.
* **Context:** Existing scheduled cards gain native media in place while already-audio, unresolved, malformed, and unrelated notes remain untouched.
* **Touched:** `src/migrate_audio.py`, `README.md`, `migrate.exe`
* **Interfaces:** Adds `--dry-run`, `--yes`, `--self-test`, `--no-pause`; writes `bao-cao-migrate.txt`.
* **Verified:** Parser self-test, mocked full migration/rerun, packaged self-test; live Anki unavailable on port 8765.
* **Follow-ups:** Run packaged dry-run and migration when AnkiConnect is reachable.

### [2026-07-11] - [migration word preview](legacy-audio-migration/context.md)
* **Status:** Completed.
* **Changed:** Migration preview now prints every ready word, card type, and different base-audio fallback before confirmation.
* **Context:** Users can inspect the exact migration set before typing Y.
* **Touched:** `src/migrate_audio.py`, `README.md`, `migrate.exe`
* **Interfaces:** Console preview adds one line per eligible note.
* **Verified:** Preview formatting self-test and packaged self-test.
* **Follow-ups:** None.

### [2026-07-11] - [pronunciation audio and timed logging](pronunciation-audio/context.md)
* **Status:** Completed.
* **Changed:** Added DictionaryAPI pronunciation, AnkiConnect media payloads, reverse-answer fallback, attribution, timed phase logs, and developer README.
* **Context:** Normal cards play audio on the front; reverse cards play the displayed answer on the back while missing audio remains non-fatal.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Cards carry optional audio metadata; Anki note payloads may include `audio`; reverse data retains `answer` and `keyword`.
* **Verified:** Source/package self-tests, live DictionaryAPI samples, audio payload checks, packaged diagnostics.
* **Follow-ups:** Full Gemini/Anki insertion requires a configured user key and running Anki.

### [2026-07-11] - [input validation order](input-validation/context.md)
* **Status:** Completed.
* **Changed:** Moved saved-input validation before AnkiConnect and standardized the Vietnamese empty/locked input error.
* **Context:** Unsaved empty Notepad input now reports the input action instead of an unrelated Anki warning.
* **Touched:** `src/anki_deck.py`, `run.exe`
* **Interfaces:** Normal startup validates input before the AnkiConnect preflight.
* **Verified:** Empty-input regression check plus source and packaged self-tests.
* **Follow-ups:** Windows cannot detect unsaved in-memory Notepad edits when the on-disk file already contains older text.

### [2026-07-11] - [aligned console status](console-logging/context.md)
* **Status:** Completed.
* **Changed:** Padded console status labels to a fixed nine-character width.
* **Context:** Runtime log messages now align after brackets for faster scanning.
* **Touched:** `src/anki_deck.py`, `README.md`
* **Interfaces:** Console output uses `[Đang chạy]`, `[OK       ]`, and equivalently padded labels.
* **Verified:** Source self-test assertions for running, success, and failure labels.
* **Follow-ups:** `run.exe` intentionally not rebuilt per user request.

### [2026-07-11] - [automatic AI retry progress](ai-retries/context.md)
* **Status:** Completed.
* **Changed:** Reduced Gemini request timeout to 30 seconds, retried transient connection failures, and logged active-step elapsed time before retries.
* **Context:** Runs recover without Ctrl+C and make long retry periods visible.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Gemini attempts use a 30-second timeout and up to three automatic retries.
* **Verified:** Retry classification/progress self-tests and packaged self-test.
* **Follow-ups:** None.

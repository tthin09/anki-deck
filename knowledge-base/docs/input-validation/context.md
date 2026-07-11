### [2026-07-11] - input validation order
* **Status:** Completed.
* **Changed:** Empty or unreadable input now raises `Hãy điền từ vựng vào notepad, lưu, và đóng file đó lại trước.` before checking Anki.
* **Context:** Startup errors now point to the first user action that must be corrected.
* **Touched:** `src/anki_deck.py`, `run.exe`
* **Interfaces:** Input validation precedes AnkiConnect validation.
* **Verified:** Empty-directory regression assertion and source/package self-tests.
* **Follow-ups:** Existing saved file contents are indistinguishable from newer unsaved editor contents.

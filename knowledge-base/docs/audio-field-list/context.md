### [2026-07-11] - Anki audio field list
* **Status:** Completed.
* **Changed:** Wrapped each AnkiConnect audio target field in a list.
* **Context:** Passing a string caused AnkiConnect to iterate characters and silently attach audio to no field.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Native audio payload target is now a list of field names.
* **Verified:** Source and packaged `--self-test`.
* **Follow-ups:** None.

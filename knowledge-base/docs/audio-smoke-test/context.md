### [2026-07-13] - configurable AI flashcard test workflow
* **Status:** Completed.
* **Changed:** Added `test/test_new_N_words.py`, which reuses production Gemini normal/reverse prompts and card functions, verifies audio, deletes/recreates `English Vocab [Test]`, and adds complete normal/reverse notes.
* **Context:** The positional count selects 1-50 words; each run starts with a fresh test deck and sets `new.perDay` to 200.
* **Touched:** `test/test_new_N_words.py`
* **Interfaces:** CLI: `python test/test_new_N_words.py <number>`.
* **Verified:** Python compilation, help, and invalid-count validation; live run requires AnkiConnect and Gemini access.
* **Follow-ups:** Start Anki with AnkiConnect before the live workflow.

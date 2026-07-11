### [2026-07-11] - automatic AI retry progress
* **Status:** Completed.
* **Changed:** Added active timed-step progress lines before each automatic Gemini retry and treated connection timeouts as retryable.
* **Context:** A blocked request now releases after 30 seconds and retry progress shows total batch elapsed time.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Gemini retry ceiling remains three retries after the initial attempt.
* **Verified:** Source and packaged `--self-test`.
* **Follow-ups:** None.

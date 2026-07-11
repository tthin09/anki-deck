### [2026-07-11] - aligned console status
* **Status:** Completed.
* **Changed:** Central `msg` formatting pads status labels to nine characters.
* **Context:** All normal runtime messages share one aligned text column without changing their Vietnamese wording.
* **Touched:** `src/anki_deck.py`, `README.md`
* **Interfaces:** Console log prefix width is fixed at nine characters inside brackets.
* **Verified:** `python src/anki_deck.py --self-test --no-pause`.
* **Follow-ups:** Rebuild `run.exe` only when requested.

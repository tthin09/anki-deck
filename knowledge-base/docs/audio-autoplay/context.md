### [2026-07-11] - native audio autoplay
* **Status:** Completed.
* **Changed:** Deleted attribution HTML/data and added `getDeckConfig`/`saveDeckConfig` autoplay enforcement.
* **Context:** AnkiConnect still downloads media and injects sound into `Front` for vocabulary cards and `Back` for reverse cards.
* **Touched:** `src/anki_deck.py`, `README.md`, `HUONG-DAN.txt`, `run.exe`
* **Interfaces:** Deck configuration preserves all values except `autoplay`, which is forced to `true`.
* **Verified:** False/true/save-failure autoplay paths, clean audio metadata, source/package self-tests.
* **Follow-ups:** No migration of previously generated note HTML.

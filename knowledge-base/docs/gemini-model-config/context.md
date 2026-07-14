### [2026-07-14] - Gemini model configuration
* **Status:** Completed.
* **Changed:** Switched the default and example Gemini model to `gemini-3.1-flash-lite`; the local config was updated too.
* **Context:** Gemini 3.1 Flash-Lite is the current low-latency, high-frequency model selected for higher request capacity.
* **Touched:** `src/anki_deck.py`, `src/config.example.json`, `src/config.json`
* **Interfaces:** `src/config.json` continues to use the existing `model` field; the Gemini `generateContent` request shape is unchanged.
* **Verified:** `python src\\anki_deck.py --self-test --no-pause`; confirmed the test script has 50 words.
* **Follow-ups:** None.

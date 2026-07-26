### [2026-07-14] - Gemini model configuration
* **Status:** Completed.
* **Changed:** Switched the default and example Gemini model to `gemini-3.1-flash-lite`; the local config was updated too.
* **Context:** Gemini 3.1 Flash-Lite is the current low-latency, high-frequency model selected for higher request capacity.
* **Touched:** `src/anki_deck.py`, `src/config.example.json`, `src/config.json`
* **Interfaces:** `src/config.json` continues to use the existing `model` field; the Gemini `generateContent` request shape is unchanged.
* **Verified:** `python src\\anki_deck.py --self-test --no-pause`; confirmed the test script has 50 words.
* **Follow-ups:** None.

### [2026-07-14] - Test workflow alignment
* **Status:** Completed.
* **Changed:** Reused the production generation, audio, Excel, progress logging, and Anki-add workflow from the 50-word test script; retained only fixed test words and Test-deck reset as test behavior.
* **Context:** Test runs now expose the same timed AI stage and failure behavior as the main application.
* **Touched:** `src/anki_deck.py`, `test/test_new_N_words.py`
* **Interfaces:** Added internal shared workflow helpers; Test deck remains `English Vocab [Test]`.
* **Verified:** Python compilation, source self-test, and test-script help command.
* **Follow-ups:** Live test intentionally not run because it deletes and recreates the Test deck.

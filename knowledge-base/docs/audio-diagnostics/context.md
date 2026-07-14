### [2026-07-14] - Audio response diagnostics
* **Status:** Completed.
* **Changed:** Added per-word tracing for DictionaryAPI, Wiktionary, and Google TTS when audio cannot be resolved.
* **Context:** DictionaryAPI responses legitimately vary: `phonetics.audio` is optional or empty, entries may contain multiple pronunciations, and valid entries may have no recording. Some responses also provide `.ogg` alongside MP3.
* **Touched:** `src/anki_deck.py`
* **Interfaces:** Missing-audio warnings now include each source's result or error; card creation remains non-fatal.
* **Verified:** `python src\\anki_deck.py --self-test --no-pause`; researched official DictionaryAPI examples and live response variants.
* **Follow-ups:** Keep MP3-only filtering for mobile compatibility; use the new logs to identify whether remaining misses are endpoint gaps, rejected formats, or fallback failures.

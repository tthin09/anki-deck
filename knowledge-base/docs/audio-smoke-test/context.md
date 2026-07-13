### [2026-07-13] - 50-word audio smoke test
* **Status:** Completed.
* **Changed:** Added `test/test_audio_50_words.py`, using the existing audio resolver and fetching one byte from each returned HTTPS URL.
* **Context:** The test exercises DictionaryAPI/Wiktionary/Google TTS fallback behavior against live services.
* **Touched:** `test/test_audio_50_words.py`
* **Interfaces:** None.
* **Verified:** `python -m py_compile test/test_audio_50_words.py`; live run passed 50/50.
* **Follow-ups:** Requires network access and may take about one minute.

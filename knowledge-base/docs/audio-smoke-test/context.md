### [2026-07-13] - 50-word audio smoke test
* **Status:** Completed.
* **Changed:** Added `test/test_audio_50_words.py`, using the existing audio resolver, fetching one byte from each returned HTTPS URL, and adding Basic notes to `English Vocab [Test]`.
* **Context:** The test exercises DictionaryAPI/Wiktionary/Google TTS fallback behavior and AnkiConnect deck setup against live services. It sets `new.perDay` to 200.
* **Touched:** `test/test_audio_50_words.py`
* **Interfaces:** None.
* **Verified:** `python -m py_compile test/test_audio_50_words.py`; live run passed 50/50 and added 50 notes.
* **Follow-ups:** Requires network access and may take about one minute.

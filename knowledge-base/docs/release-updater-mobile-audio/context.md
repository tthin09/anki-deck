### [2026-07-13] - release updater and mobile-safe audio
* **Status:** Completed.
* **Changed:** Added tag-triggered GitHub Actions builds for `run.exe` and `migrate.exe`, a native PowerShell updater, root diagnostics launcher, MP3-only audio selection, and end-user mobile sync instructions.
* **Context:** Users update from GitHub without installing Git or Python; release packages preserve local config, input, and generated workbooks. Non-MP3 source URLs are rejected so the existing fallback chain can choose portable MP3 audio.
* **Touched:** `.github/workflows/release.yml`, `update.cmd`, `update.ps1`, `src/anki_deck.py`, `src/README.md`, `HUONG-DAN.txt`
* **Interfaces:** The updater consumes the public `anki-deck-runtime.zip` asset from the latest GitHub release and never copies `src/config.json` or user data.
* **Verified:** `py_compile`, source self-tests, packaged self-tests, and PowerShell parser validation.
* **Follow-ups:** Rotate the previously committed Gemini credential before publishing the first release.

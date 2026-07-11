### [2026-07-11] - centered replay button
* **Status:** Completed.
* **Changed:** Styled `.replay-button` as a centered block with 12px top spacing in audio-bearing fields.
* **Context:** The Basic note model has no dedicated audio field, so field-local CSS positions Anki's appended native control without changing the model.
* **Touched:** `src/anki_deck.py`, `README.md`, `run.exe`
* **Interfaces:** Card field HTML gains a compact `<style>` element only when audio exists.
* **Verified:** Source and packaged `--self-test`.
* **Follow-ups:** None.

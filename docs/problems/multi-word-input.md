# Multi-word input such as "as well as" has no defined behaviour

Status: fixed (2026-10-21) — see "Decision" below.

## Symptom
Users sometimes enter a phrase longer than one word, for example "as well as", "look forward to" or "take off". We haven't decided what the app should do with it.

## How it works now
- Web input (`vocabulary` in `src/web_app.py`) rejects any line with whitespace: "enter one word without spaces or tabs". So the phrase can't be converted from the web UI at all.
- The prompt (`src/agent-prompt.md`) already says "word, phrase, or sentence" and has phrase tags (`np`, `vp`, `adjp`, `advp`, `s`), so the LLM side partly expects phrases.
- Audio comes from Wiktionary, with Google TTS as fallback. Many phrases have no Wiktionary page, so they would rely on TTS.

## Things to decide
1. Accept phrases at all? If yes, up to how many words or characters (the line limit is 50 characters now)?
2. Treat the whole line as one item (one card for "as well as"), or split it into separate words? One item seems right for fixed phrases.
3. Which part-of-speech tag to use for phrases that don't fit the current set, for example "as well as" (conjunction/preposition) or phrasal verbs.
4. How to bold the phrase in the example sentence when it's split or inflected ("looking forward to", "take it off").
5. IPA and audio for phrases: whole-phrase IPA from the LLM, and TTS audio when Wiktionary has none.

## Open questions
- How common is this in real input lists?
- Should the error message at least explain that phrases aren't supported yet, until we decide?

## Decision (2026-10-21)

Phrases are accepted (max 50 characters, inner spaces collapsed) and kept as one entry. A phrase has no part of speech, IPA or audio; it gets a meaning, an example sentence and a practice card, and its notes are tagged `phrase`. See `docs/plans/research-step.md`.

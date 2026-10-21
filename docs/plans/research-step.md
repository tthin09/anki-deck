# Research step — Plan

Status: implemented 2026-10-21.

## Problem

1. A word with several meanings ("fine", "bank") gets one card for whichever meaning the AI picks.
2. Phrases ("as well as", "excessive amount") are rejected at input.

## Solution

Add a **Research** step between input and conversion. The AI lists the senses of every entry; the learner chooses which senses to convert. Terms are defined in `docs/context/CONTEXT.md` (vocabulary entry, phrase, research, sense, typo correction).

## Flow

1. Learner types up to 100 entries (words or phrases). Button: **Tìm từ**.
2. Research job: entries go to the AI in batches of 30 with `src/prompt/research-prompt.md`. Same job mechanism as conversion (progress events, heartbeat, cancel on leaving the page). Results do not survive a page reload.
3. The input is greyed and locked. A **← Sửa từ** link unlocks it; the next **Tìm từ** researches everything again from scratch.
4. Senses are shown as cards: entry + `(pos)` on the first line (no `(pos)` for phrases), Vietnamese meaning in italics below. Hover shows the sense's example sentence with the entry in bold.
   - Entry with ≥ 2 senses: its senses blink once; the first is selected, the rest unselected. Message: "N từ có nhiều hơn một nghĩa (X nghĩa thêm). Chọn nghĩa bạn muốn thêm vào Anki."
   - Entry with 1 sense: selected.
   - Corrected typo: blinks blue; hover bubble "Bạn ghi nhầm thành X, tôi đã tự sửa lại thành Y".
   - No sense found: one grey card "Không tìm thấy nghĩa", not selectable, skipped.
   - Unselected cards: grey/low opacity, slightly smaller. All cards clickable to toggle.
5. Button becomes **Tạo bộ thẻ**. No cap on chosen senses (100 entries × 4 max). Conversion uses only chosen senses.

## Conversion changes

- Input to card generation is a chosen sense (entry, part of speech, Vietnamese meaning, research example), not a bare word. `src/prompt/agent-prompt.md` must keep the given part of speech and meaning and write a **different** example sentence from the research one. `src/prompt/reverse-prompt.md` and `src/prompt/verify-prompt.md` likewise must not change the sense.
- Two chosen senses of one entry are two independent notes: drop `genanki.guid_for(tag, word)` so re-imports never overwrite. Audio is still fetched once per entry.
- Phrase: no part of speech, IPA or audio; gets meaning, example sentence and a practice card. Front shows the phrase alone; practice back shows the answer alone.
- Parser: allow spaces in an entry (still max 50 characters).

## Measured

Prompt test on the local Qwen model (2026-10-21):
- 10 mixed entries (fine, bank, recieve, as well as, lede, asdfgh, …): 21 s; typos corrected, rare word "lede" kept, gibberish → no senses, phrases → no part of speech.
- 30 typical study words: 9 s, **32 senses** (28 words × 1, advocate and schedule × 2). The feared 3–4 senses per word did not happen; only genuinely ambiguous words split.

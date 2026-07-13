---
name: write-update
description: Turn user-provided release bullets into a concise, natural-language changelog entry for this project. Use when the user invokes $write-update, asks to write release notes, or provides a list of updates for a new version.
---

# Write Update

Convert rough update bullets into a polished changelog entry and write it to the project's `CHANGELOG.md`.

## Workflow

1. Read `CHANGELOG.md` if it exists. Preserve existing entries and formatting.
2. Determine the heading:
   - Use a version and date explicitly supplied by the user.
   - Otherwise use the current version from `VERSION` if present.
   - Otherwise use `Unreleased`; do not invent a version number.
3. Rewrite the supplied bullets in natural, user-facing language. Keep the facts, remove implementation jargon, and group items under only the headings that apply: `Added`, `Changed`, `Fixed`, `Removed`, or `Notes`.
4. Put the newest entry at the top of `CHANGELOG.md`. Keep it concise; do not add features or claims that were not in the bullets.
5. If the user explicitly asks to bump the version, update `VERSION` with the requested version (or increment only the patch component when they explicitly say "bump patch"). Otherwise change only `CHANGELOG.md`.
6. Show the resulting entry and run a quick check that the file is readable. Commit every file changed, following this project's `AGENTS.md` instruction.

## Style

- Write in plain English with short, specific sentences.
- Prefer "Added support for ..." or "Fixed ..." over commit-message fragments.
- Keep technical names only when users need them (commands, model names, file formats).
- Do not include commit hashes, internal speculation, or a separate "What changed" preamble.

### Example

Input:

```text
- Added a retry when Gemini is busy
- Fixed the API key header
```

Output:

```markdown
## Unreleased

### Changed
- Added automatic retries when Gemini is temporarily unavailable.

### Fixed
- Corrected Gemini authentication by sending the API key in the required header.
```

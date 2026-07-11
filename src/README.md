# Anki Deck Generator

Windows application for turning newline-separated English vocabulary into two Anki cards per item:

1. A vocabulary card with meaning, IPA, example, synonyms, and pronunciation audio.
2. A reverse practice card that asks the learner to fill a missing word and plays the displayed answer on the back.

The packaged `run.exe` needs no Python installation, but it must be distributed with the complete folder.

## How it works

1. Read and deduplicate UTF-8 `.txt` files from `input/`.
2. Ask Gemini for vocabulary data and reverse practice sentences.
3. Resolve pronunciation media through DictionaryAPI, Wiktionary, then Google Translate TTS.
4. Write the review workbook to `vocabulary/`.
5. Send notes to the locally running AnkiConnect server. AnkiConnect downloads audio into Anki's media collection.

Every major phase logs when it starts and whether it completed or failed, including elapsed seconds. Status labels use a fixed-width column such as `[Đang chạy]` and `[OK       ]`. Audio lookup failures are non-fatal; the text-only card is still created only if every source fails.

Gemini calls time out after 30 seconds. Transient overload and connection failures retry automatically three times; each retry reprints the active batch with its elapsed time.

## Project layout

- `src/anki_deck.py` — application, diagnostics, and self-test.
- `src/agent-prompt.md` — Gemini vocabulary-card prompt.
- `src/reverse-prompt.md` — Gemini reverse-card prompt.
- `src/config.json` — local runtime configuration; never commit or distribute a real shared API key.
- `input/` — user vocabulary text files, one item per line.
- `vocabulary/template.xlsx` — workbook template.
- `run.exe` — PyInstaller Windows executable.
- `KIEM-TRA.cmd` — user-facing deployment diagnostics.

## External services

- **Gemini API:** generates structured card content. Each user supplies their own API key.
- **DictionaryAPI:** primary pronunciation source, paced at one uncached request every 2.5 seconds. Selection priority is US, UK/GB, then any HTTPS recording.
- **Wiktionary:** backup source; the app reads an English entry's HTTPS MP3 recording.
- **Google Translate TTS:** no-key final fallback for an exact word or phrase. This compatibility endpoint is free but not a supported developer API and may change or throttle.
- **AnkiConnect:** creates notes and downloads audio. Anki must be open with add-on `2055492159` installed.

Normal-card audio is attached to `Front`. Reverse-card audio is attached to `Back`; the exact displayed answer form is tried first, then the original vocabulary word. No audio source text is shown on cards. The app enables autoplay on the configured deck preset before adding notes.

AnkiConnect receives audio targets as field-name lists (`["Front"]` or `["Back"]`), allowing it to insert the native `[sound:...]` marker into the note.
The target field also contains local CSS that places Anki's native replay button on its own centered line.

## Run from source

Requirements: Python 3.12+, Anki, AnkiConnect, and a configured Gemini key.

```powershell
python -m pip install -r src\requirements.txt
python src\anki_deck.py --self-test --no-pause
python src\anki_deck.py --no-pause
```

Copy `src/config.example.json` to `src/config.json`, then replace `YOUR_OWN_GEMINI_API_KEY`. Do not expose the key in source control or a shared ZIP.

## Diagnostics

Run `KIEM-TRA.cmd` or:

```powershell
run.exe --diagnose --no-pause
```

This writes `bao-cao-kiem-tra.txt`, checks required files, input, workbook access, DictionaryAPI, Gemini, and AnkiConnect, and never adds cards. The report does not include the Gemini key.

## Migrate old cards to audio

Open Anki, then double-click `migrate.exe`. It scans all `tag:ai-vocab` notes without native `[sound:...]`, prints every word that will be migrated (including reverse/base-audio fallback), and requires `Y` before changing notes. Existing audio notes and unrelated cards are skipped. Results are written to `bao-cao-migrate.txt`.

```powershell
migrate.exe --dry-run --no-pause
migrate.exe --self-test --no-pause
```

Reverse answers try their displayed form first, then a unique normal-card base matched through common English inflections. Ambiguous, irregular, malformed, and audio-less notes are reported without modification. The migration is safe to rerun.

## Build `run.exe`

```powershell
python -m PyInstaller --onefile --console --name run --clean --noconfirm src\anki_deck.py
Copy-Item -Force dist\run.exe .\run.exe
```

Build the migration executable:

```powershell
python -m PyInstaller --onefile --console --name migrate --clean --noconfirm src\migrate_audio.py
Copy-Item -Force dist\migrate.exe .\migrate.exe
```

Verify the packaged artifact:

```powershell
.\run.exe --self-test --no-pause
.\run.exe --diagnose --no-pause
```

Distribute the whole project runtime folder as a ZIP, including `run.exe`, `src/`, `input/`, `vocabulary/template.xlsx`, `HUONG-DAN.txt`, and `KIEM-TRA.cmd`. The executable is unsigned, so Windows SmartScreen may warn users.

## Audio behavior

- Lookups are cached case-insensitively for one run.
- Media filenames are deterministic URL hashes, preventing unsafe characters and collisions.
- Only HTTPS audio URLs are accepted.
- DictionaryAPI 404, 429, network, and malformed-response failures continue to Wiktionary, then Google Translate TTS; remaining failures do not stop card creation.
- The app enables Anki's native autoplay for the configured deck preset; normal replay controls remain available and no custom model or JavaScript is required.

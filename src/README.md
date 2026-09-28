# Anki Deck Generator

Windows application for turning newline-separated English vocabulary into two Anki cards per item:

1. A vocabulary card with meaning, IPA, example, synonyms, and pronunciation audio.
2. A reverse practice card that asks the learner to fill a missing word and plays the displayed answer on the back.

The packaged `run.exe` needs no Python installation, but it must be distributed with the complete folder.

## How it works

1. Read and deduplicate UTF-8 `.txt` files from `input/`.
2. Ask Gemini for vocabulary data and reverse practice sentences.
3. Resolve pronunciation media through Wiktionary, then Google Translate TTS.
4. Write the review workbook and a self-contained `.apkg` with audio to `vocabulary/`. Package names use `ddmmyy-{index}-{word_count}words.apkg`; the count is the number of generated vocabulary entries, with two cards per word.
5. Import the `.apkg` into Anki through AnkiConnect. The package remains available if Anki is closed or import fails.

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
- `migrate.exe` — legacy-card audio migration executable.
- `update.cmd` — one-click user updater; no Git or Python required.
- `KIEM-TRA.cmd` — user-facing deployment diagnostics.

## External services

- **Gemini API:** generates structured card content. Each user supplies their own API key.
- **Wiktionary:** primary pronunciation source; the app reads an English entry's HTTPS MP3 recording.
- **Google Translate TTS:** no-key final fallback for an exact word or phrase. This compatibility endpoint is free but not a supported developer API and may change or throttle.
- **AnkiConnect:** imports the generated `.apkg` and applies the deck's autoplay setting. Anki must be open with add-on `2055492159` installed.

Generated `.apkg` files contain both card types and their audio, and can also be imported manually from Anki if AnkiConnect is unavailable.

Normal-card audio is attached to `Front`. Reverse-card audio is attached to `Back`; the exact displayed answer form is tried first, then the original vocabulary word. No audio source text is shown on cards. The app enables autoplay on the configured deck preset before importing the package.

The `.apkg` contains both card types and embeds local audio media. The sound marker is added to the normal card's `Front` and the reverse card's `Back`; local CSS places Anki's native replay button on its own centered line.

## Run from source

Requirements: Python 3.12+, Anki, AnkiConnect, and a configured Gemini key.

```powershell
python -m pip install -r src\requirements.txt
python src\anki_deck.py --self-test --no-pause
python src\anki_deck.py --no-pause
```

Copy `src/config.example.json` to `src/config.json`, then replace `YOUR_OWN_GEMINI_API_KEY`. Do not expose the key in source control or a shared ZIP.

## Update the packaged app

End users should close `run.exe` and `migrate.exe`, then double-click `update.cmd`. It downloads the latest `anki-deck-runtime.zip` release from GitHub using Windows PowerShell. Git, Python, and developer dependencies are not required. The updater preserves `src/config.json`, `input/`, and generated files in `vocabulary/`.

Maintainers publish a release by pushing a tag such as `v1.0.0`. GitHub Actions builds and self-tests both executables, then attaches the runtime ZIP to the GitHub release. Do not use `git pull` as the end-user update path because user configuration and input are local data.

## Diagnostics

Run `KIEM-TRA.cmd` or:

```powershell
run.exe --diagnose --no-pause
```

This writes `bao-cao-kiem-tra.txt`, checks required files, input, workbook access, audio download through Wiktionary/Google TTS, Gemini, and AnkiConnect, and never adds cards. The report does not include the Gemini key.

## Migrate old cards to audio

Open Anki, then double-click `migrate.exe`. It scans all `tag:ai-vocab` notes without native `[sound:...]`, downloads and validates replacement audio locally, prints every word that will be migrated (including reverse/base-audio fallback), and requires `Y` before changing notes. Existing audio notes and unrelated cards are skipped. Results are written to `bao-cao-migrate.txt`.

```powershell
migrate.exe --dry-run --no-pause
migrate.exe --self-test --no-pause
```

Reverse answers try their displayed form first, then a unique normal-card base matched through common English inflections. Ambiguous, irregular, malformed, and audio-less notes are reported without modification. The migration is safe to rerun.

## Build and publish (maintainers)

```powershell
python -m PyInstaller --onefile --console --name run --clean --noconfirm src\anki_deck.py
Copy-Item -Force dist\run.exe .\run.exe
```

Build the migration executable:

```powershell
python -m PyInstaller --onefile --console --name migrate --clean --noconfirm src\migrate_audio.py
Copy-Item -Force dist\migrate.exe .\migrate.exe
```

Verify the packaged artifacts:

```powershell
.\run.exe --self-test --no-pause
.\run.exe --diagnose --no-pause
.\migrate.exe --self-test --no-pause
```

The release workflow packages only runtime resources and `vocabulary/template.xlsx`; it never packages `src/config.json`, input files, or generated workbooks. The executable is unsigned, so Windows SmartScreen may warn users.

## Audio behavior

- Lookups are cached case-insensitively for one run.
- Media filenames are deterministic URL hashes, preventing unsafe characters and collisions.
- Only HTTPS MP3 audio URLs, plus extensionless URLs known to return MP3, are accepted. Other formats fall through to the next audio source because MP3 is the most portable mobile format.
- Wiktionary and audio-download 429/network failures continue to Google TTS; remaining failures do not stop card creation.
- Audio is downloaded and checked before package creation. The `.apkg` is saved before AnkiConnect is called, so it remains usable when Anki is closed or import fails.
- The app enables Anki's native autoplay for the configured deck preset; normal replay controls remain available.

If audio works on desktop but not mobile, enable sound/image syncing on both devices, complete the media sync, and run Anki's Check Media before testing playback.

# Web Anki Deck Generator — Plan

## Problem Statement

The current generator is a Windows executable that reads local text files, generates vocabulary cards, writes an `.apkg`, and attempts to import it into Anki. The user wants a local web application instead: users enter or drop vocabulary, inspect validation, convert it, and import the downloaded package themselves.

## Solution

Build a Vite frontend and FastAPI backend, run together in Docker on the user's local machine, and persist application data in a host-mounted directory outside the container. Require login for every user. A successful conversion generates and immediately downloads an `.apkg`; the backend also keeps an archival copy and records the conversion in a CSV. The app has no user-facing conversion history or later-download link.

## User Stories

1. As an authorized user, I want to log in with my username and password so only provisioned users can use the converter.
2. As the operator, I want to create and maintain accounts in a simple JSON file so I can manage the small set of users without a registration workflow.
3. As a user, I want to type or paste vocabulary into an editor so I can prepare a list without creating a file first.
4. As a user, I want to drop a `.txt` file onto the editor so its contents replace the editor text and I can review or edit them before converting.
5. As a user, I want blank lines and case-insensitive duplicates ignored so the preview matches the actual conversion input.
6. As a user, I want to see the unique word count and the words in first-seen order so I can verify what will be generated.
7. As a user, I want the app to enforce the 100-word maximum before conversion so requests stay within the agreed limit.
8. As a user, I want to start conversion with one action so I can generate my study deck without running a desktop executable.
9. As a user, I want to see a progress bar and live status lines matching the existing terminal output so I can understand what the backend is doing.
10. As a user, I want the completed `.apkg` to download automatically so I can import it into Anki myself.
11. As the operator, I want each generated `.apkg` retained outside the container so container restarts or rebuilds do not erase the archive.
12. As the operator, I want a CSV record of each completed package, uploader, timestamp, and vocabulary list so I can audit what was generated.
13. As a user, I want my dropped text file discarded after its contents are read so the server does not retain an unnecessary original upload.
14. As a user, I want the deck to contain the existing English–Vietnamese card types and audio so the web version preserves the current learning experience.

## Product Behavior

### Login and accounts

- Require username and password login; there is no separate shared access code and no public registration.
- The operator provisions accounts in a JSON file mounted from the host.
- Store password hashes, not plaintext passwords. Never return account data or password hashes to the browser.
- Use a server-managed secure session after successful login. Require an authenticated session for conversion and package delivery.
- Support logout and reject expired or invalid sessions.

### Vocabulary editor and validation

- Provide one notepad-like editor, not a conversational chat interface.
- Accept typed/pasted text and dropped `.txt` files. Dropping a file replaces the editor contents; the browser reads the file locally rather than uploading the source file separately.
- Parse one word per line, trim surrounding whitespace, ignore blank lines, and keep the first spelling and position of case-insensitive duplicates.
- Show the count and comma-separated list of unique words in first-seen order.
- Allow 1–100 unique words. Reject an empty list and more than 100 unique words in both the UI and backend; client validation is not a security boundary.
- Preserve the original spelling/capitalization of each first occurrence when sending words for generation.

### Conversion and download

- Convert using the existing English-to-Vietnamese prompts and card content: vocabulary card, reverse practice card, definitions, examples, synonyms, and pronunciation audio.
- Keep the current audio-source behavior, including non-fatal lookup failures where cards can still be generated without audio.
- Generate an `.apkg` only. Do not generate the Excel workbook or call AnkiConnect/import cards into Anki.
- Show a progress bar and append the existing terminal-style status text live beneath it. Include phases for generation, audio lookup, package creation, and completion/failure. Do not expose API keys or internal secrets in progress/error text.
- On success, immediately trigger a browser download of the package. Do not show a history page or a user-facing package link after the request completes.
- Keep the generated archive copy even if the client download is interrupted; users can rerun conversion if they did not receive the download.

### Persistent records and files

- Store all persistent files in a Docker-mounted host directory: the account JSON, generated package archive, and conversion CSV.
- Retain generated `.apkg` archives indefinitely. They are not exposed through a history or public file-serving interface.
- Append one CSV row after successful package creation. Include package filename, uploader, UTC creation timestamp, and the ordered unique vocabulary words used.
- Encode the vocabulary list as one properly quoted CSV field (JSON array text is suitable) so entries cannot corrupt CSV column structure.
- Do not retain the dropped `.txt` file. It is read by the browser and only its parsed vocabulary is submitted for conversion and recorded in the CSV.
- Ensure concurrent conversions cannot corrupt or lose CSV rows or overwrite each other's package files.

## Implementation Decisions

- **Frontend:** Vite application with login, vocabulary editor/drop target, live validation, conversion progress, and automatic download. Keep conversion history out of the UI.
- **Backend:** FastAPI owns authentication, input validation, conversion orchestration, progress reporting, package delivery, and persistence.
- **Generation boundary:** Reuse the current prompts and card/package logic, but separate deck generation from the current command-line flow so the web backend can generate an archive without invoking AnkiConnect. Inject or wrap Gemini/audio providers and progress reporting so conversion can be tested without real external services.
- **Progress transport:** Use a conversion job with one-way live progress events (Server-Sent Events is the recommended fit). The frontend displays the existing status lines as they arrive, then requests the completed package for immediate download. The user-facing UI does not retain a download link or history.
- **Authentication:** JSON account store with securely hashed passwords and an authenticated, HTTP-only session cookie. Keep session-signing secrets and the Gemini key outside source control and outside the container image.
- **Storage:** Host-mounted Docker volume; deterministic directories for archives and account/CSV data. Use collision-safe package names and serialized/locked CSV writes for concurrent requests.
- **No database:** A JSON account file and CSV audit log are sufficient for the current small, manually managed user set. Do not add a database or self-service account administration.
- **Local-first deployment:** Docker Compose (or equivalent one-command Docker setup) runs the frontend/backend and mounts persistent data. The current release is local-only; public hosting is a later phase requiring its own security and operations review.

## Testing Decisions

Test observable behavior at the highest useful seam: an authenticated conversion request through parsing, generation orchestration, archive/CSV persistence, progress events, and package response, with Gemini and audio providers replaced by deterministic fakes. Do not make automated tests call real Gemini, Wiktionary, Google TTS, or AnkiConnect.

- Test parsing and preview rules: whitespace, blank lines, case-insensitive duplicates, preserved first-seen order/spelling, empty input, 100 accepted, and 101 rejected.
- Test authentication: valid/invalid credentials, session creation and expiry, protected endpoints, logout, and absence of passwords/hashes in responses.
- Test conversion orchestration: the expected card types are packaged, progress messages are emitted, audio failures follow the existing non-fatal behavior, and AnkiConnect is never called.
- Test persistence: successful packages are archived, exactly one CSV row is appended with the correct uploader/time/words, package names do not collide, and concurrent writes do not corrupt records.
- Test failure behavior: provider or packaging failure does not create a successful conversion record or send a partial package; the UI receives a useful terminal-style error without secrets.
- Test the API and browser flow end-to-end with fake generation providers, including immediate download after completion and no history/list endpoint exposed to users.
- Test Docker persistence by recreating the container and verifying accounts, CSV, and archived packages remain in the mounted host directory.
- Prior art: the current generator has `run_self_test()` assertions and a test script that exercises generation against Anki. Adapt the useful generation checks, but replace real-Anki integration in the web application's automated tests with fakes.
- Manual acceptance: log in as each provisioned user; edit text and drop a `.txt` file; verify replacement, count/list, and limit; convert a small list; observe live progress; download and import the `.apkg` manually in Anki; verify archive/CSV persistence after container recreation.

## Delivery Phases

1. **Extract reusable generation:** separate vocabulary-to-package generation from CLI prompts, workbook generation, and AnkiConnect import; preserve existing package/card/audio behavior and cover it with isolated tests.
2. **Build backend:** add FastAPI, authentication, server-side Gemini configuration, input validation, conversion orchestration/progress, archive persistence, and CSV logging.
3. **Build frontend:** implement login, editor and `.txt` drop-replacement, live count/list and limit validation, progress display, and automatic package download.
4. **Package and verify locally:** add Docker setup with host-mounted persistent data; run backend/frontend tests and end-to-end manual acceptance.
5. **Public deployment later:** out of this delivery. Before enabling public access, review TLS/proxy configuration, abuse/rate limits, backups, storage growth, and account/session operations.

## Acceptance Criteria

- A non-logged-in visitor cannot convert or download a package.
- An operator-provisioned account can log in; a failed login reveals no sensitive account data.
- Typing or dropping a `.txt` updates the editor correctly; dropping replaces rather than appends.
- The displayed list and count equal the ordered, case-insensitive-deduplicated input, with no more than 100 unique words accepted.
- A valid conversion shows live terminal-style progress and produces a valid `.apkg` with the existing card types and available audio.
- The browser downloads the `.apkg` automatically; no AnkiConnect import or Excel workbook is produced.
- The archive and CSV survive container recreation; the CSV contains the correct account, UTC time, package name, and exact conversion vocabulary.
- No user-facing history or later-download link is provided, and the original `.txt` is not retained by the server.
- Automated tests run without Gemini, audio-provider, or AnkiConnect credentials/network access.

## Out of Scope

- Public internet deployment, user self-registration, password reset UI, and user-managed accounts.
- User-facing conversion history or later downloads.
- Automatic import into Anki, AnkiConnect integration, and Excel workbook output.
- Retaining source `.txt` files or adding a database.
- More than 100 unique words per conversion.
- Changes to the current Anki card content beyond adapting it for the web workflow.

### [2026-07-14] - Wikimedia audio download throttling
* **Status:** Documented; implementation intentionally unchanged.
* **Changed:** Recorded the failure mode where a valid Wikimedia Commons transcoded MP3 URL returns HTTP 429 during AnkiConnect media download.
* **Context:** For `bookshelf`, the selected URL is a Wikimedia Commons WAV-to-MP3 transcode. The application currently trusts the URL metadata and passes the remote URL to AnkiConnect. AnkiConnect performs the download later, receives `429 Too Many Requests`, and cannot attach playable media; the resulting card has no replay button.
* **Touched:** `knowledge-base/docs/audio-429/context.md`, `knowledge-base/docs/INDEX.md`
* **Interfaces:** Current card audio payload remains AnkiConnect's remote `{url, filename, fields}` form. No application interface was changed.
* **Verified:** Failure message reviewed against the current `audio_metadata`, `wiktionary_audio`, `anki_note`, and AnkiConnect flow.
* **Follow-ups:** Implement the proposed media prefetch/retry design in a separate change.

## Proposed solution

Prefer application-owned media download before creating notes:

1. Download the selected audio URL in the application with a descriptive Wikimedia-compliant `User-Agent`.
2. On HTTP 429, honor `Retry-After` when present, otherwise use bounded exponential backoff with a small maximum retry count.
3. Validate the response status, content type, and non-empty body before accepting the audio.
4. If Wikimedia still fails, discard that candidate and continue to the next audio source, ending with Google TTS as the existing MP3-compatible fallback.
5. Store validated bytes in AnkiConnect with `storeMediaFile` using base64 data, then reference the deterministic filename in the note field. This prevents AnkiConnect from making an unthrottled remote request.
6. Log the source, HTTP status, retry delay, and final fallback decision so a missing button is explainable.

Do not solve this by blindly changing `.wav`/`.ogg` extensions or by retrying indefinitely. Wikimedia Commons supports multiple audio formats and automatic transcoding, but the app still needs a verified MP3-compatible payload for mobile playback.

Wikimedia documents rate limits for both API metadata and CDN media retrieval in [its rate-limit FAQ](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits/FAQ). HTTP 429 means the request was rate-limited and should be retried according to server guidance. [AnkiConnect's media documentation](https://github.com/FooSoft/anki-connect) supports storing base64-encoded media with `storeMediaFile`, while its note audio form downloads a remote URL during note creation.

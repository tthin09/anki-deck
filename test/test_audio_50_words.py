"""Live smoke test for pronunciation audio on 50 common English words."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anki_deck import anki, anki_note, google_tts_audio, resolve_audio  # noqa: E402


WORDS = """apple book cat dog easy family green house idea jump
kind light morning night open people quick red school time
under very water year young able bring change do every find
good help important job keep learn make new old place run say see take tell think use want work""".split()
DECK = "English Vocab [Test]"
TAG = "audio-50-test"


def verify_audio(url: str) -> None:
    request = Request(url, headers={"User-Agent": "anki-deck/1.0 (audio smoke test)"})
    with urlopen(request, timeout=20) as response:
        if not response.read(1):
            raise RuntimeError("audio response was empty")


def add_to_test_deck(audio_by_word: dict[str, dict], config: dict) -> int:
    anki("version", None, config)
    anki("createDeck", {"deck": DECK}, config)

    deck_config = anki("getDeckConfig", {"deck": DECK}, config)
    deck_config.setdefault("new", {})["perDay"] = 200
    if anki("saveDeckConfig", {"config": deck_config}, config) is not True:
        raise RuntimeError("AnkiConnect could not save the 200 new-cards/day limit")

    notes = [
        anki_note(DECK, word, "Audio test", [TAG], audio_by_word[word], "Front")
        for word in WORDS
    ]
    allowed = anki("canAddNotes", {"notes": notes}, config)
    new_notes = [note for note, can_add in zip(notes, allowed) if can_add]
    if new_notes:
        result = anki("addNotes", {"notes": new_notes}, config)
        if not all(result):
            raise RuntimeError("AnkiConnect failed to add one or more test notes")

    note_ids = anki("findNotes", {"query": f'deck:"{DECK}" tag:{TAG}'}, config)
    if len(note_ids) < len(WORDS):
        raise RuntimeError(f"test deck contains {len(note_ids)}/{len(WORDS)} notes")
    return len(new_notes)


def main() -> int:
    if len(WORDS) != 50:
        raise AssertionError(f"expected 50 words, got {len(WORDS)}")

    passed = 0
    audio_by_word = {}
    for word in WORDS:
        try:
            audio = resolve_audio(word)
            if not audio:
                raise RuntimeError("no audio URL returned")
            try:
                verify_audio(audio["url"])
            except Exception:
                fallback = google_tts_audio(word)
                verify_audio(fallback["url"])
                audio = fallback
            audio_by_word[word] = audio
            passed += 1
            print(f"[OK] {word}: {audio['url']}")
        except Exception as exc:
            print(f"[FAIL] {word}: {exc}")

    print(f"\nAudio available: {passed}/{len(WORDS)}")
    if passed != len(WORDS):
        return 1

    try:
        added = add_to_test_deck(audio_by_word, {"anki_connect_url": "http://127.0.0.1:8765"})
        print(f"Deck: {DECK}; added {added} new notes; new cards/day: 200")
    except Exception as exc:
        print(f"[FAIL] AnkiConnect: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

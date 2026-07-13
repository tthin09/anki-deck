"""Generate complete AI flashcards and add N of the test words to Anki."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anki_deck import (  # noqa: E402
    add_to_anki,
    anki,
    chunks,
    enrich_audio,
    gemini_cards,
    gemini_reverse_cards,
    google_tts_audio,
    load_config,
    shuffled,
    src_dir,
)


WORDS = """apple book cat dog easy family green house idea jump
kind light morning night open people quick red school time
under very water year young able bring change do every find
good help important job keep learn make new old place run say see take tell think use want work""".split()
DECK = "English Vocab [Test]"


def verify_audio(url: str) -> None:
    request = Request(url, headers={"User-Agent": "anki-deck/1.0 (audio smoke test)"})
    with urlopen(request, timeout=20) as response:
        if not response.read(1):
            raise RuntimeError("audio response was empty")


def recreate_test_deck(config: dict) -> None:
    anki("version", None, config)
    if DECK in anki("deckNames", None, config):
        anki("deleteDecks", {"decks": [DECK], "cardsToo": True}, config)
    anki("createDeck", {"deck": DECK}, config)
    deck_config = anki("getDeckConfig", {"deck": DECK}, config)
    deck_config.setdefault("new", {})["perDay"] = 200
    if anki("saveDeckConfig", {"config": deck_config}, config) is not True:
        raise RuntimeError("AnkiConnect could not save the 200 new-cards/day limit")


def verify_card_audio(cards: list[dict]) -> None:
    for card in cards:
        audio = card.get("audio")
        if not audio:
            raise RuntimeError(f"no audio returned for '{card['word']}'")
        try:
            verify_audio(audio["url"])
        except Exception:
            fallback = google_tts_audio(card["word"])
            verify_audio(fallback["url"])
            card["audio"] = fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate N complete test flashcards and add them to Anki.")
    parser.add_argument("number", type=int, help=f"number of words to generate (1-{len(WORDS)})")
    args = parser.parse_args()
    if not 1 <= args.number <= len(WORDS):
        parser.error(f"number must be between 1 and {len(WORDS)}")

    config = load_config(ROOT)
    recreate_test_deck(config)
    words = shuffled(WORDS[: args.number])
    prompt = (src_dir(ROOT) / "agent-prompt.md").read_text(encoding="utf-8")
    reverse_prompt = (src_dir(ROOT) / "reverse-prompt.md").read_text(encoding="utf-8")

    cards = []
    for batch in chunks(words, int(config["chunk_size"])):
        cards.extend(gemini_cards(batch, prompt, config))

    reverse_cards = []
    for batch in chunks(cards, int(config["chunk_size"])):
        reverse_cards.extend(gemini_reverse_cards(batch, reverse_prompt, config))

    enrich_audio(cards, reverse_cards)
    verify_card_audio(cards)
    test_config = {**config, "deck_name": DECK}
    added = add_to_anki(cards, reverse_cards, test_config)
    print(f"Added {added} complete notes for {args.number} words to '{DECK}'.")
    print("Deck new cards/day: 200")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

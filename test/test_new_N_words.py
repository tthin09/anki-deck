"""Generate complete AI flashcards and add N of the test words to Anki."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anki_deck import (  # noqa: E402
    anki,
    check_anki,
    generate_and_add,
    load_config,
    msg,
    shuffled,
    src_dir,
    timed_step,
)


WORDS = """apple book cat dog easy family green house idea jump
kind light morning night open people quick red school time
under very water year young able bring change do every find
good help important job keep learn make new old place run say see take tell think use want work""".split()
DECK = "English Vocab [Test]"


def recreate_test_deck(config: dict) -> None:
    if DECK in anki("deckNames", None, config):
        anki("deleteDecks", {"decks": [DECK], "cardsToo": True}, config)
    anki("createDeck", {"deck": DECK}, config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate N complete test flashcards and add them to Anki.")
    parser.add_argument("number", type=int, help=f"number of words to generate (1-{len(WORDS)})")
    args = parser.parse_args()
    if not 1 <= args.number <= len(WORDS):
        parser.error(f"number must be between 1 and {len(WORDS)}")

    msg("Lưu ý", "Hãy lưu và đóng tất cả file .txt trong thư mục input trước khi tiếp tục.")
    with timed_step("Đọc cấu hình"):
        config = load_config(ROOT)
    with timed_step("Đọc file input và prompt"):
        words = shuffled(WORDS[: args.number])
        prompt = (src_dir(ROOT) / "agent-prompt.md").read_text(encoding="utf-8")
        reverse_prompt = (src_dir(ROOT) / "reverse-prompt.md").read_text(encoding="utf-8")
    with timed_step("Kiểm tra Anki và AnkiConnect"):
        check_anki(config)
    recreate_test_deck(config)
    generate_and_add(ROOT, config, words, prompt, reverse_prompt, DECK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

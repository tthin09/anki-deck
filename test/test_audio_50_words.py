"""Live smoke test for pronunciation audio on 50 common English words."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anki_deck import resolve_audio  # noqa: E402


WORDS = """apple book cat dog easy family green house idea jump
kind light morning night open people quick red school time
under very water year young able bring change do every find
good help important job keep learn make new old place run say see take tell think use want work""".split()


def verify_audio(url: str) -> None:
    request = Request(url, headers={"User-Agent": "anki-deck/1.0 (audio smoke test)"})
    with urlopen(request, timeout=20) as response:
        if not response.read(1):
            raise RuntimeError("audio response was empty")


def main() -> int:
    if len(WORDS) != 50:
        raise AssertionError(f"expected 50 words, got {len(WORDS)}")

    passed = 0
    for word in WORDS:
        try:
            audio = resolve_audio(word)
            if not audio:
                raise RuntimeError("no audio URL returned")
            verify_audio(audio["url"])
            passed += 1
            print(f"[OK] {word}: {audio['url']}")
        except Exception as exc:
            print(f"[FAIL] {word}: {exc}")

    print(f"\nAudio available: {passed}/{len(WORDS)}")
    return 0 if passed == len(WORDS) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run research on 30 typical study words against the real AI and report how many senses come back.

Re-run after changing src/research-prompt.md. Needs LLM_BASE_URL (default http://localhost:8000)
or GEMINI_API_KEY for the fallback.

    python script/research-check.py
"""
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import anki_deck  # noqa: E402

WORDS = ["combination", "advocate", "environment", "reluctant", "negotiate", "significant", "apple", "library",
         "curious", "maintain", "abundant", "schedule", "gratitude", "fragile", "obvious", "contribute", "persuade",
         "ambitious", "inevitable", "temporary", "generous", "accurate", "emphasize", "dilemma", "transparent",
         "illustrate", "vivid", "sustain", "hesitate", "perspective"]

config = {"gemini_api_key": os.environ.get("GEMINI_API_KEY", ""), "model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
          "llm_base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8000"), "chunk_size": 30}
started = time.perf_counter()
found = anki_deck.research_entries(WORDS, (ROOT / "src" / "research-prompt.md").read_text(encoding="utf-8"), config)
counts = Counter(len(item["senses"]) for item in found)
print(f"\n{len(found)} words -> {sum(len(item['senses']) for item in found)} senses in {time.perf_counter() - started:.0f}s")
print("words by number of senses:", dict(sorted(counts.items())))
for item in found:
    if len(item["senses"]) != 1:
        print(f"  {item['entry']}: " + " | ".join(f"({s['part_of_speech']}) {s['vietnamese_meaning']}" for s in item["senses"]))

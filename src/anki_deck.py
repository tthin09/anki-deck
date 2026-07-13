from __future__ import annotations

import argparse
import html
import hashlib
import json
import random
import re
import socket
import sys
import tempfile
import time
from contextlib import contextmanager, redirect_stdout
from copy import copy
from datetime import datetime
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import openpyxl

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "part_of_speech": {"type": "string"},
                    "ipa": {"type": "string"},
                    "vietnamese_meaning": {"type": "string"},
                    "word_forms": {"type": "string"},
                    "example_sentence": {"type": "string"},
                    "synonyms": {"type": "array", "items": {"type": "string"}},
                    "anki_front_html": {"type": "string"},
                    "anki_back_html": {"type": "string"},
                },
                "required": [
                    "word",
                    "part_of_speech",
                    "ipa",
                    "vietnamese_meaning",
                    "word_forms",
                    "example_sentence",
                    "synonyms",
                    "anki_front_html",
                    "anki_back_html",
                ],
            },
        }
    },
    "required": ["cards"],
}


REVERSE_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "sentence": {"type": "string"},
                    "vietnamese_hint": {"type": "string"},
                },
                "required": ["word", "sentence", "vietnamese_hint"],
            },
        }
    },
    "required": ["cards"],
}


AUDIO_BUTTON_STYLE = "<style>.replay-button{display:block!important;text-align:center;margin-top:12px}</style>"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    path = Path(__file__).resolve()
    return path.parent.parent if path.parent.name == "src" else path.parent


def src_dir(root: Path) -> Path:
    return root / "src"


def msg(kind: str, text: str) -> None:
    print(f"[{kind:<9}] {text}", flush=True)


_active_step: tuple[str, float] | None = None


@contextmanager
def timed_step(text: str):
    global _active_step
    started = time.perf_counter()
    previous = _active_step
    _active_step = (text, started)
    msg("Đang chạy", text)
    try:
        yield
    except Exception:
        msg("Lỗi", f"{text} thất bại sau {time.perf_counter() - started:.1f} giây.")
        raise
    else:
        msg("OK", f"{text} hoàn tất trong {time.perf_counter() - started:.1f} giây.")
    finally:
        _active_step = previous


def log_step_progress() -> None:
    if _active_step:
        text, started = _active_step
        msg("Đang chạy", f"{text} ({time.perf_counter() - started:.1f}s)")


def load_config(root: Path) -> dict:
    path = src_dir(root) / "config.json"
    if not path.exists():
        raise RuntimeError("Không tìm thấy src/config.json. Hãy tạo file này từ src/config.example.json.")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Không đọc được src/config.json. Hãy kiểm tra file JSON và quyền truy cập.") from exc
    if not config.get("groq_api_key") or config["groq_api_key"].startswith("YOUR_"):
        raise RuntimeError("Chưa cấu hình groq_api_key trong config.json.")
    config.setdefault("model", "openai/gpt-oss-20b")
    config.setdefault("deck_name", "English Vocabulary")
    config.setdefault("anki_connect_url", "http://127.0.0.1:8765")
    config.setdefault("chunk_size", 30)
    return config


def read_words(input_dir: Path) -> list[str]:
    if not input_dir.exists():
        raise RuntimeError("Không tìm thấy thư mục input.")
    words: list[str] = []
    seen: set[str] = set()
    for path in sorted(input_dir.glob("*.txt")):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except PermissionError as exc:
            raise RuntimeError(
                "Hãy điền từ vựng vào notepad, lưu, và đóng file đó lại trước."
            ) from exc
        except UnicodeError as exc:
            raise RuntimeError(f"{path.name} không phải file UTF-8 hợp lệ.") from exc
        for line in lines:
            word = line.strip()
            key = word.casefold()
            if word and key not in seen:
                seen.add(key)
                words.append(word)
    if not words:
        raise RuntimeError("Hãy điền từ vựng vào notepad, lưu, và đóng file đó lại trước.")
    return words


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def shuffled(items: list[str]) -> list[str]:
    items = items[:]
    random.shuffle(items)
    return items


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gọi API thất bại ({exc.code}): {body[:500]}") from exc
    except (URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
        raise RuntimeError(f"Không thể kết nối tới dịch vụ: {exc}") from exc


def get_json(url: str, timeout: int = 20):
    try:
        with urlopen(Request(url, headers={"User-Agent": "anki-deck/1.0"}), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"DictionaryAPI trả về lỗi {exc.code}.") from exc
    except (URLError, TimeoutError, ConnectionError, socket.timeout, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Không đọc được DictionaryAPI: {exc}") from exc


def select_audio(entries) -> dict | None:
    candidates = []
    for entry in entries if isinstance(entries, list) else []:
        for phonetic in entry.get("phonetics", []) if isinstance(entry, dict) else []:
            if not isinstance(phonetic, dict):
                continue
            url = str(phonetic.get("audio") or "").strip()
            audio = audio_metadata(url)
            if not audio:
                continue
            marker = urlparse(audio["url"]).path.casefold()
            rank = 0 if re.search(r"(?:^|[-_/.])us(?:[-_/.]|$)", marker) else 1 if re.search(r"(?:^|[-_/.])(uk|gb)(?:[-_/.]|$)", marker) else 2
            candidates.append((rank, audio["url"]))
    if not candidates:
        return None
    _, url = min(candidates, key=lambda item: item[0])
    return audio_metadata(url)


def audio_metadata(url: str) -> dict | None:
    url = html.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix and suffix != ".mp3":
        return None
    suffix = ".mp3"
    return {
        "url": url,
        "filename": f"vocab_{hashlib.sha256(url.encode()).hexdigest()[:16]}{suffix}",
    }


def dictionary_audio(text: str) -> dict | None:
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(text, safe='')}"
    return select_audio(get_json(url))


def wiktionary_audio_from_html(page: str) -> dict | None:
    english = re.search(r'<h2 id="English">.*?(?=<h2|\Z)', page, flags=re.DOTALL)
    if not english:
        return None
    for url in re.findall(r'<source src="([^"]+)" type="audio/mpeg"', english.group(0)):
        audio = audio_metadata(url)
        if audio:
            return audio
    return None


def wiktionary_audio(text: str) -> dict | None:
    url = f"https://en.wiktionary.org/w/rest.php/v1/page/{quote(text, safe='')}/html"
    try:
        with urlopen(Request(url, headers={"User-Agent": "anki-deck/1.0 (audio lookup)"}), timeout=20) as response:
            return wiktionary_audio_from_html(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Wiktionary trả về lỗi {exc.code}.") from exc
    except (URLError, TimeoutError, ConnectionError, socket.timeout, UnicodeError) as exc:
        raise RuntimeError(f"Không đọc được Wiktionary: {exc}") from exc


def google_tts_audio(text: str) -> dict | None:
    url = "https://translate.googleapis.com/translate_tts?ie=UTF-8&client=tw-ob&tl=en-US&q=" + quote(text)
    return audio_metadata(url)


def resolve_audio(text: str, sources=None) -> dict | None:
    for source in sources or (dictionary_audio, wiktionary_audio, google_tts_audio):
        try:
            audio = source(text)
        except RuntimeError:
            continue
        if audio:
            return audio
    return None


def enrich_audio(cards: list[dict], reverse_cards: list[dict]) -> None:
    cache: dict[str, dict | None] = {}
    next_dictionary_request = 0.0

    def paced_dictionary_audio(text: str) -> dict | None:
        nonlocal next_dictionary_request
        delay = next_dictionary_request - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        next_dictionary_request = time.monotonic() + 2.5
        return dictionary_audio(text)

    def lookup(text: str) -> dict | None:
        key = text.casefold()
        if key not in cache:
            cache[key] = resolve_audio(text, (paced_dictionary_audio, wiktionary_audio, google_tts_audio))
        return cache[key]

    by_word = {}
    for card in cards:
        card["audio"] = lookup(card["word"])
        if card["audio"] is None:
            msg("Cảnh báo", f"Không tìm thấy audio cho '{card['word']}'. Thẻ vẫn được tạo không có âm thanh.")
        by_word[card["word"].casefold()] = card["audio"]
    for reverse in reverse_cards:
        reverse["audio"] = lookup(reverse["answer"]) or by_word.get(reverse["word"].casefold())
        if reverse["audio"] is None:
            msg("Cảnh báo", f"Không tìm thấy audio cho đáp án '{reverse['answer']}'.")


def is_busy_ai_error(exc: RuntimeError) -> bool:
    return "Không thể kết nối" in str(exc) or any(f"({code})" in str(exc) for code in (429, 500, 502, 503, 504))


def groq_json(items: list[dict | str], prompt: str, schema: dict, config: dict) -> dict:
    model = config["model"]
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt
                + "\n\nReturn only valid JSON. Input data as JSON array:\n"
                + json.dumps(items, ensure_ascii=False),
            }
        ],
    }
    last_error = None
    for attempt in range(4):
        try:
            response = post_json(
                url,
                payload,
                headers={
                    "Authorization": f"Bearer {config['groq_api_key']}",
                    "User-Agent": "anki-deck/1.0",
                },
                timeout=30,
            )
            break
        except RuntimeError as exc:
            last_error = exc
            if attempt == 3 or not is_busy_ai_error(exc):
                raise RuntimeError(f"Groq API không xác thực được hoặc đã thất bại: {exc}") from exc
            log_step_progress()
            msg("Đang chạy", f"Dịch vụ AI đang quá tải. Tự động thử lại lần {attempt + 1}/3...")
            time.sleep(2 * (attempt + 1))
    else:
        raise last_error
    try:
        text = response["choices"][0]["message"]["content"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI trả về dữ liệu không đọc được. Chưa thêm thẻ vào Anki.") from exc


def groq_cards(words: list[str], prompt: str, config: dict) -> list[dict]:
    data = groq_json(words, prompt, CARD_SCHEMA, config)
    return validate_cards(data)


def groq_reverse_cards(cards: list[dict], prompt: str, config: dict) -> list[dict]:
    items = [
        {
            "word": card["word"],
            "part_of_speech": card["part_of_speech"],
            "vietnamese_meaning": card["vietnamese_meaning"],
            "word_forms": card["word_forms"],
            "example_sentence": card["example_sentence"],
        }
        for card in cards
    ]
    data = groq_json(items, prompt, REVERSE_SCHEMA, config)
    return validate_reverse_cards(cards, data)


def validate_cards(data: dict) -> list[dict]:
    cards = data.get("cards")
    if not isinstance(cards, list) or not cards:
        raise RuntimeError("AI không trả về danh sách thẻ hợp lệ. Chưa thêm thẻ vào Anki.")
    required = set(CARD_SCHEMA["properties"]["cards"]["items"]["required"])
    for card in cards:
        if not isinstance(card, dict) or required - card.keys():
            raise RuntimeError("AI trả về thẻ thiếu dữ liệu. Chưa thêm thẻ vào Anki.")
        if not isinstance(card["synonyms"], list):
            raise RuntimeError("AI trả về synonyms không hợp lệ. Chưa thêm thẻ vào Anki.")
    return cards


def normalize_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"</?str>", "", text).strip()).casefold()


def answer_text(sentence: str) -> str:
    matches = re.findall(r"<str>(.*?)</str>", sentence, flags=re.IGNORECASE | re.DOTALL)
    if len(matches) != 1 or not matches[0].strip():
        raise RuntimeError("AI trả về câu luyện tập không hợp lệ. Chưa thêm thẻ vào Anki.")
    return matches[0].strip()


def blank_for(answer: str) -> str:
    length = max(1, len(re.sub(r"\s+", "", answer)))
    blank_len = min(length, max(3, int(length * random.uniform(0.60, 0.80))))
    return "_" * blank_len


def make_reverse_note(card: dict, reverse: dict) -> dict:
    answer = answer_text(reverse["sentence"])
    front = re.sub(
        r"<str>.*?</str>",
        f"{blank_for(answer)} ({reverse['vietnamese_hint']})",
        reverse["sentence"],
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    keyword = f"{answer} ({card['part_of_speech']})"
    return {"front": front, "back": keyword, "keyword": keyword, "word": card["word"], "answer": answer}


def validate_reverse_cards(cards: list[dict], data: dict) -> list[dict]:
    reverse_cards = data.get("cards")
    if not isinstance(reverse_cards, list) or len(reverse_cards) != len(cards):
        raise RuntimeError("AI không trả về đủ câu luyện tập. Chưa thêm thẻ vào Anki.")
    by_word = {card["word"].casefold(): card for card in cards}
    validated = []
    for reverse in reverse_cards:
        if not isinstance(reverse, dict) or {"word", "sentence", "vietnamese_hint"} - reverse.keys():
            raise RuntimeError("AI trả về câu luyện tập thiếu dữ liệu. Chưa thêm thẻ vào Anki.")
        card = by_word.get(str(reverse["word"]).casefold())
        if not card:
            raise RuntimeError("AI trả về câu luyện tập cho từ không có trong danh sách. Chưa thêm thẻ vào Anki.")
        answer_text(reverse["sentence"])
        if normalize_sentence(reverse["sentence"]) == normalize_sentence(card["example_sentence"]):
            raise RuntimeError("AI trả về câu luyện tập trùng câu ví dụ. Chưa thêm thẻ vào Anki.")
        validated.append(make_reverse_note(card, reverse))
    return validated


def next_excel_path(vocabulary_dir: Path) -> Path:
    vocabulary_dir.mkdir(exist_ok=True)
    prefix = datetime.now().strftime("%d%m%y")
    ids = []
    for path in vocabulary_dir.glob(f"{prefix}-*.xlsx"):
        match = re.fullmatch(rf"{prefix}-(\d{{2}})\.xlsx", path.name)
        if match:
            ids.append(int(match.group(1)))
    next_id = max(ids, default=0) + 1
    if next_id > 99:
        raise RuntimeError("Hôm nay đã tạo 99 file Excel. Hãy xoá bớt file hoặc chạy lại vào ngày khác.")
    return vocabulary_dir / f"{prefix}-{next_id:02d}.xlsx"


def copy_row_style(ws, source_row: int, target_row: int, max_col: int = 6) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, max_col + 1):
        src = ws.cell(source_row, col)
        dst = ws.cell(target_row, col)
        dst._style = copy(src._style)
        if src.has_style:
            dst.font = copy(src.font)
            dst.fill = copy(src.fill)
            dst.border = copy(src.border)
            dst.alignment = copy(src.alignment)
            dst.number_format = src.number_format


def write_excel(root: Path, cards: list[dict], reverse_cards: list[dict]) -> Path:
    vocabulary_dir = root / "vocabulary"
    template = vocabulary_dir / "template.xlsx"
    if not template.exists():
        raise RuntimeError("Không tìm thấy vocabulary/template.xlsx.")
    wb = openpyxl.load_workbook(template)
    ws = wb.active
    for row in range(2, ws.max_row + 1):
        for col in range(1, 7):
            ws.cell(row, col).value = None
    for index, card in enumerate(cards, start=1):
        row = index + 1
        if row > ws.max_row:
            copy_row_style(ws, 2, row)
        ws.cell(row, 1).value = index
        ws.cell(row, 2).value = card["word"]
        ws.cell(row, 3).value = card["part_of_speech"]
        ws.cell(row, 4).value = card["vietnamese_meaning"]
        ws.cell(row, 5).value = card["word_forms"]
        ws.cell(row, 6).value = card["example_sentence"]
    if "Reverse" in wb.sheetnames:
        del wb["Reverse"]
    reverse_ws = wb.create_sheet("Reverse")
    reverse_ws.append(["No", "Sentence", "Keyword"])
    for col in range(1, 4):
        reverse_ws.cell(1, col)._style = copy(ws.cell(1, min(col, 3))._style)
    for index, reverse in enumerate(reverse_cards, start=1):
        reverse_ws.append([index, reverse["front"], reverse["keyword"]])
    reverse_ws.column_dimensions["A"].width = 11
    reverse_ws.column_dimensions["B"].width = 80
    reverse_ws.column_dimensions["C"].width = 24
    output = next_excel_path(vocabulary_dir)
    wb.save(output)
    return output


def anki(action: str, params: dict | None, config: dict) -> dict:
    payload = {"action": action, "version": 6, "params": params or {}}
    try:
        response = post_json(config["anki_connect_url"], payload, timeout=15)
    except RuntimeError as exc:
        if "Không thể kết nối" in str(exc):
            raise RuntimeError(
                "Không kết nối được AnkiConnect. Hãy mở Anki, cài add-on 2055492159 và kiểm tra cổng 8765."
            ) from exc
        raise
    if response.get("error"):
        raise RuntimeError(str(response["error"]))
    return response.get("result")


def anki_note(deck: str, front: str, back: str, tags: list[str], audio: dict | None, audio_field: str) -> dict:
    note = {
        "deckName": deck,
        "modelName": "Basic",
        "fields": {"Front": front, "Back": back},
        "tags": tags,
    }
    if audio:
        note["fields"][audio_field] += AUDIO_BUTTON_STYLE
        note["audio"] = {
            "url": audio["url"],
            "filename": audio["filename"],
            "fields": [audio_field],
        }
    return note


def enable_anki_autoplay(deck: str, config: dict) -> None:
    try:
        deck_config = anki("getDeckConfig", {"deck": deck}, config)
        if not isinstance(deck_config, dict):
            raise RuntimeError("AnkiConnect trả về cấu hình bộ thẻ không hợp lệ.")
        if deck_config.get("autoplay") is True:
            return
        deck_config["autoplay"] = True
        if anki("saveDeckConfig", {"config": deck_config}, config) is not True:
            raise RuntimeError("Anki không lưu được cấu hình tự động phát audio.")
    except RuntimeError as exc:
        raise RuntimeError(
            "Không thể bật tự động phát audio trong Anki. Hãy kiểm tra AnkiConnect rồi chạy lại."
        ) from exc


def add_to_anki(cards: list[dict], reverse_cards: list[dict], config: dict) -> int:
    anki("version", None, config)
    deck = config["deck_name"]
    anki("createDeck", {"deck": deck}, config)
    enable_anki_autoplay(deck, config)
    normal_notes = [
        anki_note(deck, card["anki_front_html"], card["anki_back_html"], ["ai-vocab"], card.get("audio"), "Front")
        for card in shuffled(cards)
    ]
    reverse_notes = [
        anki_note(deck, reverse["front"], reverse["back"], ["ai-vocab", "reverse"], reverse.get("audio"), "Back")
        for reverse in shuffled(reverse_cards)
    ]
    notes = []
    for batch in (normal_notes, reverse_notes):
        allowed = anki("canAddNotes", {"notes": batch}, config)
        notes.extend(note for note, ok in zip(batch, allowed) if ok)
    if not notes:
        raise RuntimeError("Không có thẻ mới để thêm vào Anki. Có thể các thẻ này đã tồn tại.")
    result = anki("addNotes", {"notes": notes}, config)
    return len([note_id for note_id in result if note_id])


def run_self_test() -> None:
    sample = {
        "cards": [
            {
                "word": "combination",
                "part_of_speech": "n",
                "ipa": "/ˌkɑːm.bəˈneɪ.ʃən/",
                "vietnamese_meaning": "sự kết hợp; tổ hợp",
                "word_forms": "combine (v); combined (adj)",
                "example_sentence": "Milk and coffee are a great combination.",
                "synonyms": ["mix", "blend", "union"],
                "anki_front_html": "combination (n)<br>/ˌkɑːm.bəˈneɪ.ʃən/<br>Ex: <i>Milk and coffee are a great <b>combination</b>.</i>",
                "anki_back_html": "sự kết hợp; tổ hợp<br>Synonyms: mix, blend, union",
            }
        ]
    }
    cards = validate_cards(sample)
    assert cards[0]["word"] == "combination"
    assert sorted(shuffled(["a", "b", "c"])) == ["a", "b", "c"]
    assert is_busy_ai_error(RuntimeError("Gọi API thất bại (503): overloaded"))
    assert is_busy_ai_error(RuntimeError("Không thể kết nối tới dịch vụ: timed out"))
    assert not is_busy_ai_error(RuntimeError("Gọi API thất bại (400): bad request"))
    assert next_excel_path(app_dir() / "vocabulary").name.endswith(".xlsx")
    notes = [
        {
            "deckName": "English Vocabulary",
            "modelName": "Basic",
            "fields": {"Front": cards[0]["anki_front_html"], "Back": cards[0]["anki_back_html"]},
            "tags": ["ai-vocab"],
        }
    ]
    assert notes[0]["fields"]["Front"].startswith("combination")
    reverse = validate_reverse_cards(
        cards,
        {
            "cards": [
                {
                    "word": "combination",
                    "sentence": "These two ideas form a useful <str>combination</str>.",
                    "vietnamese_hint": "sự kết hợp",
                }
            ]
        },
    )
    assert reverse[0]["back"] == "combination (n)"
    assert reverse[0]["keyword"] == "combination (n)"
    assert reverse[0]["answer"] == "combination"
    assert "___" in reverse[0]["front"]
    audio = select_audio([
        {"phonetics": [
            {"audio": "", "text": "/x/"},
            {"audio": "//api.dictionaryapi.dev/media/word-uk.mp3"},
            {
                "audio": "https://api.dictionaryapi.dev/media/word-us.mp3",
                "sourceUrl": "https://commons.wikimedia.org/example",
                "license": {"name": "CC BY", "url": "https://creativecommons.org/licenses/by/4.0/"},
            },
        ]}
    ])
    assert audio and audio["url"].endswith("-us.mp3")
    assert audio["filename"].startswith("vocab_") and audio["filename"].endswith(".mp3")
    assert set(audio) == {"url", "filename"}
    assert audio_metadata("https://example.com/audio") ["filename"].endswith(".mp3")
    assert audio_metadata("https://example.com/audio.ogg") is None
    assert audio_metadata("https://example.com/audio.wav") is None
    assert select_audio([{"phonetics": [{"audio": "http://example.com/unsafe.mp3"}]}]) is None
    wiktionary = wiktionary_audio_from_html(
        '<h2 id="French">French</h2><source src="//example.com/french.mp3" type="audio/mpeg">'
        '<h2 id="English">English</h2><source src="//upload.wikimedia.org/english.mp3" type="audio/mpeg">'
    )
    assert wiktionary and wiktionary["url"] == "https://upload.wikimedia.org/english.mp3"
    assert wiktionary_audio_from_html('<h2 id="English">English</h2><source src="http://example.com/audio.mp3" type="audio/mpeg">') is None
    calls = []

    def missing_source(text):
        calls.append("missing")
        return None

    def backup_source(text):
        calls.append("backup")
        return {"url": "https://example.com/backup.mp3", "filename": "backup.mp3"}

    def unused_source(text):
        calls.append("tts")
        return {"url": "https://example.com/tts.mp3", "filename": "tts.mp3"}

    assert resolve_audio("word", (missing_source, backup_source, unused_source))["filename"] == "backup.mp3"
    assert calls == ["missing", "backup"]
    calls.clear()
    assert resolve_audio("word", (missing_source, missing_source, unused_source))["filename"] == "tts.mp3"
    assert calls == ["missing", "missing", "tts"]
    assert google_tts_audio("two words")["url"].endswith("q=two%20words")
    normal_note = anki_note("Deck", "front", "back", ["ai-vocab"], audio, "Front")
    reverse_note = anki_note("Deck", "front", "back", ["reverse"], audio, "Back")
    assert normal_note["audio"]["fields"] == ["Front"]
    assert reverse_note["audio"]["fields"] == ["Back"]
    assert normal_note["fields"]["Front"].endswith(AUDIO_BUTTON_STYLE)
    assert reverse_note["fields"]["Back"].endswith(AUDIO_BUTTON_STYLE)
    assert AUDIO_BUTTON_STYLE not in normal_note["fields"]["Back"]
    assert AUDIO_BUTTON_STYLE not in reverse_note["fields"]["Front"]
    assert "audio" not in anki_note("Deck", "front", "back", [], None, "Front")
    original_anki = globals()["anki"]
    actions = []

    def fake_anki(action, params, config):
        actions.append((action, params))
        if action == "getDeckConfig":
            return {"id": 1, "autoplay": False, "new": {"perDay": 20}}
        if action == "saveDeckConfig":
            return True

    globals()["anki"] = fake_anki
    try:
        enable_anki_autoplay("Deck", {})
    finally:
        globals()["anki"] = original_anki
    saved_config = actions[-1][1]["config"]
    assert saved_config["autoplay"] is True and saved_config["new"]["perDay"] == 20

    def already_enabled(action, params, config):
        actions.append((action, params))
        return {"autoplay": True}

    actions.clear()
    globals()["anki"] = already_enabled
    try:
        enable_anki_autoplay("Deck", {})
    finally:
        globals()["anki"] = original_anki
    assert [action for action, _ in actions] == ["getDeckConfig"]

    def save_fails(action, params, config):
        return {"autoplay": False} if action == "getDeckConfig" else False

    globals()["anki"] = save_fails
    try:
        try:
            enable_anki_autoplay("Deck", {})
        except RuntimeError as exc:
            assert "Không thể bật tự động phát audio" in str(exc)
        else:
            raise AssertionError("Lưu autoplay thất bại phải dừng tạo thẻ.")
    finally:
        globals()["anki"] = original_anki
    output = StringIO()
    with redirect_stdout(output):
        with timed_step("Kiểm tra thời gian"):
            log_step_progress()
            pass
        try:
            with timed_step("Kiểm tra lỗi"):
                raise ValueError("test")
        except ValueError:
            pass
    assert re.search(r"hoàn tất trong \d+\.\d giây", output.getvalue())
    assert re.search(r"thất bại sau \d+\.\d giây", output.getvalue())
    assert "[Đang chạy]" in output.getvalue()
    assert re.search(r"Kiểm tra thời gian \(\d+\.\d+s\)", output.getvalue())
    assert "[OK       ]" in output.getvalue()
    assert "[Lỗi      ]" in output.getvalue()
    with tempfile.TemporaryDirectory() as empty_input:
        try:
            read_words(Path(empty_input))
        except RuntimeError as exc:
            assert str(exc) == "Hãy điền từ vựng vào notepad, lưu, và đóng file đó lại trước."
        else:
            raise AssertionError("Thư mục input trống phải báo lỗi.")
    msg("OK", "Tự kiểm tra thành công.")


def run_diagnostics(root: Path) -> int:
    report_path = root / "bao-cao-kiem-tra.txt"
    results: list[str] = []

    def check(name: str, test) -> None:
        started = time.perf_counter()
        try:
            detail = test()
            results.append(f"[OK] {name} ({time.perf_counter() - started:.1f} giây)" + (f": {detail}" if detail else ""))
        except Exception as exc:
            results.append(f"[LỖI] {name} ({time.perf_counter() - started:.1f} giây): {exc}")

    required = [
        "run.exe",
        "src/config.json",
        "src/agent-prompt.md",
        "src/reverse-prompt.md",
        "vocabulary/template.xlsx",
    ]
    for relative in required:
        check(relative, lambda relative=relative: "đã tìm thấy" if (root / relative).is_file() else (_ for _ in ()).throw(RuntimeError("thiếu file")))

    def valid_template() -> str:
        workbook = openpyxl.load_workbook(root / "vocabulary" / "template.xlsx", read_only=True)
        workbook.close()
        return "mở được"

    check("Tự kiểm tra chương trình", lambda: (run_self_test(), "thành công")[1])
    check("Mẫu Excel", valid_template)
    check("Đọc cấu hình", lambda: f"model={load_config(root)['model']} (khóa API đã được ẩn)")
    check("Đọc file input", lambda: f"{len(read_words(root / 'input'))} từ/cụm từ")
    check(
        "DictionaryAPI",
        lambda: "kết nối và audio hoạt động"
        if dictionary_audio("hello")
        else (_ for _ in ()).throw(RuntimeError("không tìm thấy audio thử")),
    )

    def writable() -> str:
        folder = root / "vocabulary"
        folder.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix="kiem-tra-", delete=True):
            pass
        return "có quyền ghi"

    check("Thư mục vocabulary", writable)

    config: dict | None = None
    try:
        config = load_config(root)
    except RuntimeError:
        pass

    if config:
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        check(
            "Groq API (yêu cầu thử tối thiểu)",
            lambda: "khóa, mạng và model hoạt động"
            if groq_json(["test"], "Return {\"ok\": true}.", schema, config).get("ok") is True
            else (_ for _ in ()).throw(RuntimeError("phản hồi thử không hợp lệ")),
        )
        check("AnkiConnect", lambda: f"version {anki('version', None, config)}")
    else:
        results.extend([
            "[BỎ QUA] Gemini API: cấu hình chưa hợp lệ",
            "[BỎ QUA] AnkiConnect: cấu hình chưa hợp lệ",
        ])

    failed = any(line.startswith("[LỖI]") for line in results)
    header = [
        "BÁO CÁO KIỂM TRA ANKI DECK",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Lưu ý: Báo cáo không chứa khóa API và không thêm thẻ vào Anki.",
        "",
    ]
    report_path.write_text("\n".join(header + results) + "\n", encoding="utf-8-sig")
    for line in results:
        print(line)
    msg("OK" if not failed else "LỖI", f"Đã lưu báo cáo: {report_path.name}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--no-pause", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            run_self_test()
            return 0
        root = app_dir()
        if args.diagnose:
            return run_diagnostics(root)
        msg("Lưu ý", "Hãy lưu và đóng tất cả file .txt trong thư mục input trước khi tiếp tục. Nội dung chưa lưu sẽ không được xử lý.")
        with timed_step("Đọc cấu hình"):
            config = load_config(root)
        with timed_step("Đọc file input và prompt"):
            words = shuffled(read_words(root / "input"))
            prompt = (src_dir(root) / "agent-prompt.md").read_text(encoding="utf-8")
            reverse_prompt = (src_dir(root) / "reverse-prompt.md").read_text(encoding="utf-8")
        with timed_step("Kiểm tra Anki và AnkiConnect"):
            try:
                anki("version", None, config)
            except RuntimeError as exc:
                raise RuntimeError(
                    "Anki chưa được mở hoặc AnkiConnect chưa hoạt động. "
                    "Hãy mở Anki, cài add-on 2055492159 nếu cần, rồi chạy lại run.exe."
                ) from exc
        all_cards: list[dict] = []
        word_batches = chunks(words, int(config["chunk_size"]))
        for index, batch in enumerate(word_batches, start=1):
            with timed_step(f"Dùng AI tạo thẻ từ vựng, đợt {index}/{len(word_batches)} ({len(batch)} từ)"):
                all_cards.extend(groq_cards(batch, prompt, config))
        all_reverse_cards: list[dict] = []
        reverse_batches = chunks(all_cards, int(config["chunk_size"]))
        for index, batch in enumerate(reverse_batches, start=1):
            with timed_step(f"Dùng AI tạo thẻ luyện tập, đợt {index}/{len(reverse_batches)} ({len(batch)} từ)"):
                all_reverse_cards.extend(groq_reverse_cards(batch, reverse_prompt, config))
        with timed_step("Lấy audio phát âm từ DictionaryAPI"):
            enrich_audio(all_cards, all_reverse_cards)
        with timed_step("Tạo file Excel"):
            excel_path = write_excel(root, all_cards, all_reverse_cards)
        msg("OK", f"File Excel: {excel_path.relative_to(root)}")
        with timed_step("Thêm thẻ và audio vào Anki"):
            added = add_to_anki(all_cards, all_reverse_cards, config)
        msg("OK", f"Đã thêm {added} thẻ vào Anki.")
        return 0
    except (RuntimeError, HTTPError) as exc:
        msg("Lỗi", str(exc))
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        msg("Lỗi", f"Không thể đọc hoặc ghi file. Hãy đóng các file đang mở và kiểm tra quyền truy cập. Chi tiết: {exc}")
        return 1
    finally:
        if getattr(sys, "frozen", False) and not args.no_pause:
            input("Nhấn Enter để đóng cửa sổ...")


if __name__ == "__main__":
    raise SystemExit(main())

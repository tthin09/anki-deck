from __future__ import annotations

from contextvars import ContextVar, copy_context
import hashlib
import html
from html.parser import HTMLParser
import json
import random
import re
import socket
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import genanki

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
                    # sentence and meaning come first so the part of speech is chosen from them
                    "example_sentence": {"type": "string"},
                    "vietnamese_meaning": {"type": "string"},
                    "part_of_speech": {"type": "string"},
                    "ipa": {"type": "string"},
                    "word_forms": {"type": "string"},
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
                    "part_of_speech": {"type": "string"},
                    "vietnamese_hint": {"type": "string"},
                },
                "required": ["word", "sentence", "part_of_speech", "vietnamese_hint"],
            },
        }
    },
    "required": ["cards"],
}


VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    # written before the corrected cards: the model's reasoning, since thinking mode is off
                    "check": {"type": "string"},
                    "card": CARD_SCHEMA["properties"]["cards"]["items"],
                    "practice_card": REVERSE_SCHEMA["properties"]["cards"]["items"],
                },
                "required": ["word", "check", "card", "practice_card"],
            },
        }
    },
    "required": ["pairs"],
}
LLM_TIMEOUT = 180
VERIFICATION_ROUNDS = 2
VERIFICATION_CHUNK_SIZE = 10


AUDIO_BUTTON_STYLE = "<style>.replay-button{display:block!important;text-align:center;margin-top:12px}</style>"
AUDIO_DOWNLOAD_RETRIES = 3
AUDIO_DOWNLOAD_MAX_BYTES = 10 * 1024 * 1024
AUDIO_DOWNLOAD_RETRY_CODES = {429, 500, 502, 503, 504}
PARTS_OF_SPEECH = {"n", "v", "adj", "adv", "prep", "conj", "pron", "det", "np", "vp", "adjp", "advp", "s"}


def src_dir(root: Path) -> Path:
    return root / "src"


progress_sink: ContextVar = ContextVar("progress_sink", default=None)
cancellation_check: ContextVar = ContextVar("cancellation_check", default=lambda: None)
_active_step: ContextVar = ContextVar("active_step", default=None)


class ConversionCancelled(Exception):
    pass


def check_cancelled() -> None:
    cancellation_check.get()()


class CardHTML(HTMLParser):
    """Keep prompt-supported formatting, never AI-supplied active content."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.blocked = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "template"}:
            self.blocked.append(tag)
        elif not self.blocked and tag in {"br", "i", "b"}:
            self.output.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
        elif tag in {"i", "b"}:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked:
            self.output.append(html.escape(data, quote=False))


def sanitize_card_html(value: str) -> str:
    parser = CardHTML()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def msg(kind: str, text: str) -> None:
    check_cancelled()
    line = f"[{kind:<9}] {text}"
    print(line, flush=True)
    sink = progress_sink.get()
    if sink:
        sink(line)


@contextmanager
def timed_step(text: str):
    started = time.perf_counter()
    token = _active_step.set((text, started))
    msg("Đang chạy", text)
    try:
        yield
    except Exception:
        msg("Lỗi", f"{text} thất bại sau {time.perf_counter() - started:.1f} giây.")
        raise
    else:
        msg("OK", f"Hoàn thành trong {time.perf_counter() - started:.1f} giây.")
    finally:
        _active_step.reset(token)


def log_step_progress() -> None:
    if _active_step.get():
        text, started = _active_step.get()
        msg("Đang chạy", f"{text} ({time.perf_counter() - started:.1f}s)")


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 60) -> dict:
    check_cancelled()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            check_cancelled()
            return result
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gọi API thất bại ({exc.code}): {body[:500]}") from exc
    except (URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
        raise RuntimeError(f"Không thể kết nối tới dịch vụ: {exc}") from exc


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


def download_audio(
    audio: dict,
    directory: Path,
    sleep=time.sleep,
    opener=None,
) -> Path:
    check_cancelled()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / audio["filename"]
    request = Request(audio["url"], headers={"User-Agent": "anki-deck/1.0 (audio download)"})
    for attempt in range(AUDIO_DOWNLOAD_RETRIES):
        check_cancelled()
        try:
            with (opener or urlopen)(request, timeout=30) as response:
                data = response.read(AUDIO_DOWNLOAD_MAX_BYTES + 1)
                if not data:
                    raise RuntimeError("audio trả về file rỗng")
                if len(data) > AUDIO_DOWNLOAD_MAX_BYTES:
                    raise RuntimeError("audio vượt quá giới hạn 10 MB")
                if not is_mp3(data):
                    raise RuntimeError("Nguồn audio trả về dữ liệu không phải file MP3.")
                check_cancelled()
                path.write_bytes(data)
                return path
        except HTTPError as exc:
            if exc.code not in AUDIO_DOWNLOAD_RETRY_CODES or attempt == AUDIO_DOWNLOAD_RETRIES - 1:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"tải audio thất bại ({exc.code}): {body or exc.reason}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = min(30.0, max(1.0, float(retry_after)))
            except (TypeError, ValueError):
                delay = float(2**attempt)
            sleep(delay)
        except (URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
            if attempt == AUDIO_DOWNLOAD_RETRIES - 1:
                raise RuntimeError(f"tải audio thất bại: {exc}") from exc
            sleep(float(2**attempt))
    raise RuntimeError("tải audio thất bại")


def is_mp3(data: bytes) -> bool:
    return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)


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
    check_cancelled()
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


def resolve_audio(
    text: str,
    sources=None,
    trace: list[str] | None = None,
    announce: bool = False,
    prepare=None,
) -> dict | None:
    for source in sources or (wiktionary_audio, google_tts_audio):
        check_cancelled()
        name = {
            "wiktionary_audio": "Wiktionary",
            "google_tts_audio": "Google TTS",
        }.get(source.__name__, source.__name__)
        started = time.perf_counter()
        if announce:
            msg("Đang chạy", f"Audio '{text}': thử {name}...")
        try:
            audio = source(text)
        except RuntimeError as exc:
            if trace is not None:
                trace.append(f"{source.__name__}: error ({exc})")
            if announce:
                msg("Cảnh báo", f"Audio '{text}': {name} lỗi sau {time.perf_counter() - started:.1f}s.")
            continue
        if audio and prepare:
            try:
                audio = prepare(audio)
            except RuntimeError as exc:
                if trace is not None:
                    trace.append(f"{source.__name__}: download error ({exc})")
                if announce:
                    msg("Cảnh báo", f"Audio '{text}': {name} tải thất bại: {exc}. Thử nguồn tiếp theo.")
                continue
        if audio:
            if trace is not None:
                trace.append(f"{source.__name__}: audio found")
            if announce:
                msg("OK", f"Audio '{text}': {name} đã có sau {time.perf_counter() - started:.1f}s.")
            return audio
        if trace is not None:
            trace.append(f"{source.__name__}: no audio")
        if announce:
            msg("Đang chạy", f"Audio '{text}': {name} không có audio sau {time.perf_counter() - started:.1f}s.")
    return None


def enrich_audio(cards: list[dict], reverse_cards: list[dict], audio_dir: Path | None = None) -> None:
    cache: dict[str, dict | None] = {}
    trace_cache: dict[str, list[str]] = {}

    def prepare(audio: dict) -> dict:
        if audio_dir is None:
            return audio
        path = download_audio(audio, audio_dir)
        return {**audio, "path": str(path)}

    terms = {item.casefold(): item for item in
             [card["word"] for card in cards] + [card["answer"] for card in reverse_cards]}
    unique_terms = list(terms.items())

    def fetch(item: tuple[str, str]) -> tuple[str, dict | None]:
        key, text = item
        trace_cache[key] = []
        msg("Đang chạy", f"Audio '{text}'...")
        audio = resolve_audio(
            text,
            (wiktionary_audio, google_tts_audio),
            trace_cache[key],
            announce=True,
            prepare=prepare,
        )
        return key, audio

    def fetch_batches(items: list[tuple[str, str]], size: int) -> None:
        for start in range(0, len(items), size):
            batch = items[start:start + size]
            with ThreadPoolExecutor(max_workers=size) as executor:
                futures = [executor.submit(copy_context().run, fetch, item) for item in batch]
                cache.update(future.result() for future in futures)

    # ponytail: retry rate-limited audio in smaller groups; final failures keep silent cards.
    fetch_batches(unique_terms, 8)
    def rate_limited(key: str) -> bool:
        return any(re.search(r"\b(?:429|439)\b", entry) for entry in trace_cache[key])

    for size in (4, 2, 1):
        deferred = [item for item in unique_terms if cache.get(item[0]) is None and rate_limited(item[0])]
        if not deferred:
            break
        fetch_batches(deferred, size)

    rate_limited_words = [text for key, text in unique_terms if cache.get(key) is None and rate_limited(key)]
    if rate_limited_words:
        msg("Cảnh báo", f"Không thể lấy audio cho {len(rate_limited_words)} từ do lỗi server: {', '.join(rate_limited_words)}")

    by_word = {card["word"].casefold(): cache.get(card["word"].casefold()) for card in cards}
    for card in cards:
        key = card["word"].casefold()
        card["audio"] = by_word[key]
        if card["audio"] is None:
            msg(
                "Cảnh báo",
                f"Không tìm thấy audio cho '{card['word']}' sau: {'; '.join(trace_cache[key])}. "
                "Thẻ vẫn được tạo không có âm thanh.",
            )
    for reverse in reverse_cards:
        reverse["audio"] = cache.get(reverse["answer"].casefold()) or by_word.get(reverse["word"].casefold())
        if reverse["audio"] is None:
            msg(
                "Cảnh báo",
                f"Không tìm thấy audio cho đáp án '{reverse['answer']}' sau: "
                f"{'; '.join(trace_cache[reverse['answer'].casefold()])}.",
            )


def is_busy_ai_error(exc: RuntimeError) -> bool:
    return "Không thể kết nối" in str(exc) or any(f"({code})" in str(exc) for code in (429, 500, 502, 503, 504))


def prompt_with(items: list, prompt: str) -> str:
    return prompt + "\n\nInput data as JSON array:\n" + json.dumps(items, ensure_ascii=False)


def local_llm_json(items: list, prompt: str, schema: dict, name: str, config: dict) -> dict:
    base = config["llm_base_url"].rstrip("/")
    try:
        # ask which model is loaded, so swapping the served model needs no config change
        with urlopen(Request(f"{base}/v1/models"), timeout=10) as response:
            model = json.loads(response.read().decode("utf-8"))["data"][0]["id"]
    except (URLError, TimeoutError, ConnectionError, socket.timeout, KeyError, IndexError, ValueError) as exc:
        raise RuntimeError(f"Không thể kết nối tới dịch vụ: {exc}") from exc
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_with(items, prompt)}],
        "temperature": 0.2,
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        # this vLLM ignores response_format when thinking is on
        "chat_template_kwargs": {"enable_thinking": False},
    }
    response = post_json(f"{base}/v1/chat/completions", payload, timeout=LLM_TIMEOUT)
    try:
        return json.loads(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI trả về dữ liệu không đọc được. Chưa tạo bộ thẻ.") from exc


def llm_json(items: list, prompt: str, schema: dict, name: str, config: dict) -> dict:
    try:
        return local_llm_json(items, prompt, schema, name, config)
    except RuntimeError as exc:
        if not is_busy_ai_error(exc):
            raise
        msg("Cảnh báo", f"AI nội bộ không phản hồi, chuyển sang Gemini. Chi tiết: {exc}")
        return gemini_json(items, prompt, schema, config)


def gemini_json(items: list[dict | str], prompt: str, schema: dict, config: dict) -> dict:
    model = quote(config["model"], safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={quote(config['gemini_api_key'])}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt_with(items, prompt)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    last_error = None
    for attempt in range(4):
        check_cancelled()
        try:
            response = post_json(url, payload, timeout=30)
            break
        except RuntimeError as exc:
            last_error = exc
            if attempt == 3 or not is_busy_ai_error(exc):
                raise RuntimeError(
                    "Dịch vụ AI đang quá tải hoặc tạm thời bị lỗi. Đây là lỗi từ nhà cung cấp AI, "
                    "không phải do bạn. Hãy thử chạy lại sau vài phút. "
                    f"Chi tiết: {exc}"
                ) from exc
            log_step_progress()
            msg("Đang chạy", f"Dịch vụ AI đang quá tải. Tự động thử lại lần {attempt + 1}/3...")
            time.sleep(2 * (attempt + 1))
    else:
        raise last_error
    try:
        text = response["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI trả về dữ liệu không đọc được. Chưa tạo bộ thẻ.") from exc


def llm_cards(words: list[str], prompt: str, config: dict) -> list[dict]:
    data = llm_json(words, prompt, CARD_SCHEMA, "cards", config)
    return validate_cards(data)


def llm_practice_cards(cards: list[dict], prompt: str, config: dict) -> list[dict]:
    items = [
        {key: card[key] for key in ("word", "part_of_speech", "vietnamese_meaning", "word_forms", "example_sentence")}
        for card in cards
    ]
    data = llm_json(items, prompt, REVERSE_SCHEMA, "practice_cards", config)
    return validate_practice_cards(cards, data)


def validate_cards(data: dict) -> list[dict]:
    cards = data.get("cards")
    if not isinstance(cards, list) or not cards:
        raise RuntimeError("AI không trả về danh sách thẻ hợp lệ. Chưa tạo bộ thẻ.")
    required = set(CARD_SCHEMA["properties"]["cards"]["items"]["required"])
    for card in cards:
        if not isinstance(card, dict) or required - card.keys():
            raise RuntimeError("AI trả về thẻ thiếu dữ liệu. Chưa tạo bộ thẻ.")
        if not isinstance(card["synonyms"], list):
            raise RuntimeError("AI trả về synonyms không hợp lệ. Chưa tạo bộ thẻ.")
    for card in cards:
        parts = str(card["part_of_speech"]).split("/")
        if any(part not in PARTS_OF_SPEECH for part in parts) or len(set(parts)) != len(parts):
            raise RuntimeError(f"AI trả về part_of_speech không hợp lệ cho '{card['word']}'. Chưa tạo bộ thẻ.")
    return [{key: card[key] for key in required} for card in cards]


def normalize_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"</?str>", "", text).strip()).casefold()


def answer_text(sentence: str) -> str:
    matches = re.findall(r"<str>(.*?)</str>", sentence, flags=re.IGNORECASE | re.DOTALL)
    if len(matches) != 1 or not matches[0].strip():
        raise RuntimeError("AI trả về câu luyện tập không hợp lệ. Chưa tạo bộ thẻ.")
    return matches[0].strip()


def blank_for(answer: str) -> str:
    length = max(1, len(re.sub(r"\s+", "", answer)))
    blank_len = min(length, max(3, int(length * random.uniform(0.60, 0.80))))
    return "_" * blank_len


def make_reverse_note(card: dict, reverse: dict) -> dict:
    answer = answer_text(reverse["sentence"])
    front = re.sub(
        r"<str>.*?</str>",
        lambda _: f"{blank_for(answer)} ({reverse['vietnamese_hint']})",
        reverse["sentence"],
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    keyword = f"{answer} ({reverse['part_of_speech']})"
    return {"front": html.escape(front), "back": html.escape(keyword), "keyword": keyword, "word": card["word"], "answer": answer}


def validate_practice_cards(cards: list[dict], data: dict) -> list[dict]:
    """Return the AI's practice cards in the same order as their vocabulary cards."""
    practice = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(practice, list) or len(practice) != len(cards):
        raise RuntimeError("AI không trả về đủ câu luyện tập. Chưa tạo bộ thẻ.")
    keys = REVERSE_SCHEMA["properties"]["cards"]["items"]["required"]
    by_word = {str(item.get("word")).casefold(): item for item in practice if isinstance(item, dict)}
    validated = []
    for card in cards:
        item = by_word.get(card["word"].casefold())
        if item is None or set(keys) - item.keys():
            raise RuntimeError("AI trả về câu luyện tập thiếu dữ liệu. Chưa tạo bộ thẻ.")
        answer_text(item["sentence"])
        if item["part_of_speech"] not in str(card["part_of_speech"]).split("/"):
            raise RuntimeError(f"AI trả về câu luyện tập sai từ loại cho '{card['word']}'. Chưa tạo bộ thẻ.")
        if normalize_sentence(item["sentence"]) == normalize_sentence(card["example_sentence"]):
            raise RuntimeError("AI trả về câu luyện tập trùng câu ví dụ. Chưa tạo bộ thẻ.")
        validated.append({key: item[key] for key in keys})
    return validated


def verified_pair(card: dict, practice: dict, fix: dict | None) -> tuple[dict, dict]:
    """Take the verification's correction only if it is still a valid card pair for the same word."""
    try:
        new_card = {**validate_cards({"cards": [fix["card"]]})[0], "word": card["word"]}
        if fix["card"]["word"].casefold() != card["word"].casefold():
            return card, practice
        # the front shows the part of speech too; a fix that relabels only one of them is rejected
        if f"({new_card['part_of_speech']})" not in new_card["anki_front_html"]:
            return card, practice
        return new_card, validate_practice_cards([new_card], {"cards": [fix["practice_card"]]})[0]
    except (RuntimeError, KeyError, TypeError, AttributeError):
        return card, practice


def verify_cards(cards: list[dict], practice: list[dict], prompt: str, config: dict) -> None:
    """Verification: let the AI correct card pairs in place, keeping the originals if it fails."""
    for round_number in range(1, VERIFICATION_ROUNDS + 1):
        changed = 0
        try:
            with timed_step(f"Kiểm tra lại thẻ, vòng {round_number}/{VERIFICATION_ROUNDS}"):
                for start in range(0, len(cards), VERIFICATION_CHUNK_SIZE):
                    indexes = range(start, min(start + VERIFICATION_CHUNK_SIZE, len(cards)))
                    items = [{"card": cards[i], "practice_card": practice[i]} for i in indexes]
                    data = llm_json(items, prompt, VERIFY_SCHEMA, "verification", config)
                    pairs = data.get("pairs") if isinstance(data, dict) else None
                    if not isinstance(pairs, list):
                        raise RuntimeError("AI trả về kết quả kiểm tra không hợp lệ.")
                    fixes = {str(pair.get("word")).casefold(): pair for pair in pairs if isinstance(pair, dict)}
                    for i in indexes:
                        pair = verified_pair(cards[i], practice[i], fixes.get(cards[i]["word"].casefold()))
                        if pair != (cards[i], practice[i]):
                            cards[i], practice[i] = pair
                            changed += 1
                msg("OK", f"Vòng {round_number}/{VERIFICATION_ROUNDS}: đã sửa {changed} thẻ.")
        except RuntimeError as exc:
            msg("Cảnh báo", f"Không kiểm tra lại hết được thẻ; thẻ chưa kiểm tra được giữ nguyên. Chi tiết: {exc}")
            return
        if not changed:
            return


def package_note(front: str, back: str, tags: list[str], audio: dict | None, audio_field: str) -> dict:
    fields = {"Front": sanitize_card_html(front), "Back": sanitize_card_html(back)}
    if audio:
        fields[audio_field] += f"[sound:{audio['filename']}]" + AUDIO_BUTTON_STYLE
    return {"fields": fields, "tags": tags}


def create_apkg(cards: list[dict], reverse_cards: list[dict], deck_name: str, output: Path) -> Path:
    deck_id = (int.from_bytes(hashlib.sha256(deck_name.encode("utf-8")).digest()[:4], "big") % (1 << 30)) + (1 << 30)
    models = [
        genanki.Model(
            model_id,
            name,
            fields=[{"name": "Front"}, {"name": "Back"}],
            templates=[{"name": "Card 1", "qfmt": "{{Front}}", "afmt": '{{FrontSide}}<hr id="answer">{{Back}}'}],
        )
        for model_id, name in ((1690123450, "Vocabulary Generator"), (1690123451, "Vocabulary Generator Reverse"))
    ]
    deck = genanki.Deck(deck_id, deck_name)
    media = {}
    check_cancelled()
    for items, model, front_key, back_key, tag in (
        (cards, models[0], "anki_front_html", "anki_back_html", "ai-vocab"),
        (reverse_cards, models[1], "front", "back", "reverse"),
    ):
        for item in items:
            check_cancelled()
            audio = item.get("audio")
            note = package_note(
                item[front_key],
                item[back_key],
                ["ai-vocab", tag] if tag == "reverse" else [tag],
                audio,
                "Back" if tag == "reverse" else "Front",
            )
            deck.add_note(genanki.Note(
                model=model,
                fields=[note["fields"]["Front"], note["fields"]["Back"]],
                tags=note["tags"],
                guid=genanki.guid_for(tag, item["word"].casefold()),
            ))
            if audio:
                audio_path = Path(audio["path"])
                if not audio_path.is_file():
                    raise RuntimeError(f"Không tìm thấy file audio tạm: {audio_path.name}")
                media[audio["filename"]] = audio_path
    package = genanki.Package(deck, media_files=[str(path) for path in media.values()])
    check_cancelled()
    package.write_to_file(str(output))
    check_cancelled()
    return output


def generate_package(root: Path, config: dict, words: list[str], output: Path) -> Path:
    prompt = (src_dir(root) / "agent-prompt.md").read_text(encoding="utf-8")
    reverse_prompt = (src_dir(root) / "reverse-prompt.md").read_text(encoding="utf-8")
    verify_prompt = (src_dir(root) / "verify-prompt.md").read_text(encoding="utf-8")
    cards, reverse_cards = generate_cards(words, prompt, reverse_prompt, verify_prompt, config)
    with tempfile.TemporaryDirectory(prefix="anki-deck-audio-") as temp_dir:
        with timed_step("Lấy audio phát âm từ Wiktionary và Google TTS"):
            enrich_audio(cards, reverse_cards, Path(temp_dir))
        with timed_step("Đóng gói thẻ và audio thành APKG"):
            create_apkg(cards, reverse_cards, config["deck_name"], output)
    return output


def generate_cards(
    words: list[str], prompt: str, reverse_prompt: str, verify_prompt: str, config: dict
) -> tuple[list[dict], list[dict]]:
    all_cards: list[dict] = []
    word_batches = chunks(words, int(config["chunk_size"]))
    for index, batch in enumerate(word_batches, start=1):
        with timed_step(f"Dùng AI tạo thẻ từ vựng, đợt {index}/{len(word_batches)} ({len(batch)} từ)"):
            all_cards.extend(llm_cards(batch, prompt, config))
    all_practice: list[dict] = []
    practice_batches = chunks(all_cards, int(config["chunk_size"]))
    for index, batch in enumerate(practice_batches, start=1):
        with timed_step(f"Dùng AI tạo thẻ luyện tập, đợt {index}/{len(practice_batches)} ({len(batch)} từ)"):
            all_practice.extend(llm_practice_cards(batch, reverse_prompt, config))
    verify_cards(all_cards, all_practice, verify_prompt, config)
    return all_cards, [make_reverse_note(card, practice) for card, practice in zip(all_cards, all_practice)]

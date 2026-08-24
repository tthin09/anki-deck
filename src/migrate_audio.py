from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tempfile
from pathlib import Path

from anki_deck import (
    AUDIO_BUTTON_STYLE,
    anki,
    dictionary_audio,
    download_audio,
    enable_anki_autoplay,
    google_tts_audio,
    msg,
    resolve_audio,
    timed_step,
    wiktionary_audio,
)


def root_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def config(root: Path) -> dict:
    url = "http://127.0.0.1:8765"
    path = root / "src" / "config.json"
    try:
        url = json.loads(path.read_text(encoding="utf-8-sig")).get("anki_connect_url") or url
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return {"anki_connect_url": url}


def visible_text(value: str) -> str:
    value = re.sub(r"<style\b.*?</style>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"\[sound:[^]]+]", "", value, flags=re.IGNORECASE)
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def term_from_field(value: str, normal: bool) -> str:
    if normal:
        value = re.split(r"<br\s*/?>", value, maxsplit=1, flags=re.IGNORECASE)[0]
    text = visible_text(value)
    return re.sub(r"\s+\((?:n|v|adj|adv|np|vp|adjp|advp|s)(?:/[a-z]+)*\)\s*$", "", text, flags=re.IGNORECASE).strip()


def word_forms(word: str) -> set[str]:
    word = word.casefold()
    match = re.fullmatch(r"(.*?)([a-z]+)", word)
    if not match:
        return {word}
    prefix, base = match.groups()
    forms = {base, base + "s", base + "es", base + "ed", base + "ing"}
    if base.endswith("e"):
        forms.update({base + "d", base[:-1] + "ing"})
    if len(base) > 1 and base.endswith("y") and base[-2] not in "aeiou":
        forms.update({base[:-1] + "ies", base[:-1] + "ied"})
    if len(base) >= 3 and base[-1] not in "aeiouwxy" and base[-2] in "aeiou" and base[-3] not in "aeiou":
        forms.update({base + base[-1] + "ed", base + base[-1] + "ing"})
    return {prefix + form for form in forms}


def migrated_field(value: str, filename: str) -> str:
    style = "" if AUDIO_BUTTON_STYLE in value else AUDIO_BUTTON_STYLE
    return f"{value}{style}[sound:{filename}]"


def preview_line(item: dict) -> str:
    kind = "thẻ đảo" if item["reverse"] else "thẻ thường"
    fallback = f" → audio: {item['audio_term']}" if item["audio_term"].casefold() != item["term"].casefold() else ""
    return f"  - {item['term']} ({kind}){fallback}"


def report(root: Path, rows: list[dict]) -> Path:
    path = root / "bao-cao-migrate.txt"
    lines = ["BÁO CÁO MIGRATE AUDIO", ""]
    lines.extend(f"{row.get('id', '-')}: {row['status']} - {row.get('term', '')}" for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def run_self_test() -> None:
    assert term_from_field("advocate (v/n)<br>/ipa/", True) == "advocate"
    assert term_from_field("advocates (v)<style>x</style>", False) == "advocates"
    assert "advocates" in word_forms("advocate")
    assert "pencils" in word_forms("pencil")
    assert "studies" in word_forms("study")
    assert "stopped" in word_forms("stop")
    value = migrated_field("answer", "audio.mp3")
    assert value == f"answer{AUDIO_BUTTON_STYLE}[sound:audio.mp3]"
    assert migrated_field(value, "other.mp3").count(AUDIO_BUTTON_STYLE) == 1
    assert preview_line({"term": "advocates", "audio_term": "advocate", "reverse": True}) == "  - advocates (thẻ đảo) → audio: advocate"
    msg("OK", "Tự kiểm tra migrate thành công.")


def resolve_legacy_audio(candidates: list[dict], normal_terms: set[str]):
    temp_dir = tempfile.TemporaryDirectory(prefix="anki-deck-migrate-audio-")
    audio_dir = Path(temp_dir.name)
    cache: dict[str, dict | None] = {}

    def prepare(audio: dict) -> dict:
        path = download_audio(audio, audio_dir)
        return {**audio, "path": str(path)}

    def lookup(term: str) -> dict | None:
        key = term.casefold()
        if key not in cache:
            cache[key] = resolve_audio(
                term,
                (dictionary_audio, wiktionary_audio, google_tts_audio),
                prepare=prepare,
            )
        return cache[key]

    try:
        with timed_step("Tìm audio cho thẻ cũ"):
            for item in candidates:
                item["audio_term"] = item["term"]
                audio = lookup(item["term"])
                if audio is None and item["reverse"]:
                    matches = [base for base in normal_terms if item["term"].casefold() in word_forms(base)]
                    if len(matches) == 1:
                        item["audio_term"] = matches[0]
                        audio = lookup(matches[0])
                item["audio"] = audio
                item["row"]["status"] = "SẴN SÀNG" if audio else "BỎ QUA: không tìm thấy audio"
    except Exception:
        temp_dir.cleanup()
        raise
    return [item for item in candidates if item.get("audio")], temp_dir


def migrate(root: Path, dry_run: bool, assume_yes: bool) -> int:
    cfg = config(root)
    rows: list[dict] = []
    with timed_step("Kết nối AnkiConnect và đọc thẻ cũ"):
        anki("version", None, cfg)
        ids = anki("findNotes", {"query": "tag:ai-vocab"}, cfg)
        notes = anki("notesInfo", {"notes": ids}, cfg) if ids else []

    normal_terms: set[str] = set()
    candidates = []
    for note in notes:
        fields = {name: data["value"] for name, data in note.get("fields", {}).items()}
        reverse = "reverse" in {tag.casefold() for tag in note.get("tags", [])}
        target = "Back" if reverse else "Front"
        value = fields.get(target)
        row = {"id": note.get("noteId"), "status": "", "term": ""}
        if value is None:
            row["status"] = "BỎ QUA: thiếu trường Front/Back"
        elif "[sound:" in value.casefold():
            row["status"] = "BỎ QUA: đã có audio"
        else:
            term = term_from_field(value, not reverse)
            row["term"] = term
            if not term:
                row["status"] = "BỎ QUA: không đọc được từ"
            else:
                candidate = {"note": note, "target": target, "value": value, "term": term, "reverse": reverse, "row": row}
                candidates.append(candidate)
                if not reverse:
                    normal_terms.add(term)
        rows.append(row)

    ready, audio_temp = resolve_legacy_audio(candidates, normal_terms)
    skipped_audio = sum("đã có audio" in row["status"] for row in rows)
    unresolved = sum("không tìm thấy audio" in row["status"] for row in rows)
    malformed = len(rows) - len(ready) - skipped_audio - unresolved
    if ready:
        msg("Thông tin", "Các từ sẽ được migrate:")
        for item in ready:
            print(preview_line(item), flush=True)
    msg("Thông tin", f"Sẵn sàng: {len(ready)} | Đã có audio: {skipped_audio} | Không có audio: {unresolved} | Bỏ qua: {malformed}")

    if dry_run or not ready:
        path = report(root, rows)
        msg("OK", f"Đã lưu báo cáo: {path.name}")
        audio_temp.cleanup()
        return 0
    if not assume_yes and input("Nhập Y để bắt đầu migrate: ").strip().casefold() != "y":
        msg("Cảnh báo", "Đã hủy. Chưa thay đổi thẻ nào.")
        report(root, rows)
        audio_temp.cleanup()
        return 0

    card_ids = [card for item in ready for card in item["note"].get("cards", [])]
    card_info = anki("cardsInfo", {"cards": card_ids}, cfg) if card_ids else []
    decks = {card["deckName"] for card in card_info}
    with timed_step("Bật tự động phát audio"):
        for deck in decks:
            enable_anki_autoplay(deck, cfg)

    stored = set()
    with timed_step(f"Migrate {len(ready)} thẻ"):
        for item in ready:
            audio = item["audio"]
            original = item["value"]
            try:
                if audio["filename"] not in stored:
                    result = anki(
                        "storeMediaFile",
                        {
                            "filename": audio["filename"],
                            "path": audio["path"],
                            "deleteExisting": True,
                        },
                        cfg,
                    )
                    if not result:
                        raise RuntimeError("Anki không lưu được file audio")
                    stored.add(audio["filename"])
                updated = migrated_field(original, audio["filename"])
                anki("updateNoteFields", {"note": {"id": item["note"]["noteId"], "fields": {item["target"]: updated}}}, cfg)
                checked = anki("notesInfo", {"notes": [item["note"]["noteId"]]}, cfg)[0]
                if "[sound:" not in checked["fields"][item["target"]]["value"].casefold():
                    anki("updateNoteFields", {"note": {"id": item["note"]["noteId"], "fields": {item["target"]: original}}}, cfg)
                    raise RuntimeError("xác minh audio thất bại; đã khôi phục thẻ")
                item["row"]["status"] = "THÀNH CÔNG"
            except RuntimeError as exc:
                item["row"]["status"] = f"LỖI: {exc}"
                msg("Cảnh báo", f"Thẻ {item['note']['noteId']}: {exc}")

    path = report(root, rows)
    succeeded = sum(row["status"] == "THÀNH CÔNG" for row in rows)
    msg("OK", f"Đã migrate {succeeded}/{len(ready)} thẻ. Báo cáo: {path.name}")
    audio_temp.cleanup()
    return 0 if succeeded == len(ready) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--no-pause", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            run_self_test()
            return 0
        return migrate(root_dir(), args.dry_run, args.yes)
    except RuntimeError as exc:
        msg("Lỗi", str(exc))
        return 1
    finally:
        if getattr(sys, "frozen", False) and not args.no_pause:
            input("Nhấn Enter để đóng cửa sổ...")


if __name__ == "__main__":
    raise SystemExit(main())

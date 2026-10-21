"""Local web adapter for the vocabulary-to-APKG generator."""
from __future__ import annotations

import csv
import json
import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from anki_deck import ConversionCancelled, cancellation_check, generate_package, progress_sink, prompt_dir, msg, research_entries

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ANKI_DATA_DIR", str(ROOT / "data")))
CLIENT_AGE = 365 * 24 * 60 * 60
# Every message a learner can see says whose fault it is, in Vietnamese.
USER_ERROR = "Lỗi do người dùng: "
SYSTEM_ERROR = "Lỗi do hệ thống: "
TOO_LONG = USER_ERROR + "Danh sách quá dài. Hãy chia thành nhiều lần, mỗi lần tối đa 100 từ."
jobs: dict[str, dict] = {}
workers: dict[str, dict] = {}
pending: dict[str, dict] = {}
lock = threading.RLock()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class APIBodyLimit:
    """Bound actual received bytes before FastAPI parses JSON."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) >= 8192:
                response = JSONResponse({"detail": TOO_LONG}, status_code=413)
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


app.add_middleware(APIBodyLimit)


LIST_MARKER = re.compile(r"^(?:[-*•·–]|\d+[.)])\s+")


def parse(text: str) -> tuple[list[str], list[str]]:
    """Unique entries (words or phrases) from pasted text, plus one error per bad line.

    Accepts one word per line, comma/semicolon lists, bullet or numbered lists, and spreadsheet
    rows (tab-separated: the "Word" column if a header names it, else the first non-number cell).
    """
    if len(text.encode("utf-8")) >= 8192:
        raise HTTPException(422, TOO_LONG)
    lines = text.splitlines()
    column = None
    for index, line in enumerate(lines):
        cells = [cell.strip().casefold() for cell in line.split("\t")]
        # A header row names a "Word" column and has no row number.
        if len(cells) > 1 and "word" in cells and not any(cell.replace(".", "").isdigit() for cell in cells):
            column, lines[index] = cells.index("word"), ""
            break
        if line.strip() and "\t" in line:
            break
    seen: set[str] = set()
    words, errors = [], []
    for number, line in enumerate(lines, 1):
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
            if column is not None:
                line = cells[column] if column < len(cells) else ""
            else:
                line = next((cell for cell in cells if cell and not cell.replace(".", "").isdigit()), "")
        for item in re.split(r"[,;]", LIST_MARKER.sub("", line.strip())):
            word = " ".join(item.split())
            if len(word) > 50:
                errors.append(f"{USER_ERROR}Dòng {number} dài quá 50 ký tự. Mỗi dòng chỉ ghi một từ hoặc một cụm từ.")
            elif word and word.casefold() not in seen:
                seen.add(word.casefold())
                words.append(word)
    return words, errors


def vocabulary(text: str) -> list[str]:
    words, errors = parse(text)
    if errors:
        raise HTTPException(422, errors[0])
    if not words:
        raise HTTPException(422, USER_ERROR + "Hãy nhập ít nhất một từ.")
    if len(words) > 100:
        raise HTTPException(422, USER_ERROR + "Tối đa 100 từ mỗi lần. Hãy bớt từ hoặc chia thành nhiều lần.")
    return words


class Input(BaseModel):
    text: str = Field(max_length=8191)


class Choice(BaseModel):
    research: str = Field(max_length=64)
    # [entry index, sense index] pairs into the research result
    senses: list[tuple[int, int]] = Field(min_length=1, max_length=400)


def current_user(response: Response, session: str | None = Cookie(default=None)) -> str:
    """Anonymous per-browser id; it only keeps one browser's jobs and downloads away from another's."""
    if session and len(session) == 43:
        return session
    session = secrets.token_urlsafe(32)
    response.set_cookie("session", session, httponly=True, samesite="strict", max_age=CLIENT_AGE, path="/")
    return session


def job_for(job_id: str, user: str) -> dict:
    with lock:
        job = jobs.get(job_id)
        if not job or job["user"] != user or job["created"] + 3600 < time.time():
            raise HTTPException(404, SYSTEM_ERROR + "Không tìm thấy lượt chạy này, có thể hệ thống vừa khởi động lại. Hãy thử lại.")
        return job


def progress(job: dict, line: str):
    with job["condition"]:
        batch = re.search(r"Tìm nghĩa, đợt (\d+)/(\d+)", line)
        if batch:
            job["percent"] = 5 + 90 * (int(batch[1]) - 1) // int(batch[2])
        elif "Dùng AI tạo thẻ luyện tập" in line:
            job["percent"] = 40
        elif "Kiểm tra lại thẻ" in line:
            job["percent"] = 55
        elif "Lấy audio" in line:
            job["percent"] = 65
        elif "Đóng gói" in line:
            job["percent"] = 90
        job["events"].append({"type": "line", "text": line, "percent": job["percent"]})
        job["condition"].notify_all()


def finish(job: dict, state: str):
    with job["condition"]:
        if job["state"] in {"done", "failed", "cancelled"}:
            return
        job["state"] = state
        job["lease"].cancel()
        event = {"type": state, "percent": 100 if state == "done" else job["percent"]}
        if state == "done" and "result" in job:
            event["result"] = job["result"]
        job["events"].append(event)
        job["condition"].notify_all()


def cancelled(job: dict) -> bool:
    return job["state"] == "cancelled" or time.monotonic() - job["heartbeat"] >= 30


def schedule_expiry(job: dict):
    delay = max(0, 30 - (time.monotonic() - job["heartbeat"]))
    job["lease"] = threading.Timer(delay, expire_job, args=(job,))
    job["lease"].daemon = True
    job["lease"].start()


def expire_job(job: dict):
    with lock:
        if job["state"] in {"done", "failed", "cancelled"}:
            return
        if cancelled(job):
            finish(job, "cancelled")
        else:
            schedule_expiry(job)


def check_job(job: dict):
    with lock:
        if cancelled(job):
            finish(job, "cancelled")
            raise ConversionCancelled()


def ai_config() -> dict:
    return {"gemini_api_key": os.environ["GEMINI_API_KEY"], "model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
            "llm_base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8000"),
            "deck_name": "English Vocabulary", "chunk_size": 30}


def research(job: dict):
    token = progress_sink.set(lambda line: progress(job, line))
    cancel_token = cancellation_check.set(lambda: check_job(job))
    try:
        prompt = (prompt_dir(ROOT) / "step_1" / "research-prompt.md").read_text(encoding="utf-8")
        check_job(job)
        result = research_entries(job["words"], prompt, ai_config())
        with lock:
            check_job(job)
            job["result"] = result
            finish(job, "done")
    except ConversionCancelled:
        finish(job, "cancelled")
    except Exception:
        progress(job, "[Lỗi      ] Không thể tìm từ. Kiểm tra dịch vụ và thử lại.")
        finish(job, "failed")
    finally:
        cancellation_check.reset(cancel_token)
        progress_sink.reset(token)


def convert(job: dict):
    token = progress_sink.set(lambda line: progress(job, line))
    cancel_token = cancellation_check.set(lambda: check_job(job))
    # One folder per run; it is written as "<stamp>.part" and renamed only once both files are complete.
    stamp = job["stamp"]
    folder = DATA / "output" / stamp
    temporary = folder.with_name(f"{stamp}.part")
    deck, report = f"{stamp}_deck.apkg", f"{stamp}_report.xlsx"
    senses = job["senses"]
    try:
        config = ai_config()
        temporary.mkdir(parents=True, exist_ok=True)
        (DATA / "history").mkdir(parents=True, exist_ok=True)
        check_job(job)
        generate_package(ROOT, config, senses, temporary / deck, temporary / report)
        check_job(job)
        for name in (deck, report):
            with (temporary / name).open("rb") as file:
                os.fsync(file.fileno())
        # ponytail: one process holds this lock; use a database if multiple server workers are needed.
        with lock:
            check_job(job)
            os.replace(temporary, folder)
            path = DATA / "history" / "conversions.csv"
            with path.open("a", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                if file.tell() == 0:
                    writer.writerow(["filename", "uploader", "created_utc", "words"])
                chosen = [f"{sense['entry']} ({sense['part_of_speech']})" if sense["part_of_speech"] else sense["entry"]
                          for sense in senses]
                writer.writerow([deck, job["user"], datetime.now(timezone.utc).isoformat(), json.dumps(chosen, ensure_ascii=False)])
                file.flush()
                os.fsync(file.fileno())
            for parent in (folder, folder.parent, path.parent, DATA):
                directory = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            job["file"] = folder / deck
            progress(job, f"[OK       ] Đã lưu: output/{stamp}/ ({deck}, {report})")
            finish(job, "done")
    except ConversionCancelled:
        finish(job, "cancelled")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        progress(job, "[Lỗi      ] Không thể tạo gói. Kiểm tra dịch vụ và thử lại.")
        finish(job, "failed")
    finally:
        try:
            shutil.rmtree(temporary, ignore_errors=True)
        finally:
            cancellation_check.reset(cancel_token)
            progress_sink.reset(token)


def run_user(job: dict):
    # One worker per user: a cancelled network call must return before its replacement starts.
    user = job["user"]
    while job:
        try:
            with lock:
                check_job(job)
                job["state"] = "running"
            job["run"](job)
        except ConversionCancelled:
            pass
        except Exception:
            progress(job, "[Lỗi      ] Không thể lưu gói. Kiểm tra quyền và dung lượng data/.")
            finish(job, "failed")
        with lock:
            job = pending.pop(user, None)
            if job:
                workers[user] = job
            else:
                workers.pop(user, None)


@app.post("/api/preview")
def preview(data: Input, response: Response, session: str | None = Cookie(default=None)):
    current_user(response, session)
    words, errors = parse(data.text)
    return {"words": words, "count": len(words), "error": errors[0] if errors else ""}


def queue(user: str, run, **fields) -> str:
    """Start a research or conversion job; one runs per browser at a time. Call with `lock` held."""
    active = pending.get(user) or workers.get(user)
    if active and active["state"] not in {"done", "failed"} and not cancelled(active):
        raise HTTPException(409, USER_ERROR + "Đang có một lượt tìm từ hoặc tạo bộ thẻ khác chạy, có thể ở tab khác. "
                                 "Hãy đợi lượt đó xong rồi thử lại.")
    if active:
        finish(active, "cancelled")
    job_id = uuid4().hex
    job = {"user": user, "created": time.time(), "run": run, "stamp": None,
           "condition": threading.Condition(), "events": [], "percent": 5,
           "file": None, "downloaded": False, "state": "queued", "heartbeat": time.monotonic(), **fields}
    jobs[job_id] = job
    schedule_expiry(job)
    if user in workers:
        previous = pending.get(user)
        if previous:
            finish(previous, "cancelled")
        pending[user] = job
    else:
        workers[user] = job
        threading.Thread(target=run_user, args=(job,), daemon=True).start()
    return job_id


def forget_old_jobs():
    for old_id in [key for key, value in jobs.items() if value["created"] + 3600 < time.time()]:
        del jobs[old_id]


@app.post("/api/research", status_code=202)
def start_research(data: Input, response: Response, session: str | None = Cookie(default=None)):
    user = current_user(response, session)
    words = vocabulary(data.text)
    with lock:
        forget_old_jobs()
        return {"id": queue(user, research, words=words)}


@app.post("/api/jobs", status_code=202)
def start(data: Choice, response: Response, session: str | None = Cookie(default=None)):
    user = current_user(response, session)
    try:
        found = job_for(data.research, user).get("result")
    except HTTPException:
        found = None
    if found is None:
        # research lives in memory: it is gone after an hour or a server restart
        raise HTTPException(410, SYSTEM_ERROR + "Kết quả tìm từ đã hết hạn hoặc hệ thống vừa khởi động lại. "
                                 "Hãy bấm Tìm từ để tìm lại.")
    senses = []
    for entry, sense in dict.fromkeys(data.senses):
        if not (0 <= entry < len(found) and 0 <= sense < len(found[entry]["senses"])):
            raise HTTPException(422, SYSTEM_ERROR + "Nghĩa đã chọn không còn hợp lệ. Hãy bấm Tìm từ để tìm lại.")
        senses.append({"entry": found[entry]["entry"], **found[entry]["senses"][sense]})
    started = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    with lock:
        forget_old_jobs()
        stamps = {job["stamp"] for job in jobs.values()}
        stamp = f"{started:%H%M%S-%d%m%y}"
        while stamp in stamps or (DATA / "output" / stamp).exists():
            started += timedelta(seconds=1)
            stamp = f"{started:%H%M%S-%d%m%y}"
        return {"id": queue(user, convert, stamp=stamp, senses=senses)}


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str, response: Response, session: str | None = Cookie(default=None)):
    job = job_for(job_id, current_user(response, session))
    with lock:
        finish(job, "cancelled")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/heartbeat")
def heartbeat(job_id: str, response: Response, session: str | None = Cookie(default=None)):
    job = job_for(job_id, current_user(response, session))
    with lock:
        if job["state"] not in {"done", "failed", "cancelled"}:
            if cancelled(job):
                finish(job, "cancelled")
            else:
                job["heartbeat"] = time.monotonic()
    return {"state": job["state"]}


@app.get("/api/jobs/{job_id}/events")
def events(job_id: str, response: Response, session: str | None = Cookie(default=None)):
    job = job_for(job_id, current_user(response, session))

    def stream():
        index = 0
        while True:
            with job["condition"]:
                if index == len(job["events"]):
                    job["condition"].wait(timeout=15)
                batch = job["events"][index:]
                index += len(batch)
            if not batch:
                yield ": keepalive\n\n"
            for event in batch:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] in ("done", "failed", "cancelled"):
                    return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str, response: Response, session: str | None = Cookie(default=None)):
    job = job_for(job_id, current_user(response, session))
    with lock:
        if not job["file"] or job["downloaded"]:
            raise HTTPException(404, SYSTEM_ERROR + "Không tải được bộ thẻ. Hãy bấm Tạo bộ thẻ lần nữa.")
        job["downloaded"] = True
        return FileResponse(job["file"], media_type="application/octet-stream", filename=job["file"].name)


DIST = ROOT / "web" / "dist"
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if not (DIST / "index.html").is_file():
        raise HTTPException(503, "Build the frontend first")
    return FileResponse(DIST / "index.html")

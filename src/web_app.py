"""Local web adapter for the vocabulary-to-APKG generator."""
from __future__ import annotations

import csv
import json
import os
import secrets
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

from anki_deck import ConversionCancelled, cancellation_check, generate_package, progress_sink, msg

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ANKI_DATA_DIR", str(ROOT / "data")))
CLIENT_AGE = 365 * 24 * 60 * 60
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
                response = JSONResponse({"detail": "Request body must be fewer than 8192 bytes"}, status_code=413)
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


def vocabulary(text: str, enforce_limit: bool = True) -> list[str]:
    if len(text.encode("utf-8")) >= 8192:
        raise HTTPException(422, "Input is too large")
    seen: set[str] = set()
    words = []
    for number, line in enumerate(text.splitlines(), 1):
        word = line.strip()
        if len(word) > 50:
            raise HTTPException(422, f"Line {number}: a word must be at most 50 characters")
        if any(char.isspace() for char in word):
            raise HTTPException(422, f"Line {number}: enter one word without spaces or tabs")
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            words.append(word)
            if enforce_limit and len(words) > 100:
                raise HTTPException(422, "Maximum 100 unique words")
    if not words:
        raise HTTPException(422, "Enter at least one word")
    return words


class Input(BaseModel):
    text: str = Field(max_length=8191)


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
            raise HTTPException(404, "Conversion not found")
        return job


def progress(job: dict, line: str):
    with job["condition"]:
        if "Dùng AI tạo thẻ luyện tập" in line:
            job["percent"] = 40
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
        job["events"].append({"type": state, "percent": 100 if state == "done" else job["percent"]})
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


def convert(job: dict):
    token = progress_sink.set(lambda line: progress(job, line))
    cancel_token = cancellation_check.set(lambda: check_job(job))
    output = DATA / "history" / job["filename"]
    temporary = output.with_suffix(".apkg.part")
    words = job["words"]
    try:
        key = os.environ["GEMINI_API_KEY"]
        output.parent.mkdir(parents=True, exist_ok=True)
        config = {"gemini_api_key": key, "model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
                  "llm_base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8000"),
                  "deck_name": "English Vocabulary", "chunk_size": 30}
        check_job(job)
        generate_package(ROOT, config, words, temporary)
        check_job(job)
        with temporary.open("rb") as file:
            os.fsync(file.fileno())
        # ponytail: one process holds this lock; use a database if multiple server workers are needed.
        with lock:
            check_job(job)
            os.replace(temporary, output)
            path = DATA / "history" / "conversions.csv"
            with path.open("a", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                if file.tell() == 0:
                    writer.writerow(["filename", "uploader", "created_utc", "words"])
                writer.writerow([output.name, job["user"], datetime.now(timezone.utc).isoformat(), json.dumps(words, ensure_ascii=False)])
                file.flush()
                os.fsync(file.fileno())
            for parent in (output.parent, DATA):
                directory = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            job["file"] = output
            progress(job, f"[OK       ] File APKG: {output.name}")
            finish(job, "done")
    except ConversionCancelled:
        finish(job, "cancelled")
    except Exception:
        output.unlink(missing_ok=True)
        progress(job, "[Lỗi      ] Không thể tạo gói. Kiểm tra dịch vụ và thử lại.")
        finish(job, "failed")
    finally:
        try:
            temporary.unlink(missing_ok=True)
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
            convert(job)
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
    try:
        words = vocabulary(data.text, enforce_limit=False)
    except HTTPException as exc:
        if exc.detail == "Enter at least one word":
            words = []
        else:
            raise
    return {"words": words, "count": len(words)}


@app.post("/api/jobs", status_code=202)
def start(data: Input, response: Response, session: str | None = Cookie(default=None)):
    user = current_user(response, session)
    words = vocabulary(data.text)
    job_id = uuid4().hex
    started = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    with lock:
        active = pending.get(user) or workers.get(user)
        if active and active["state"] not in {"done", "failed"} and not cancelled(active):
            raise HTTPException(409, "A conversion is already running. Please wait.")
        if active:
            finish(active, "cancelled")
        for old_id in [key for key, value in jobs.items() if value["created"] + 3600 < time.time()]:
            del jobs[old_id]
        filenames = {job["filename"] for job in jobs.values()}
        filename = f"{started:%d%m%y-%H%M%S}-{len(words)}_words.apkg"
        while filename in filenames or (DATA / "history" / filename).exists():
            started += timedelta(seconds=1)
            filename = f"{started:%d%m%y-%H%M%S}-{len(words)}_words.apkg"
        job = {"user": user, "created": time.time(), "filename": filename,
               "condition": threading.Condition(), "events": [], "percent": 5,
               "file": None, "downloaded": False, "words": words,
               "state": "queued", "heartbeat": time.monotonic()}
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
    return {"id": job_id}


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
            raise HTTPException(404, "Package unavailable")
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

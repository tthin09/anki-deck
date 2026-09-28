"""Local web adapter for the vocabulary-to-APKG generator."""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from anki_deck import generate_package, progress_sink, msg

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ANKI_DATA_DIR", str(ROOT / "data")))
SESSION_AGE = 8 * 60 * 60
sessions: dict[str, tuple[str, float]] = {}
jobs: dict[str, dict] = {}
lock = threading.RLock()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"{salt.hex()}:{key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = (bytes.fromhex(part) for part in stored.split(":"))
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000), expected)
    except (ValueError, TypeError):
        return False


def vocabulary(text: str, enforce_limit: bool = True) -> list[str]:
    if len(text.encode("utf-8")) > 32_000:
        raise HTTPException(422, "Input is too large")
    seen: set[str] = set()
    words = []
    for line in text.splitlines():
        word = line.strip()
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            words.append(word)
            if enforce_limit and len(words) > 100:
                raise HTTPException(422, "Maximum 100 unique words")
    if not words:
        raise HTTPException(422, "Enter at least one word")
    return words


class Login(BaseModel):
    username: str
    password: str


class Input(BaseModel):
    text: str = Field(max_length=32_000)


def current_user(session: str | None = Cookie(default=None)) -> str:
    with lock:
        entry = sessions.get(session or "")
        if not entry or entry[1] <= time.time():
            raise HTTPException(401, "Login required")
        return entry[0]


def job_for(job_id: str, user: str) -> dict:
    with lock:
        job = jobs.get(job_id)
        if not job or job["user"] != user or job["created"] + 3600 < time.time():
            raise HTTPException(404, "Conversion not found")
        return job


@app.post("/api/login")
def login(credentials: Login, response: Response):
    try:
        accounts = json.loads((DATA / "accounts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Accounts not configured")
    if not isinstance(accounts, dict):
        raise HTTPException(503, "Accounts not configured")
    stored = accounts.get(credentials.username)
    if not isinstance(stored, str) or not verify_password(credentials.password, stored):
        raise HTTPException(401, "Invalid credentials")
    token = secrets.token_urlsafe(32)
    with lock:
        sessions[token] = (credentials.username, time.time() + SESSION_AGE)
    response.set_cookie("session", token, httponly=True, samesite="strict", max_age=SESSION_AGE, path="/")
    return {"username": credentials.username}


@app.get("/api/me")
def me(session: str | None = Cookie(default=None)):
    return {"username": current_user(session)}


@app.post("/api/logout")
def logout(response: Response, session: str | None = Cookie(default=None)):
    with lock:
        sessions.pop(session or "", None)
    response.delete_cookie("session", path="/")
    return {"ok": True}


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


def convert(job_id: str, words: list[str]):
    job = jobs[job_id]
    token = progress_sink.set(lambda line: progress(job, line))
    output = DATA / "history" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{job_id}.apkg"
    try:
        key = os.environ["GEMINI_API_KEY"]
        output.parent.mkdir(parents=True, exist_ok=True)
        config = {"gemini_api_key": key, "model": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
                  "deck_name": "English Vocabulary", "chunk_size": 30}
        generate_package(ROOT, config, words, output)
        # ponytail: one process holds this lock; use a database if multiple server workers are needed.
        with lock:
            path = DATA / "history" / "conversions.csv"
            with path.open("a", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                if file.tell() == 0:
                    writer.writerow(["filename", "uploader", "created_utc", "words"])
                writer.writerow([output.name, job["user"], datetime.now(timezone.utc).isoformat(), json.dumps(words, ensure_ascii=False)])
            job["file"] = output
        msg("OK", f"File APKG: {output.name}")
        with job["condition"]:
            job["events"].append({"type": "done", "percent": 100})
            job["condition"].notify_all()
    except Exception:
        output.unlink(missing_ok=True)
        progress(job, "[Lỗi      ] Không thể tạo gói. Kiểm tra dịch vụ và thử lại.")
        with job["condition"]:
            job["events"].append({"type": "failed"})
            job["condition"].notify_all()
    finally:
        progress_sink.reset(token)


@app.post("/api/preview")
def preview(data: Input, session: str | None = Cookie(default=None)):
    current_user(session)
    try:
        words = vocabulary(data.text, enforce_limit=False)
    except HTTPException as exc:
        if exc.detail == "Enter at least one word":
            words = []
        else:
            raise
    return {"words": words, "count": len(words)}


@app.post("/api/jobs", status_code=202)
def start(data: Input, session: str | None = Cookie(default=None)):
    user = current_user(session)
    words = vocabulary(data.text)
    job_id = uuid4().hex
    with lock:
        for old_id in [key for key, value in jobs.items() if value["created"] + 3600 < time.time()]:
            del jobs[old_id]
        jobs[job_id] = {"user": user, "created": time.time(), "condition": threading.Condition(),
                        "events": [], "percent": 5, "file": None, "downloaded": False}
    threading.Thread(target=convert, args=(job_id, words), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}/events")
def events(job_id: str, session: str | None = Cookie(default=None)):
    job = job_for(job_id, current_user(session))

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
                if event["type"] in ("done", "failed"):
                    return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str, session: str | None = Cookie(default=None)):
    job = job_for(job_id, current_user(session))
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash-password", action="store_true", help="Prompt for a password and print its hash")
    args = parser.parse_args()
    if args.hash_password:
        print(hash_password(getpass.getpass("Password: ")))

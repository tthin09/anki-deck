"""Local, network-free checks of the web conversion boundary."""
import asyncio
import csv
import json
import os
import sqlite3
import zipfile
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import web_app as web
import anki_deck as generator


class WebFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        (self.data / "accounts.json").write_text(json.dumps({"alice": web.hash_password("correct"),
                                                       "bob": web.hash_password("other")}), encoding="utf-8")
        self.data_patch = patch.object(web, "DATA", self.data)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        with web.lock:
            web.sessions.clear()
            web.jobs.clear()
            web.workers.clear()
            web.pending.clear()
        self.client = TestClient(web.app)
        self.addCleanup(self.client.close)

    def login(self, username="alice", password="correct"):
        return self.client.post("/api/login", json={"username": username, "password": password})

    def test_auth_preview_and_limits(self):
        self.assertEqual(self.client.post("/api/preview", json={"text": "apple"}).status_code, 401)
        self.assertEqual(self.login(password="wrong").status_code, 401)
        self.assertEqual(self.login().json(), {"username": "alice"})
        self.assertNotIn("correct", str(self.client.get("/api/me").json()))
        self.assertEqual(self.client.post("/api/preview", json={"text": " Apple \nbook\napple\n\nStraße\nSTRASSE"}).json(),
                         {"count": 3, "words": ["Apple", "book", "Straße"]})
        self.assertEqual(self.client.post("/api/jobs", json={"text": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/preview", json={"text": "\n"}).json()["count"], 0)
        hundred = "\n".join(f"word{i}" for i in range(100))
        self.assertEqual(self.client.post("/api/preview", json={"text": hundred}).json()["count"], 100)
        self.assertEqual(self.client.post("/api/jobs", json={"text": hundred + "\nword100"}).status_code, 422)
        self.assertEqual(self.client.post("/api/jobs", json={"text": "x" * 32001}).status_code, 413)
        self.assertEqual(self.client.post("/api/preview", json={"text": "😀" * 8100}).status_code, 413)
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_conversion_history_progress_ownership_and_one_download(self):
        self.login()
        def fake_generate(root, config, words, output):
            self.assertEqual(words, ["Apple", "book"])
            web.msg("Đang chạy", "Dùng AI tạo thẻ từ vựng")
            web.msg("Đang chạy", "Lấy audio")
            web.msg("Đang chạy", "Đóng gói")
            output.write_bytes(b"sample package")
            return output

        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate):
            job = self.client.post("/api/jobs", json={"text": "Apple\nbook\napple"})
            self.assertEqual(job.status_code, 202)
            job_id = job.json()["id"]
            # Other users cannot observe events or download another user's package.
            bob = TestClient(web.app)
            try:
                bob.post("/api/login", json={"username": "bob", "password": "other"})
                self.assertEqual(bob.get(f"/api/jobs/{job_id}/events").status_code, 404)
                self.assertEqual(bob.get(f"/api/jobs/{job_id}/download").status_code, 404)
            finally:
                bob.close()
            with self.client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                self.assertEqual(response.status_code, 200)
                events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
            self.assertEqual(events[-1]["type"], "done")
            self.assertEqual(events[-1]["percent"], 100)
            self.assertTrue(any("Lấy audio" in item.get("text", "") for item in events))
            result = self.client.get(f"/api/jobs/{job_id}/download")
            self.assertEqual(result.content, b"sample package")
            self.assertRegex(result.headers["content-disposition"], r'filename="\d{6}-\d{6}-2_words\.apkg"')
            self.assertEqual(self.client.get(f"/api/jobs/{job_id}/download").status_code, 404)
            self.assertEqual(len(list((self.data / "history").glob("*.apkg"))), 1)
            with (self.data / "history" / "conversions.csv").open(encoding="utf-8", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["uploader"], "alice")
            self.assertEqual(json.loads(rows[0]["words"]), ["Apple", "book"])
            self.assertEqual(rows[0]["filename"], result.headers["content-disposition"].split('filename="')[1].split('"')[0])

    def test_parallel_conversions_keep_distinct_packages_and_csv_rows(self):
        self.login()
        def fake_generate(root, config, words, output):
            output.write_bytes(words[0].encode())
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate), TestClient(web.app) as bob:
            bob.post("/api/login", json={"username": "bob", "password": "other"})
            clients = (self.client, bob)
            ids = [client.post("/api/jobs", json={"text": word}).json()["id"] for client, word in zip(clients, ("apple", "book"))]
            for client, job_id in zip(clients, ids):
                with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                    self.assertIn('"type": "done"', "".join(response.iter_text()))
            self.assertEqual([client.get(f"/api/jobs/{job_id}/download").content for client, job_id in zip(clients, ids)], [b"apple", b"book"])
        self.assertEqual(len(list((self.data / "history").glob("*.apkg"))), 2)
        with (self.data / "history" / "conversions.csv").open(encoding="utf-8", newline="") as file:
            self.assertEqual(len(list(csv.DictReader(file))), 2)

    def test_body_limit_and_single_word_rules(self):
        self.login()
        body = json.dumps({"text": "apple"}).encode()
        allowed = body + b" " * (8191 - len(body))
        self.assertEqual(self.client.post("/api/preview", content=allowed, headers={"Content-Type": "application/json"}).status_code, 200)
        for path in ("/api/preview", "/api/login", "/api/jobs", "/api/logout"):
            self.assertEqual(self.client.post(path, content=allowed + b" ").status_code, 413)
        for word in ("two words", "two\twords", "two\u00a0words", "x" * 51):
            response = self.client.post("/api/preview", json={"text": "apple\n" + word})
            self.assertEqual(response.status_code, 422)
            self.assertIn("Line 2", response.json()["detail"])
        response = self.client.post("/api/preview", json={"text": "  Apple  \n\nAPPLE\n" + "é" * 50})
        self.assertEqual(response.json()["words"], ["Apple", "é" * 50])

    def test_chunked_body_is_rejected_before_application(self):
        async def exercise():
            called, sent = [], []
            async def application(scope, receive, send):
                called.append(True)
            chunks = iter([{"type": "http.request", "body": b"x" * 4096, "more_body": True},
                           {"type": "http.request", "body": b"x" * 4096, "more_body": False}])
            async def receive():
                return next(chunks)
            async def send(message):
                sent.append(message)
            await web.APIBodyLimit(application)({"type": "http", "path": "/api/jobs", "headers": []}, receive, send)
            self.assertEqual(called, [])
            self.assertEqual(sent[0]["status"], 413)
        asyncio.run(exercise())

    def test_cancel_waits_for_provider_and_keeps_only_latest_replacement(self):
        self.login()
        started, release, replacement_started = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def fake_generate(root, config, words, output):
            calls.append(words[0])
            if words == ["first"]:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("test timed out")
                generator.check_cancelled()
            else:
                replacement_started.set()
                output.write_bytes(words[0].encode())
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate):
            try:
                first = self.client.post("/api/jobs", json={"text": "first"}).json()["id"]
                self.assertTrue(started.wait(2))
                response = self.client.post("/api/jobs", json={"text": "duplicate"})
                self.assertEqual(response.status_code, 409)
                self.assertIn("already running", response.json()["detail"])
                with TestClient(web.app) as bob:
                    bob.post("/api/login", json={"username": "bob", "password": "other"})
                    self.assertEqual(bob.post(f"/api/jobs/{first}/cancel").status_code, 404)
                    self.assertEqual(bob.post(f"/api/jobs/{first}/heartbeat").status_code, 404)
                self.assertEqual(self.client.post(f"/api/jobs/{first}/cancel").status_code, 200)
                second = self.client.post("/api/jobs", json={"text": "second"}).json()["id"]
                self.assertEqual(self.client.post("/api/jobs", json={"text": "duplicate"}).status_code, 409)
                self.client.post(f"/api/jobs/{second}/cancel")
                third = self.client.post("/api/jobs", json={"text": "third"}).json()["id"]
                self.assertEqual(calls, ["first"])
                release.set()
                self.assertTrue(replacement_started.wait(2))
                with self.client.stream("GET", f"/api/jobs/{third}/events") as response:
                    self.assertIn('"type": "done"', "".join(response.iter_text()))
                self.assertEqual(calls, ["first", "third"])
                for job_id in (first, second):
                    self.assertEqual(self.client.get(f"/api/jobs/{job_id}/download").status_code, 404)
                self.assertEqual(self.client.get(f"/api/jobs/{third}/download").content, b"third")
                self.assertEqual(len(list((self.data / "history").glob("*.apkg"))), 1)
                self.assertEqual(list((self.data / "history").glob("*.part")), [])
            finally:
                release.set()

    def test_missing_heartbeat_cancels_and_cannot_be_revived(self):
        self.login()
        started, release = threading.Event(), threading.Event()
        def fake_generate(root, config, words, output):
            started.set()
            release.wait(5)
            generator.check_cancelled()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate):
            try:
                job_id = self.client.post("/api/jobs", json={"text": "apple"}).json()["id"]
                self.assertTrue(started.wait(2))
                self.assertEqual(self.client.post(f"/api/jobs/{job_id}/heartbeat").json()["state"], "running")
                now = time.monotonic()
                with patch.object(web.time, "monotonic", return_value=now + 31):
                    web.expire_job(web.jobs[job_id])  # Fire the lease callback without a 30-second test sleep.
                    self.assertEqual(self.client.post(f"/api/jobs/{job_id}/heartbeat").json()["state"], "cancelled")
                self.assertEqual(self.client.post(f"/api/jobs/{job_id}/heartbeat").json()["state"], "cancelled")
                self.assertEqual(self.client.get(f"/api/jobs/{job_id}/download").status_code, 404)
            finally:
                release.set()
                deadline = time.monotonic() + 2
                while web.workers and time.monotonic() < deadline:
                    time.sleep(.01)

    def test_deck_html_allowlist_and_plain_text_reverse_fields(self):
        malicious = '<b onclick="bad()">word</b><br/><i style="color:red">meaning</i><img src="https://evil"><script>bad()</script><iframe>bad()</iframe>'
        note = generator.package_note(malicious, 'A & B', [], {"filename": "safe.mp3"}, "Front")
        self.assertTrue(note["fields"]["Front"].startswith('<b>word</b><br><i>meaning</i>'))
        self.assertNotIn("bad", note["fields"]["Front"])
        self.assertNotIn("https://evil", note["fields"]["Front"])
        self.assertIn("[sound:safe.mp3]", note["fields"]["Front"])
        self.assertEqual(note["fields"]["Back"], "A &amp; B")
        reverse = generator.make_reverse_note({"word": "apple", "part_of_speech": "n"},
            {"sentence": '<b>I ate</b> <str>apple</str>.', "vietnamese_hint": '<script>bad()</script>'})
        self.assertNotIn("<script>", reverse["front"])
        self.assertNotIn("<b>", reverse["front"])
        self.assertIn("&lt;b&gt;", reverse["front"])

    def test_audio_rate_limits_retry_with_smaller_batches(self):
        original = generator.wiktionary_audio
        attempts = {}
        def flaky_audio(word):
            attempts[word] = attempts.get(word, 0) + 1
            if attempts[word] == 1:
                raise RuntimeError("Wiktionary trả về lỗi 429.")
            return {"url": "https://example.com/audio.mp3", "filename": f"{word}.mp3"}
        cards = [{"word": f"word{i}"} for i in range(5)]
        with patch.object(generator, "wiktionary_audio", new=flaky_audio), \
             patch.object(generator, "google_tts_audio", new=lambda word: None):
            generator.enrich_audio(cards, [], None)
        self.assertTrue(all(card["audio"] for card in cards))
        self.assertTrue(all(count > 1 for count in attempts.values()))

    def test_real_package_boundary_with_fake_ai_and_audio(self):
        card = {"word": "apple", "part_of_speech": "n", "ipa": "/ˈæp.əl/", "vietnamese_meaning": "táo",
                "word_forms": "apples (n)", "example_sentence": "I ate an apple.", "synonyms": ["fruit"],
                "anki_front_html": "apple (n)", "anki_back_html": "táo"}
        reverse = {"word": "apple", "front": "I ate an ____ (táo).", "back": "apple (n)", "answer": "apple"}
        def fake_audio(cards, reverse_cards, directory):
            audio_path = directory / "apple.mp3"
            audio_path.write_bytes(b"ID3sample")
            audio = {"path": str(audio_path), "filename": "apple.mp3"}
            cards[0]["audio"] = audio
            reverse_cards[0]["audio"] = audio

        self.assertFalse(hasattr(generator, "import_apkg"))
        self.assertFalse(hasattr(generator, "anki"))
        with patch.object(generator, "gemini_cards", return_value=[card]) as ai, \
             patch.object(generator, "gemini_reverse_cards", return_value=[reverse]), \
             patch.object(generator, "enrich_audio", side_effect=fake_audio):
            result = self.data / "apple.apkg"
            generator.generate_package(Path(__file__).resolve().parents[1],
                                       {"gemini_api_key": "fake", "chunk_size": 30, "deck_name": "English Vocabulary"},
                                       ["apple"], result)
            self.assertEqual(ai.call_count, 1)
            with zipfile.ZipFile(result) as package:
                self.assertIn("collection.anki2", package.namelist())
                collection = self.data / "collection.anki2"
                collection.write_bytes(package.read("collection.anki2"))
            database = sqlite3.connect(collection)
            try:
                fields = [row[0].split("\x1f") for row in database.execute("select flds from notes")]
                self.assertEqual(len(fields), 2)
                self.assertTrue(any("[sound:apple.mp3]" in front for front, _ in fields))
                self.assertTrue(any("[sound:apple.mp3]" in back for _, back in fields))
            finally:
                database.close()

    def test_failed_conversion_does_not_log_or_archive(self):
        self.login()
        def fail(*args):
            raise RuntimeError("secret provider failure")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fail):
            job_id = self.client.post("/api/jobs", json={"text": "apple"}).json()["id"]
            with self.client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                output = "".join(response.iter_text())
            self.assertIn('"type": "failed"', output)
            self.assertNotIn("secret", output)
            self.assertEqual(self.client.get(f"/api/jobs/{job_id}/download").status_code, 404)
            self.assertFalse((self.data / "history" / "conversions.csv").exists())
            self.assertEqual(list((self.data / "history").glob("*.apkg")), [])


if __name__ == "__main__":
    unittest.main()

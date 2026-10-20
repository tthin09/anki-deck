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
        self.data_patch = patch.object(web, "DATA", self.data)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        with web.lock:
            web.jobs.clear()
            web.workers.clear()
            web.pending.clear()
        self.client = TestClient(web.app)
        self.addCleanup(self.client.close)

    def test_anonymous_browser_id_preview_and_limits(self):
        self.assertEqual(self.client.post("/api/login", json={}).status_code, 405)
        self.assertEqual(len(self.client.post("/api/preview", json={"text": "apple"}).cookies["session"]), 43)
        self.assertEqual(self.client.post("/api/preview", json={"text": " Apple \nbook\napple\n\nStraße\nSTRASSE"}).json(),
                         {"count": 3, "words": ["Apple", "book", "Straße"]})
        self.assertEqual(self.client.post("/api/jobs", json={"text": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/preview", json={"text": "\n"}).json()["count"], 0)
        hundred = "\n".join(f"word{i}" for i in range(100))
        self.assertEqual(self.client.post("/api/preview", json={"text": hundred}).json()["count"], 100)
        self.assertEqual(self.client.post("/api/jobs", json={"text": hundred + "\nword100"}).status_code, 422)
        self.assertEqual(self.client.post("/api/jobs", json={"text": "x" * 32001}).status_code, 413)
        self.assertEqual(self.client.post("/api/preview", json={"text": "😀" * 8100}).status_code, 413)

    def test_conversion_history_progress_ownership_and_one_download(self):
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
            # Other browsers cannot observe events or download this browser's package.
            bob = TestClient(web.app)
            try:
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
            self.assertEqual(rows[0]["uploader"], self.client.cookies["session"])
            self.assertEqual(json.loads(rows[0]["words"]), ["Apple", "book"])
            self.assertEqual(rows[0]["filename"], result.headers["content-disposition"].split('filename="')[1].split('"')[0])

    def test_parallel_conversions_keep_distinct_packages_and_csv_rows(self):
        def fake_generate(root, config, words, output):
            output.write_bytes(words[0].encode())
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate), TestClient(web.app) as bob:
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
        body = json.dumps({"text": "apple"}).encode()
        allowed = body + b" " * (8191 - len(body))
        self.assertEqual(self.client.post("/api/preview", content=allowed, headers={"Content-Type": "application/json"}).status_code, 200)
        for path in ("/api/preview", "/api/jobs"):
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
            {"sentence": '<b>I ate</b> <str>apple</str>.', "part_of_speech": "n", "vietnamese_hint": '<script>bad()</script>'})
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
        with patch.object(generator, "generate_cards", return_value=([card], [reverse])) as ai, \
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


CARD = {"word": "like", "example_sentence": "I like tea.", "vietnamese_meaning": "thích", "part_of_speech": "v",
        "ipa": "/laɪk/", "word_forms": "liked (v)", "synonyms": ["enjoy"],
        "anki_front_html": "like (v)", "anki_back_html": "thích"}
PRACTICE = {"word": "like", "sentence": "They <str>liked</str> it.", "part_of_speech": "v", "vietnamese_hint": "thích"}


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.body


class FakeLLM:
    """Stands in for the local vLLM server and Gemini at the urlopen boundary."""
    def __init__(self, local_down=False, verify=None):
        self.local_down, self.calls, self.cards, self.practice = local_down, [], CARD, PRACTICE
        self.verify = verify or (lambda round_number: {"pairs": [{"word": "like", "check": "ok", "card": CARD,
                                                                  "practice_card": PRACTICE}]})

    def __call__(self, request, timeout=None):
        url = request.full_url
        body = json.loads(request.data) if request.data else None
        stage = None
        if "generativelanguage" in url:
            prompt = body["contents"][0]["parts"][0]["text"].split()[0]
            stage = "gemini:" + {"Cards": "cards", "Practice": "practice_cards", "Verify": "verification"}[prompt]
        elif self.local_down:
            raise generator.URLError("connection refused")
        elif url.endswith("/v1/models"):
            return FakeResponse({"data": [{"id": "qwen-test"}]})
        else:
            stage = body["response_format"]["json_schema"]["name"]
        self.calls.append(stage)
        name = stage.split(":")[-1]
        if name == "cards":
            data = {"cards": [self.cards]}
        elif name == "practice_cards":
            data = {"cards": [self.practice]}
        else:
            data = self.verify(len([c for c in self.calls if c.endswith("verification")]))
        text = json.dumps(data)
        if stage.startswith("gemini"):
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}}]})
        return FakeResponse({"choices": [{"message": {"content": text}}]})


class CardGeneration(unittest.TestCase):
    config = {"gemini_api_key": "fake", "model": "gemini-test", "llm_base_url": "http://llm:8000", "chunk_size": 30}

    def generate(self, llm):
        lines = []
        token = generator.progress_sink.set(lines.append)
        try:
            with patch.object(generator, "urlopen", new=llm):
                cards, practice = generator.generate_cards(["like"], "Cards prompt", "Practice prompt", "Verify prompt", self.config)
        finally:
            generator.progress_sink.reset(token)
        return cards, practice, lines

    def test_local_llm_down_falls_back_to_gemini(self):
        llm = FakeLLM(local_down=True)
        cards, practice, _ = self.generate(llm)
        self.assertEqual(cards[0]["part_of_speech"], "v")
        self.assertEqual(practice[0]["back"], "liked (v)")
        self.assertIn("gemini:cards", llm.calls)

    def test_verification_fixes_wrong_part_of_speech_and_stops_when_nothing_changes(self):
        wrong = {**CARD, "part_of_speech": "n", "anki_front_html": "like (n)"}
        llm = FakeLLM()
        llm.cards = wrong
        llm.practice = {**PRACTICE, "part_of_speech": "n", "sentence": "There is no <str>like</str> here."}
        llm.verify = lambda round_number: {"pairs": [{"word": "like", "check": "like is a verb", "card": CARD,
                                                     "practice_card": PRACTICE}]}
        cards, practice, lines = self.generate(llm)
        self.assertEqual(cards[0]["part_of_speech"], "v")
        self.assertEqual(cards[0]["anki_front_html"], "like (v)")
        self.assertEqual(practice[0]["back"], "liked (v)")
        self.assertEqual(llm.calls.count("verification"), 2)
        self.assertTrue(any("Đã sửa 1 thẻ" in line for line in lines))
        self.assertTrue(any("Đã sửa 0 thẻ" in line for line in lines))

    def test_verification_keeps_original_when_correction_is_invalid(self):
        llm = FakeLLM()
        llm.verify = lambda round_number: {"pairs": [{"word": "like", "check": "", "card": {**CARD, "part_of_speech": "verb"},
                                                     "practice_card": PRACTICE}]}
        cards, practice, _ = self.generate(llm)
        self.assertEqual(cards[0]["part_of_speech"], "v")
        self.assertEqual(llm.calls.count("verification"), 1)

    def test_failed_verification_ships_unverified_cards_with_warning(self):
        llm = FakeLLM()
        llm.verify = lambda round_number: ["not", "pairs"]
        cards, practice, lines = self.generate(llm)
        self.assertEqual(practice[0]["back"], "liked (v)")
        self.assertTrue(any("Cảnh báo" in line and "chưa kiểm tra" in line for line in lines))

    def test_practice_card_shows_only_the_part_of_speech_it_uses(self):
        llm = FakeLLM()
        llm.cards = {**CARD, "part_of_speech": "n/v"}
        llm.verify = lambda round_number: {"pairs": [{"word": "like", "check": "OK", "card": llm.cards,
                                                     "practice_card": PRACTICE}]}
        _, practice, _ = self.generate(llm)
        self.assertEqual(practice[0]["back"], "liked (v)")

    def test_practice_card_with_a_part_of_speech_outside_the_card_is_rejected(self):
        llm = FakeLLM()
        llm.practice = {**PRACTICE, "part_of_speech": "n"}
        with self.assertRaisesRegex(RuntimeError, "sai từ loại"):
            self.generate(llm)


if __name__ == "__main__":
    unittest.main()

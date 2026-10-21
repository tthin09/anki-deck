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


def fake_research(words, prompt, config):
    return [{"input": word, "entry": word, "corrected": False,
             "senses": [{"part_of_speech": "n", "vietnamese_meaning": "nghĩa", "example_sentence": f"A <b>{word}</b>."}]}
            for word in words]


def research(client, text, researcher=fake_research):
    """Run research to completion and return (job id, done event)."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "research_entries", researcher):
        response = client.post("/api/research", json={"text": text})
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
            events = [json.loads(line[6:]) for line in stream.iter_lines() if line.startswith("data: ")]
    return job_id, events[-1]


def convert(client, text):
    """Research `text` and convert the first sense of every entry."""
    research_id, done = research(client, text)
    return client.post("/api/jobs", json={"research": research_id, "senses": [[i, 0] for i in range(len(done["result"]))]})


def entries(senses):
    return [sense["entry"] for sense in senses]


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
                         {"count": 3, "words": ["Apple", "book", "Straße"], "error": ""})
        self.assertEqual(self.client.post("/api/research", json={"text": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/preview", json={"text": "\n"}).json()["count"], 0)
        hundred = "\n".join(f"word{i}" for i in range(100))
        self.assertEqual(self.client.post("/api/preview", json={"text": hundred}).json()["count"], 100)
        self.assertEqual(self.client.post("/api/research", json={"text": hundred + "\nword100"}).status_code, 422)
        self.assertEqual(self.client.post("/api/research", json={"text": "x" * 32001}).status_code, 413)
        self.assertEqual(self.client.post("/api/preview", json={"text": "😀" * 8100}).status_code, 413)

    def test_conversion_history_progress_ownership_and_one_download(self):
        def fake_generate(root, config, senses, output):
            self.assertEqual(entries(senses), ["Apple", "book"])
            web.msg("Đang chạy", "Dùng AI tạo thẻ từ vựng")
            web.msg("Đang chạy", "Lấy audio")
            web.msg("Đang chạy", "Đóng gói")
            output.write_bytes(b"sample package")
            return output

        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate):
            job = convert(self.client, "Apple\nbook\napple")
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
            self.assertEqual(json.loads(rows[0]["words"]), ["Apple (n)", "book (n)"])
            self.assertEqual(rows[0]["filename"], result.headers["content-disposition"].split('filename="')[1].split('"')[0])

    def test_parallel_conversions_keep_distinct_packages_and_csv_rows(self):
        def fake_generate(root, config, senses, output):
            output.write_bytes(senses[0]["entry"].encode())
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate), TestClient(web.app) as bob:
            clients = (self.client, bob)
            ids = [convert(client, word).json()["id"] for client, word in zip(clients, ("apple", "book"))]
            for client, job_id in zip(clients, ids):
                with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                    self.assertIn('"type": "done"', "".join(response.iter_text()))
            self.assertEqual([client.get(f"/api/jobs/{job_id}/download").content for client, job_id in zip(clients, ids)], [b"apple", b"book"])
        self.assertEqual(len(list((self.data / "history").glob("*.apkg"))), 2)
        with (self.data / "history" / "conversions.csv").open(encoding="utf-8", newline="") as file:
            self.assertEqual(len(list(csv.DictReader(file))), 2)

    def test_body_limit_and_entry_rules(self):
        body = json.dumps({"text": "apple"}).encode()
        allowed = body + b" " * (8191 - len(body))
        self.assertEqual(self.client.post("/api/preview", content=allowed, headers={"Content-Type": "application/json"}).status_code, 200)
        for path in ("/api/preview", "/api/jobs"):
            self.assertEqual(self.client.post(path, content=allowed + b" ").status_code, 413)
        # Preview keeps the valid entries and names the bad line; research refuses the whole input.
        preview = self.client.post("/api/preview", json={"text": "apple\n" + "x" * 51}).json()
        self.assertEqual(preview["words"], ["apple"])
        self.assertIn("Line 2", preview["error"])
        response = self.client.post("/api/research", json={"text": "apple\n" + "x" * 51})
        self.assertEqual(response.status_code, 422)
        self.assertIn("Line 2", response.json()["detail"])
        # Phrases are entries; inner whitespace collapses to one space, so these are the same entry.
        preview = self.client.post("/api/preview", json={"text": "as well  as\nAs\u00a0well as\nexcessive amount"}).json()
        self.assertEqual(preview, {"words": ["as well as", "excessive amount"], "count": 2, "error": ""})
        response = self.client.post("/api/preview", json={"text": "  Apple  \n\nAPPLE\n" + "é" * 50})
        self.assertEqual(response.json()["words"], ["Apple", "é" * 50])

    def test_pasted_lists(self):
        pastes = {
            # Rows copied from the vocabulary spreadsheets, with and without the header row.
            "No\tWord\tPart of Speech\tVietnamese Meaning\r\n1\tAdvocate\tv/n\tủng hộ, biện hộ\r\n2\tCognitive\tadj\tnhận thức\r\n": ["Advocate", "Cognitive"],
            "1\tAdvocate\tv/n\tủng hộ, biện hộ\n2.0\tCognitive\tadj": ["Advocate", "Cognitive"],
            "apple\tquả táo\nbook\tsách": ["apple", "book"],
            "\napple\nNo\tWord\tPart of Speech\n1\tAdvocate\tv/n": ["apple", "Advocate"],
            "1\tword\tn\n2\tbook\tn": ["word", "book"],
            "apple, book; cat,\ndog": ["apple", "book", "cat", "dog"],
            "• apple\n- book\n3. cat\n4) dog": ["apple", "book", "cat", "dog"],
        }
        for text, words in pastes.items():
            self.assertEqual(self.client.post("/api/preview", json={"text": text}).json(), {"words": words, "count": len(words), "error": ""})

    def test_research_returns_senses_and_conversion_uses_only_chosen_ones(self):
        def senses_of_fine(words, prompt, config):
            self.assertEqual(words, ["fine", "as well as"])
            return [{"input": "fine", "entry": "fine", "corrected": False, "senses": [
                        {"part_of_speech": "adj", "vietnamese_meaning": "ổn", "example_sentence": "I am <b>fine</b>."},
                        {"part_of_speech": "n", "vietnamese_meaning": "tiền phạt", "example_sentence": "A parking <b>fine</b>."}]},
                    {"input": "as well as", "entry": "as well as", "corrected": False, "senses": [
                        {"part_of_speech": "", "vietnamese_meaning": "cũng như", "example_sentence": "Tea <b>as well as</b> coffee."}]}]
        received = []
        def fake_generate(root, config, senses, output):
            received.extend(senses)
            output.write_bytes(b"deck")
        research_id, done = research(self.client, "fine\nas well as", senses_of_fine)
        self.assertEqual(done["type"], "done")
        self.assertEqual([len(item["senses"]) for item in done["result"]], [2, 1])
        # Conversion is refused for bad choices and for other browsers' research.
        for chosen in ([], [[0, 2]], [[2, 0]], [[-1, 0]]):
            self.assertEqual(self.client.post("/api/jobs", json={"research": research_id, "senses": chosen}).status_code, 422)
        with TestClient(web.app) as bob:
            self.assertEqual(bob.post("/api/jobs", json={"research": research_id, "senses": [[0, 0]]}).status_code, 404)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate):
            job_id = self.client.post("/api/jobs", json={"research": research_id, "senses": [[0, 1], [1, 0], [0, 1]]}).json()["id"]
            with self.client.stream("GET", f"/api/jobs/{job_id}/events") as response:
                self.assertIn('"type": "done"', "".join(response.iter_text()))
        self.assertEqual(received, [
            {"entry": "fine", "part_of_speech": "n", "vietnamese_meaning": "tiền phạt", "example_sentence": "A parking <b>fine</b>."},
            {"entry": "as well as", "part_of_speech": "", "vietnamese_meaning": "cũng như", "example_sentence": "Tea <b>as well as</b> coffee."}])

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
        def fake_generate(root, config, senses, output):
            words = entries(senses)
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
                chosen = {word: {"research": research(self.client, word)[0], "senses": [[0, 0]]}
                          for word in ("first", "second", "third", "duplicate")}
                first = self.client.post("/api/jobs", json=chosen["first"]).json()["id"]
                self.assertTrue(started.wait(2))
                self.assertEqual(self.client.post("/api/research", json={"text": "apple"}).status_code, 409)
                response = self.client.post("/api/jobs", json=chosen["duplicate"])
                self.assertEqual(response.status_code, 409)
                self.assertIn("already running", response.json()["detail"])
                with TestClient(web.app) as bob:
                    self.assertEqual(bob.post(f"/api/jobs/{first}/cancel").status_code, 404)
                    self.assertEqual(bob.post(f"/api/jobs/{first}/heartbeat").status_code, 404)
                self.assertEqual(self.client.post(f"/api/jobs/{first}/cancel").status_code, 200)
                second = self.client.post("/api/jobs", json=chosen["second"]).json()["id"]
                self.assertEqual(self.client.post("/api/jobs", json=chosen["duplicate"]).status_code, 409)
                self.client.post(f"/api/jobs/{second}/cancel")
                third = self.client.post("/api/jobs", json=chosen["third"]).json()["id"]
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
        def fake_generate(root, config, senses, output):
            started.set()
            release.wait(5)
            generator.check_cancelled()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fake_generate):
            try:
                job_id = convert(self.client, "apple").json()["id"]
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
        phrase = {"word": "as well as"}
        with patch.object(generator, "wiktionary_audio", new=flaky_audio), \
             patch.object(generator, "google_tts_audio", new=lambda word: None):
            generator.enrich_audio(cards + [phrase], [{"word": "as well as", "answer": "as well as"}], None)
        self.assertTrue(all(card["audio"] for card in cards))
        self.assertIsNone(phrase["audio"])
        self.assertNotIn("as well as", attempts)
        self.assertTrue(all(count > 1 for count in attempts.values()))

    def test_real_package_boundary_with_fake_ai_and_audio(self):
        card = {"word": "apple", "part_of_speech": "n", "ipa": "/ˈæp.əl/", "vietnamese_meaning": "táo",
                "word_forms": "apples (n)", "example_sentence": "I ate an apple.", "synonyms": ["fruit"],
                "anki_front_html": "apple (n)", "anki_back_html": "táo"}
        company = {**card, "vietnamese_meaning": "hãng Apple", "anki_front_html": "Apple (n)", "anki_back_html": "hãng Apple"}
        phrase = {**card, "word": "as well as", "part_of_speech": "", "ipa": "", "anki_front_html": "as well as",
                  "anki_back_html": "cũng như"}
        reverse = {"word": "apple", "front": "I ate an ____ (táo).", "back": "apple (n)", "answer": "apple"}
        reverses = [reverse, {**reverse, "front": "____ makes phones (hãng)."},
                    {"word": "as well as", "front": "Tea ____ coffee.", "back": "as well as", "answer": "as well as"}]
        def fake_audio(cards, reverse_cards, directory):
            audio_path = directory / "apple.mp3"
            audio_path.write_bytes(b"ID3sample")
            audio = {"path": str(audio_path), "filename": "apple.mp3"}
            for item in cards[:2] + reverse_cards[:2]:
                item["audio"] = audio

        self.assertFalse(hasattr(generator, "import_apkg"))
        self.assertFalse(hasattr(generator, "anki"))
        with patch.object(generator, "generate_cards", return_value=([card, company, phrase], reverses)) as ai, \
             patch.object(generator, "enrich_audio", side_effect=fake_audio):
            result = self.data / "apple.apkg"
            generator.generate_package(Path(__file__).resolve().parents[1],
                                       {"gemini_api_key": "fake", "chunk_size": 30, "deck_name": "English Vocabulary"},
                                       [{"entry": "apple"}], result)
            self.assertEqual(ai.call_count, 1)
            with zipfile.ZipFile(result) as package:
                self.assertIn("collection.anki2", package.namelist())
                collection = self.data / "collection.anki2"
                collection.write_bytes(package.read("collection.anki2"))
            database = sqlite3.connect(collection)
            try:
                notes = list(database.execute("select guid, flds, tags from notes"))
                fields = [row[1].split("\x1f") for row in notes]
                # Two senses of one word are separate notes, so nothing overwrites anything on import.
                self.assertEqual(len({row[0] for row in notes}), 6)
                self.assertTrue(any("[sound:apple.mp3]" in front for front, _ in fields))
                self.assertTrue(any("[sound:apple.mp3]" in back for _, back in fields))
                self.assertEqual(sum("phrase" in row[2].split() for row in notes), 2)
            finally:
                database.close()

    def test_failed_conversion_does_not_log_or_archive(self):
        def fail(*args):
            raise RuntimeError("secret provider failure")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret"}), patch.object(web, "generate_package", fail):
            job_id = convert(self.client, "apple").json()["id"]
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
LIKE = {"entry": "like", "part_of_speech": "v", "vietnamese_meaning": "thích", "example_sentence": "We <b>like</b> it."}


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
        self.requests = {}
        self.verify = verify or (lambda round_number: {"pairs": [{"word": "like", "check": "ok", "card": CARD,
                                                                  "practice_card": PRACTICE}]})

    def __call__(self, request, timeout=None):
        url = request.full_url
        body = json.loads(request.data) if request.data else None
        stage = None
        if "generativelanguage" in url:
            prompt = body["contents"][0]["parts"][0]["text"].split()[0]
            stage = "gemini:" + {"Cards": "cards", "Practice": "practice_cards", "Verify": "verification", "Research": "research"}[prompt]
        elif self.local_down:
            raise generator.URLError("connection refused")
        elif url.endswith("/v1/models"):
            return FakeResponse({"data": [{"id": "qwen-test"}]})
        else:
            stage = body["response_format"]["json_schema"]["name"]
        self.calls.append(stage)
        name = stage.split(":")[-1]
        prompt = body["contents"][0]["parts"][0]["text"] if stage.startswith("gemini") else body["messages"][0]["content"]
        self.requests[name] = json.loads(prompt.split("Input data as JSON array:\n", 1)[1])
        if name == "research":
            data = self.research
        elif name == "cards":
            data = {"cards": self.cards if isinstance(self.cards, list) else [self.cards]}
        elif name == "practice_cards":
            data = {"cards": self.practice if isinstance(self.practice, list) else [self.practice]}
        else:
            data = self.verify(len([c for c in self.calls if c.endswith("verification")]))
        text = json.dumps(data)
        if stage.startswith("gemini"):
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}}]})
        return FakeResponse({"choices": [{"message": {"content": text}}]})


class CardGeneration(unittest.TestCase):
    config = {"gemini_api_key": "fake", "model": "gemini-test", "llm_base_url": "http://llm:8000", "chunk_size": 30}

    def generate(self, llm, senses=(LIKE,)):
        lines = []
        token = generator.progress_sink.set(lines.append)
        try:
            with patch.object(generator, "urlopen", new=llm):
                cards, practice = generator.generate_cards(list(senses), "Cards prompt", "Practice prompt", "Verify prompt", self.config)
        finally:
            generator.progress_sink.reset(token)
        return cards, practice, lines

    def test_research_corrects_typos_keeps_phrases_untyped_and_caps_senses(self):
        sense = lambda pos, meaning: {"part_of_speech": pos, "vietnamese_meaning": meaning, "example_sentence": "x <b>y</b> z"}
        llm = FakeLLM()
        llm.research = {"entries": [
            {"input": "recieve", "entry": "receive", "corrected": True, "senses": [sense("v", "nhận")]},
            {"input": "As well as", "entry": "as well as", "corrected": True, "senses": [sense("conj", "cũng như")]},
            {"input": "fine", "entry": "fine", "corrected": False, "senses": [sense(pos, str(pos)) for pos in ("adj", "n", "v", "adj", "adv")]},
            {"input": "asdfgh", "entry": "asdfgh", "corrected": False, "senses": []}]}
        with patch.object(generator, "urlopen", new=llm):
            result = generator.research_entries(["recieve", "As well as", "fine", "asdfgh"], "Research prompt", self.config)
        self.assertEqual([(item["entry"], item["corrected"]) for item in result],
                         [("receive", True), ("As well as", False), ("fine", False), ("asdfgh", False)])
        self.assertEqual(result[1]["senses"][0]["part_of_speech"], "")
        self.assertEqual(len(result[2]["senses"]), 4)
        self.assertEqual(result[3]["senses"], [])
        llm.research = {"entries": llm.research["entries"][:3]}
        with patch.object(generator, "urlopen", new=llm), self.assertRaisesRegex(RuntimeError, "không trả về đủ"):
            generator.research_entries(["recieve", "As well as", "fine", "asdfgh"], "Research prompt", self.config)
        llm.research = {"entries": [{"input": "fine", "entry": "fine", "corrected": False, "senses": [sense("n/v", "x")]}]}
        with patch.object(generator, "urlopen", new=llm), self.assertRaisesRegex(RuntimeError, "không hợp lệ"):
            generator.research_entries(["fine"], "Research prompt", self.config)

    def test_local_llm_down_falls_back_to_gemini(self):
        llm = FakeLLM(local_down=True)
        cards, practice, _ = self.generate(llm)
        self.assertEqual(cards[0]["part_of_speech"], "v")
        self.assertEqual(practice[0]["back"], "liked (v)")
        self.assertIn("gemini:cards", llm.calls)

    def test_card_generation_is_told_the_chosen_sense(self):
        llm = FakeLLM()
        self.generate(llm)
        self.assertEqual(llm.requests["cards"], [{"word": "like", "part_of_speech": "v", "vietnamese_meaning": "thích",
                                                   "research_example": "We like it."}])
        self.assertEqual(llm.requests["practice_cards"][0]["avoid_sentences"], ["I like tea.", "We like it."])

    def test_card_with_a_part_of_speech_other_than_the_chosen_sense_is_rejected(self):
        for wrong in ("n", "verb"):
            llm = FakeLLM()
            llm.cards = {**CARD, "part_of_speech": wrong}
            with self.assertRaisesRegex(RuntimeError, "sai từ loại"):
                self.generate(llm)
            self.assertEqual(llm.calls, ["cards"])

    def test_two_senses_of_one_word_become_two_card_pairs_in_order(self):
        fine_adj = {"entry": "fine", "part_of_speech": "adj", "vietnamese_meaning": "ổn", "example_sentence": "I am <b>fine</b>."}
        fine_n = {"entry": "fine", "part_of_speech": "n", "vietnamese_meaning": "tiền phạt", "example_sentence": "A <b>fine</b>."}
        card = lambda pos, meaning: {**CARD, "word": "fine", "part_of_speech": pos, "vietnamese_meaning": meaning,
                                     "example_sentence": f"fine {pos}", "anki_front_html": f"fine ({pos})"}
        llm = FakeLLM()
        llm.cards = [card("adj", "ổn"), card("n", "tiền phạt")]
        llm.practice = [{**PRACTICE, "word": "fine", "part_of_speech": "adj", "sentence": "All <str>fine</str>."},
                        {**PRACTICE, "word": "fine", "part_of_speech": "n", "sentence": "Pay the <str>fine</str>."}]
        llm.verify = lambda round_number: {"pairs": [{"word": "fine", "check": "OK", "card": c, "practice_card": pr}
                                                     for c, pr in zip(llm.cards, llm.practice)]}
        cards, practice, _ = self.generate(llm, (fine_adj, fine_n))
        self.assertEqual([c["part_of_speech"] for c in cards], ["adj", "n"])
        self.assertEqual([pr["back"] for pr in practice], ["fine (adj)", "fine (n)"])

    def test_phrase_cards_have_no_part_of_speech_ipa_or_word_forms(self):
        phrase = {"entry": "as well as", "part_of_speech": "", "vietnamese_meaning": "cũng như",
                  "example_sentence": "Tea <b>as well as</b> coffee."}
        llm = FakeLLM()
        llm.cards = {**CARD, "word": "as well as", "part_of_speech": "", "ipa": "/æz/", "word_forms": "x",
                     "example_sentence": "Me as well as you.", "anki_front_html": "as well as"}
        llm.practice = {**PRACTICE, "word": "as well as", "part_of_speech": "", "sentence": "Him <str>as well as</str> her."}
        llm.verify = lambda round_number: ["skip"]
        cards, practice, _ = self.generate(llm, (phrase,))
        self.assertEqual((cards[0]["part_of_speech"], cards[0]["ipa"], cards[0]["word_forms"]), ("", "", ""))
        self.assertEqual(practice[0]["back"], "as well as")

    def test_practice_sentence_must_differ_from_the_research_example(self):
        llm = FakeLLM()
        llm.practice = {**PRACTICE, "sentence": "We <str>like</str> it."}
        with self.assertRaisesRegex(RuntimeError, "trùng câu ví dụ"):
            self.generate(llm)

    def test_verification_fixes_sentences_and_stops_when_nothing_changes(self):
        llm = FakeLLM()
        better = {**PRACTICE, "sentence": "They <str>liked</str> the film."}
        llm.verify = lambda round_number: {"pairs": [{"word": "like", "check": "awkward", "card": CARD, "practice_card": better}]}
        cards, practice, lines = self.generate(llm)
        self.assertIn("film", practice[0]["front"])
        self.assertEqual(llm.calls.count("verification"), 2)
        self.assertTrue(any("Vòng 1/2: đã sửa 1 thẻ" in line for line in lines))
        self.assertTrue(any("Vòng 2/2: đã sửa 0 thẻ" in line for line in lines))

    def test_verification_cannot_change_the_chosen_sense(self):
        for fix in ({**CARD, "part_of_speech": "n", "anki_front_html": "like (n)"}, {**CARD, "vietnamese_meaning": "giống"}):
            llm = FakeLLM()
            llm.verify = lambda round_number, fix=fix: {"pairs": [{"word": "like", "check": "", "card": fix,
                                                                   "practice_card": {**PRACTICE, "sentence": "A new <str>like</str>."}}]}
            cards, practice, _ = self.generate(llm)
            self.assertEqual((cards[0]["part_of_speech"], cards[0]["vietnamese_meaning"]), ("v", "thích"))
            self.assertIn("liked", practice[0]["front"] + practice[0]["back"])

    def test_verification_keeps_original_when_front_disagrees_with_part_of_speech(self):
        llm = FakeLLM()
        llm.verify = lambda round_number: {"pairs": [{"word": "LIKE", "check": "", "card": {**CARD, "anki_front_html": "like (n)"},
                                                     "practice_card": PRACTICE}]}
        cards, _, _ = self.generate(llm)
        self.assertEqual(cards[0]["anki_front_html"], "like (v)")

    def test_failed_verification_ships_unverified_cards_with_warning(self):
        llm = FakeLLM()
        llm.verify = lambda round_number: ["not", "pairs"]
        cards, practice, lines = self.generate(llm)
        self.assertEqual(practice[0]["back"], "liked (v)")
        self.assertTrue(any("Cảnh báo" in line and "Không kiểm tra lại hết" in line for line in lines))

    def test_prepositions_are_a_valid_part_of_speech(self):
        llm = FakeLLM()
        llm.cards = {**CARD, "word": "within", "part_of_speech": "prep", "example_sentence": "Stay within the lines.",
                     "anki_front_html": "within (prep)"}
        llm.practice = {**PRACTICE, "word": "within", "part_of_speech": "prep", "sentence": "Reply <str>within</str> a day."}
        llm.verify = lambda round_number: ["skip"]
        within = {"entry": "within", "part_of_speech": "prep", "vietnamese_meaning": "trong vòng", "example_sentence": "<b>within</b> it"}
        cards, practice, _ = self.generate(llm, (within,))
        self.assertEqual(practice[0]["back"], "within (prep)")

    def test_practice_card_with_a_part_of_speech_outside_the_card_is_rejected(self):
        llm = FakeLLM()
        llm.practice = {**PRACTICE, "part_of_speech": "n"}
        with self.assertRaisesRegex(RuntimeError, "sai từ loại"):
            self.generate(llm)


if __name__ == "__main__":
    unittest.main()

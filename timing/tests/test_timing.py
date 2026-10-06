"""Phase C tests for the canonical timing layer (stdlib unittest)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from timing import adapter, cache, phrases, schema  # noqa: E402
from timing.adapters import elevenlabs  # noqa: E402

_FIX = os.path.join(_ROOT, "tests", "fixtures")


def words(*triples):
    return [{"word": w, "start_ms": s, "end_ms": e, "confidence": None} for w, s, e in triples]


class TestElevenLabsAdapter(unittest.TestCase):
    def test_valid_char_alignment_normalizes(self):
        with open(os.path.join(_FIX, "elevenlabs_alignment.json"), encoding="utf-8") as fh:
            resp = json.load(fh)
        doc = elevenlabs.normalize(resp)
        schema.validate(doc)
        self.assertEqual("elevenlabs", doc["provider"])
        self.assertEqual(3200, doc["audio_duration_ms"])
        self.assertEqual(["Copilot", "runs", "fast."], [w["word"] for w in doc["words"]])
        self.assertEqual((0, 460), (doc["words"][0]["start_ms"], doc["words"][0]["end_ms"]))
        self.assertEqual((620, 1000), (doc["words"][1]["start_ms"], doc["words"][1]["end_ms"]))
        self.assertEqual((1220, 1900), (doc["words"][2]["start_ms"], doc["words"][2]["end_ms"]))
        self.assertEqual(1, doc["schema_version"])

    def test_word_list_seconds_normalizes(self):
        doc = elevenlabs.normalize({"words": [{"text": "Hello", "start": 0.0, "end": 0.42}],
                                    "audio_duration_seconds": 1.0})
        self.assertEqual(1000, doc["audio_duration_ms"])
        self.assertEqual((0, 420), (doc["words"][0]["start_ms"], doc["words"][0]["end_ms"]))

    def test_word_list_ms_normalizes(self):
        doc = elevenlabs.normalize({"words": [{"word": "Hi", "start_ms": 10, "end_ms": 300}],
                                    "audio_duration_ms": 500})
        self.assertEqual((10, 300), (doc["words"][0]["start_ms"], doc["words"][0]["end_ms"]))

    def test_malformed_alignment_rejected(self):
        with self.assertRaises(schema.TimingError):
            elevenlabs.normalize({"alignment": {"characters": ["a", "b"],
                                                "character_start_times_seconds": [0.0],
                                                "character_end_times_seconds": [0.1, 0.2]}})
        with self.assertRaises(schema.TimingError):
            elevenlabs.normalize({})

    def test_words_beyond_duration_rejected(self):
        with self.assertRaises(schema.TimingError):
            elevenlabs.normalize({"words": [{"text": "x", "start": 0.0, "end": 2.0}],
                                  "audio_duration_seconds": 1.0})

    def test_no_provider_fields_leak_into_canonical(self):
        doc = elevenlabs.normalize({"words": [{"text": "Hi", "start": 0.0, "end": 0.3}],
                                    "audio_duration_seconds": 1.0, "request_id": "abc",
                                    "voice_id": "v1"})
        self.assertEqual({"schema_version", "provider", "audio_duration_ms", "words"},
                         set(doc.keys()))
        self.assertEqual({"word", "start_ms", "end_ms", "confidence"},
                         set(doc["words"][0].keys()))


class TestSchema(unittest.TestCase):
    def test_negative_timestamp_rejected(self):
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 1000, words(("a", -5, 100)))

    def test_end_before_start_rejected(self):
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 1000, words(("a", 200, 100)))

    def test_zero_length_rejected(self):
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 1000, words(("a", 100, 100)))

    def test_beyond_audio_duration_rejected(self):
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 1000, words(("a", 900, 1200)))

    def test_ordering_rejected(self):
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 2000, words(("one", 500, 700), ("two", 300, 450)))

    def test_overlap_rejected(self):
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 2000, words(("one", 500, 800), ("two", 700, 900)))

    def test_confidence_range_rejected(self):
        bad = [{"word": "a", "start_ms": 0, "end_ms": 100, "confidence": 1.5}]
        with self.assertRaises(schema.TimingError):
            schema.make("elevenlabs", 1000, bad)

    def test_roundtrip(self):
        doc = schema.make("elevenlabs", 2000, words(("one", 0, 300), ("two", 400, 900)))
        again = schema.validate(json.loads(json.dumps(doc)))
        self.assertEqual(doc, again)

    def test_is_valid(self):
        self.assertTrue(schema.is_valid(schema.make("x", 500, words(("a", 0, 100)))))
        self.assertFalse(schema.is_valid({"schema_version": 1}))


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="timing-")
        self.voice = os.path.join(self.tmp, "assets", "audio", "voice", "narration.mp3")
        os.makedirs(os.path.dirname(self.voice), exist_ok=True)
        with open(self.voice, "wb") as fh:
            fh.write(b"fake-audio")
        self.doc = schema.make("elevenlabs", 2000, words(("one", 0, 300), ("two", 400, 900)))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sibling_path(self):
        self.assertTrue(cache.timing_path_for(self.voice).endswith("narration.word-timings.json"))

    def test_write_load_roundtrip(self):
        path = cache.write_for_voice(self.voice, self.doc)
        self.assertEqual(self.doc, cache.load(path))

    def test_no_overwrite_by_default(self):
        cache.write_for_voice(self.voice, self.doc)
        with self.assertRaises(FileExistsError):
            cache.write_for_voice(self.voice, self.doc)

    def test_load_cached_none_when_absent(self):
        self.assertIsNone(cache.load_cached(self.voice))

    def test_cached_reuse_never_calls_provider(self):
        cache.write_for_voice(self.voice, self.doc)
        with mock.patch.object(adapter, "normalize",
                               side_effect=AssertionError("provider must not be called")):
            got = cache.load_cached(self.voice)
        self.assertEqual(self.doc, got)


class TestPhrases(unittest.TestCase):
    def test_grouping_uses_real_word_boundaries(self):
        ws = words(("Hello", 0, 300), ("world", 320, 700), ("Again", 2000, 2400))
        groups = phrases.group(ws)
        self.assertEqual(2, len(groups))
        self.assertEqual((0, 700), (groups[0]["start_ms"], groups[0]["end_ms"]))
        self.assertEqual("Hello world", groups[0]["text"])
        self.assertEqual((2000, 2400), (groups[1]["start_ms"], groups[1]["end_ms"]))

    def test_punctuation_break(self):
        ws = words(("Stop.", 0, 300), ("Go", 320, 600))
        groups = phrases.group(ws)
        self.assertEqual(2, len(groups))
        self.assertEqual("Stop.", groups[0]["text"])

    def test_max_chars_break(self):
        ws = words(("aaaaaaaaaa", 0, 300), ("bbbbbbbbbb", 320, 600), ("cccccccccc", 620, 900))
        groups = phrases.group(ws, max_chars=12)
        self.assertEqual(3, len(groups))

    def test_empty(self):
        self.assertEqual([], phrases.group([]))

    def test_captions_validate_and_reject_overlap(self):
        caps = phrases.to_captions(words(("one", 0, 300), ("two", 400, 900)))
        phrases.validate_captions(caps)
        bad = {"captions": [{"start_ms": 0, "end_ms": 500, "text": "a"},
                            {"start_ms": 400, "end_ms": 900, "text": "b"}]}
        with self.assertRaises(schema.TimingError):
            phrases.validate_captions(bad)


class TestOffline(unittest.TestCase):
    def test_timing_package_imports_no_network_or_subprocess(self):
        root = _ROOT
        files = []
        for base, _dirs, names in os.walk(root):
            for n in names:
                path = os.path.join(base, n)
                if n.endswith(".py") and "__pycache__" not in base \
                        and (os.sep + "tests" + os.sep) not in path:
                    files.append(path)
        self.assertTrue(files)
        for path in files:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            for bad in ("import requests", "import urllib", "import socket",
                        "urlopen", "subprocess"):
                self.assertNotIn(bad, text, "%s must stay offline" % path)

    def test_no_paid_fixture_present(self):
        # fixtures must be documented provider-response mocks, never real audio
        for name in os.listdir(_FIX):
            self.assertTrue(name.endswith(".json"), "unexpected non-JSON fixture: %s" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

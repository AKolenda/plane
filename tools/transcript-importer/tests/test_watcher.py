# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from transcript_importer.client import PlaneClient, TransientError
from transcript_importer.parse import ActionItem
from transcript_importer.watcher import Config, Importer, parse_assignee_map


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail = None

    def import_items(self, items):
        if self.fail:
            raise self.fail
        self.calls.append(items)
        return [
            {"id": str(i), "identifier": f"ENG-{i}", "url": f"http://plane/acme/work-items/{i}", "created": True}
            for i, _ in enumerate(items, start=1)
        ]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ImporterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.share = self.root / "share"
        self.share.mkdir()
        self.clock = Clock()
        self.client = FakeClient()
        self.config = Config(
            directory=self.share,
            project="ENG",
            state_file=self.root / "state" / "state.json",
            assignees=parse_assignee_map("dana=dana@acme.com,Sam Lee=sam@acme.com"),
            settle_seconds=10,
            source_url_base="https://nas.local/transcripts",
        )
        self.importer = Importer(self.config, self.client, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.share / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_waits_until_the_file_stops_changing(self):
        self.write("2026/acme.txt", "Action item (Dana): send the quote\n")
        self.assertEqual(self.importer.scan(), 0)  # first sighting
        self.clock.now += 5
        self.assertEqual(self.importer.scan(), 0)  # not settled yet
        self.clock.now += 6
        self.assertEqual(self.importer.scan(), 1)

        [items] = self.client.calls
        self.assertEqual(
            items[0],
            {
                "project": "ENG",
                "external_source": "transcript",
                "external_id": f"2026/acme.txt#{ActionItem('send the quote').fingerprint}",
                "title": "send the quote",
                "description": items[0]["description"],
                "labels": ["transcript"],
                "source_url": "https://nas.local/transcripts/2026/acme.txt",
                "assignee": "dana@acme.com",
            },
        )
        self.assertIn("From call transcript 2026/acme.txt", items[0]["description"])

    def test_unchanged_files_are_not_reimported_but_edits_are(self):
        self.config.settle_seconds = 0
        path = self.write("call.md", "TODO: one\n")
        self.importer.scan()
        self.importer.scan()
        self.assertEqual(len(self.client.calls), 1)

        path.write_text("TODO: one\nTODO: two\n")
        self.importer.scan()
        self.assertEqual(len(self.client.calls), 2)
        # The unchanged item keeps its external id, so Plane updates it instead of duplicating
        self.assertEqual(self.client.calls[0][0]["external_id"], self.client.calls[1][0]["external_id"])

    def test_state_survives_a_restart(self):
        self.config.settle_seconds = 0
        self.write("call.txt", "TODO: one\n")
        self.importer.scan()
        restarted = Importer(self.config, self.client, clock=self.clock)
        restarted.scan()
        self.assertEqual(len(self.client.calls), 1)
        state = json.loads(self.config.state_file.read_text())
        self.assertEqual(state["call.txt"]["work_items"], ["ENG-1"])

    def test_transient_failures_are_retried_on_the_next_scan(self):
        self.config.settle_seconds = 0
        self.write("call.txt", "TODO: one\n")
        self.client.fail = TransientError("down")
        self.importer.scan()
        self.client.fail = None
        self.importer.scan()
        self.assertEqual(len(self.client.calls), 1)

    def test_ignores_other_files_hidden_files_and_the_state_file(self):
        self.config.settle_seconds = 0
        self.config.state_file = self.share / "state.json"
        self.importer = Importer(self.config, self.client, clock=self.clock)
        self.write("notes.docx", "TODO: no")
        self.write(".partial.txt", "TODO: no")
        self.write("ok.txt", "TODO: yes")
        self.importer.scan()
        self.importer.scan()
        self.assertEqual([[i["title"] for i in call] for call in self.client.calls], [["yes"]])

    def test_files_without_action_items_are_recorded_without_calls(self):
        self.config.settle_seconds = 0
        self.write("chat.txt", "Dana: hi\nSam: bye\n")
        self.importer.scan()
        self.assertEqual(self.client.calls, [])
        self.assertEqual(json.loads(self.config.state_file.read_text())["chat.txt"]["imported"], 0)

    def test_llm_is_used_only_when_no_markers_are_found(self):
        self.config.settle_seconds = 0

        class Extractor:
            def __init__(self):
                self.calls = 0

            def extract(self, transcript):
                self.calls += 1
                return [ActionItem("Follow up with Acme", owner="Dana")]

        extractor = Extractor()
        self.importer = Importer(self.config, self.client, extractor=extractor, clock=self.clock)
        self.write("raw.txt", "Dana: I can follow up with Acme next week.\n")
        self.write("marked.txt", "TODO: explicit\n")
        self.importer.scan()
        self.assertEqual(extractor.calls, 1)
        titles = sorted(i["title"] for call in self.client.calls for i in call)
        self.assertEqual(titles, ["Follow up with Acme", "explicit"])

    def test_owner_resolution(self):
        resolve = self.importer.resolve_owner
        self.assertEqual(resolve("Dana"), "dana@acme.com")
        self.assertEqual(resolve("@dana"), "dana@acme.com")
        self.assertEqual(resolve("Sam Lee"), "sam@acme.com")
        self.assertEqual(resolve("lee@acme.com"), "lee@acme.com")
        self.assertIsNone(resolve("Check"))
        self.assertIsNone(resolve(None))


class PlaneClientTest(unittest.TestCase):
    def test_batches_and_results(self):
        client = PlaneClient("http://plane:8000/", "key", "acme")
        self.assertEqual(client.url, "http://plane:8000/api/v1/workspaces/acme/work-items/import/")
        responses = [(207, [{"id": "a"}] * 100), (207, [{"error": "bad"}])]
        with patch("transcript_importer.client.post_json", side_effect=responses) as post:
            results = client.import_items([{"title": str(i)} for i in range(101)])
        self.assertEqual(len(results), 101)
        self.assertEqual(results[-1], {"error": "bad"})
        self.assertEqual(post.call_args_list[0].args[2], {"X-Api-Key": "key"})

    def test_rejected_api_key_is_transient(self):
        client = PlaneClient("http://plane", "bad", "acme")
        with patch("transcript_importer.client.post_json", return_value=(401, {"detail": "nope"})):
            with self.assertRaises(TransientError):
                client.import_items([{"title": "x"}])


if __name__ == "__main__":
    unittest.main()

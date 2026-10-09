# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import unittest
from pathlib import Path

from transcript_importer.parse import ActionItem, parse_transcript, split_owner

TEXT = """\
Weekly sync — Acme
[00:01:12] Dana: Thanks everyone for joining.
[00:03:40] Sam: Action item (Dana): send the revised quote to Acme by Friday
[00:05:02] Dana: TODO: update the onboarding checklist @priya
Lee: I'll think about the roadmap.
Follow-up: schedule the security review. Owner: Lee
- [ ] Book the venue for the offsite

Next steps
1. Sam to draft the SOW
2) Confirm pricing with finance (owner: dana@acme.com)
- Share the recording

Summary:
- This bullet is not an action item
"""


class ParseTextTest(unittest.TestCase):
    def setUp(self):
        self.items = parse_transcript(Path("call.txt"), TEXT)

    def test_finds_markers_checkboxes_and_sections(self):
        self.assertEqual(
            [item.text for item in self.items],
            [
                "send the revised quote to Acme by Friday",
                "update the onboarding checklist @priya",
                "schedule the security review.",
                "Book the venue for the offsite",
                "Sam to draft the SOW",
                "Confirm pricing with finance",
                "Share the recording",
            ],
        )

    def test_owners(self):
        owners = {item.text: item.owner for item in self.items}
        self.assertEqual(owners["send the revised quote to Acme by Friday"], "Dana")
        self.assertEqual(owners["update the onboarding checklist @priya"], "priya")
        self.assertEqual(owners["schedule the security review."], "Lee")
        self.assertEqual(owners["Sam to draft the SOW"], "Sam")
        self.assertEqual(owners["Confirm pricing with finance"], "dana@acme.com")
        self.assertIsNone(owners["Share the recording"])

    def test_plain_conversation_and_other_sections_are_ignored(self):
        texts = " ".join(item.text for item in self.items)
        self.assertNotIn("roadmap", texts)
        self.assertNotIn("not an action item", texts)

    def test_context_is_the_preceding_lines(self):
        first = self.items[0]
        self.assertEqual(first.line, 3)
        self.assertIn("Thanks everyone for joining.", first.context[-1])


class ParseFormatsTest(unittest.TestCase):
    def test_vtt(self):
        vtt = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\n<v Dana>Action item: renew the TLS certificate</v>\n"
        items = parse_transcript(Path("call.vtt"), vtt)
        self.assertEqual([(i.text, i.owner) for i in items], [("renew the TLS certificate", None)])

    def test_srt(self):
        srt = "1\n00:00:01,000 --> 00:00:03,000\nTODO: archive the old bucket\n\n2\n00:00:04,000 --> 00:00:05,000\nok\n"
        self.assertEqual([i.text for i in parse_transcript(Path("call.srt"), srt)], ["archive the old bucket"])

    def test_json_action_items_from_a_summarizer(self):
        data = {"action_items": ["Email the minutes", {"text": "Fix the login bug", "owner": "Priya"}, ""]}
        items = parse_transcript(Path("summary.json"), json.dumps(data))
        self.assertEqual(
            [(i.text, i.owner) for i in items], [("Email the minutes", None), ("Fix the login bug", "Priya")]
        )

    def test_json_segments(self):
        data = {"segments": [{"speaker": "Sam", "text": "Next step: ship the hotfix"}]}
        self.assertEqual([i.text for i in parse_transcript(Path("t.json"), json.dumps(data))], ["ship the hotfix"])

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_transcript(Path("bad.json"), "{not json")


class FingerprintTest(unittest.TestCase):
    def test_wording_identity_ignores_case_spacing_and_punctuation(self):
        a = ActionItem("Send the quote to Acme.")
        b = ActionItem("send  the quote to acme")
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, ActionItem("Send the invoice to Acme").fingerprint)

    def test_duplicates_in_one_file_collapse(self):
        items = parse_transcript(Path("t.txt"), "TODO: call Acme\nAction item: Call Acme.\n")
        self.assertEqual(len(items), 1)


class SplitOwnerTest(unittest.TestCase):
    def test_owner_field_is_removed_from_text(self):
        self.assertEqual(split_owner("Ship it (owner: Lee)"), ("Ship it", "Lee"))

    def test_lowercase_leading_word_is_not_an_owner(self):
        self.assertEqual(split_owner("check to see if it works"), ("check to see if it works", None))


if __name__ == "__main__":
    unittest.main()

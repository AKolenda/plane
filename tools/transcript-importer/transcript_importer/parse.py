# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Read call transcripts and pull out action items.

Recognized, case-insensitively, with or without a leading speaker or timestamp:

* marker lines: ``Action item: …``, ``AI: …``, ``TODO: …``, ``To do: …``, ``Follow up: …``,
  ``Next step: …``, ``[ ] …`` / ``- [ ] …``
* sections: a heading such as ``Action items``, ``Next steps``, ``Follow-ups`` or ``To-dos``
  followed by bullet or numbered lines, until a blank line or another heading
* JSON exports with an ``action_items`` list (strings or ``{"text", "owner"}`` objects)

Owners come from ``(Alice)`` / ``[Alice]`` after the marker, ``Owner: Alice``, ``@alice``, a
leading ``Alice to …`` / ``Alice will …``, or an email address in the text.
"""

# Python imports
import hashlib
import json
import re
from dataclasses import dataclass, field

TIMESTAMP = r"(?:\[?\(?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\)?\]?\s*)"
SPEAKER = r"(?:[A-Z][\w.'-]*(?:\s[A-Z][\w.'-]*){0,2}\s*:\s*)"
MARKER = re.compile(
    rf"^\s*{TIMESTAMP}?{SPEAKER}?(?:[-*•]\s*)?"
    r"(?:action\s*items?|ai|todo|to\s*do|follow[\s-]*ups?|next\s*steps?)"
    r"\s*(?:\((?P<owner_paren>[^)]+)\)|\[(?P<owner_bracket>[^\]]+)\])?\s*[:\-–—]\s*(?P<text>.+)$",
    re.IGNORECASE,
)
CHECKBOX = re.compile(rf"^\s*{TIMESTAMP}?(?:[-*•]\s*)?\[\s?\]\s+(?P<text>.+)$")
SECTION = re.compile(
    r"^\s*(?:#+\s*)?(?:action\s*items?|next\s*steps?|follow[\s-]*ups?|to[\s-]*dos?|tasks)\s*:?\s*$",
    re.IGNORECASE,
)
HEADING = re.compile(r"^\s*(?:#+\s+\S.*|[A-Z][A-Za-z ]{2,40}:)\s*$")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?:\[\s?\]\s+)?(?P<text>.+)$")
OWNER_FIELD = re.compile(r"[\(\[]?\s*owner\s*[:=]\s*(?P<owner>[^)\],;]+)[\)\]]?", re.IGNORECASE)
MENTION = re.compile(r"(?<![\w.])@(?P<owner>[A-Za-z][\w.-]*)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LEADING_OWNER = re.compile(r"^(?P<owner>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:to|will|should)\s+(?P<rest>.+)$")
VTT_CUE_TIME = re.compile(r"^\s*\d{2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->\s*")
VTT_VOICE = re.compile(r"<v\s+([^>]+)>")
TAG = re.compile(r"<[^>]+>")


@dataclass
class ActionItem:
    text: str
    owner: str | None = None
    line: int | None = None
    context: list[str] = field(default_factory=list)

    @property
    def fingerprint(self):
        """Stable id for the item's wording: case, spacing and punctuation do not matter."""
        normalized = re.sub(r"[^\w]+", " ", self.text.lower()).strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# Reading -----------------------------------------------------------------------------------


def transcript_lines(path, raw):
    """Plain text lines for any supported format (cue numbers and timings removed)."""
    suffix = path.suffix.lower()
    if suffix in (".vtt", ".srt"):
        lines = []
        for line in raw.splitlines():
            if not line.strip() or line.strip() == "WEBVTT" or line.strip().isdigit() or VTT_CUE_TIME.match(line):
                continue
            voice = VTT_VOICE.search(line)
            text = TAG.sub("", line).strip()
            lines.append(f"{voice.group(1).strip()}: {text}" if voice else text)
        return lines
    if suffix == ".json":
        data = json.loads(raw)
        if isinstance(data, dict):
            segments = data.get("segments") or data.get("transcript") or data.get("utterances") or []
        else:
            segments = data
        if isinstance(segments, str):
            return segments.splitlines()
        lines = []
        for segment in segments:
            if isinstance(segment, dict):
                speaker = segment.get("speaker") or segment.get("name")
                text = segment.get("text") or ""
                lines.append(f"{speaker}: {text}" if speaker else text)
            elif isinstance(segment, str):
                lines.append(segment)
        return lines
    return raw.splitlines()


def json_action_items(raw):
    """Action items a summarizer already extracted (`{"action_items": [...]}`), or None."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("action_items"), list):
        return None
    items = []
    for entry in data["action_items"]:
        if isinstance(entry, str) and entry.strip():
            items.append(ActionItem(text=clean_text(entry)))
        elif isinstance(entry, dict) and str(entry.get("text") or entry.get("title") or "").strip():
            owner = entry.get("owner") or entry.get("assignee")
            items.append(ActionItem(text=clean_text(entry.get("text") or entry.get("title")), owner=owner))
    return items


# Extraction --------------------------------------------------------------------------------


def clean_text(text):
    return re.sub(r"\s+", " ", str(text)).strip(" \t-–—:;")


def split_owner(text, owner=None):
    """Pull an owner out of the item text; returns `(text, owner)`."""
    match = OWNER_FIELD.search(text)
    if match:
        owner = owner or match.group("owner").strip()
        text = (text[: match.start()] + text[match.end() :]).strip()
    match = EMAIL.search(text)
    if match and not owner:
        owner = match.group(0)
    match = MENTION.search(text)
    if match and not owner:
        owner = match.group("owner")
    match = LEADING_OWNER.match(text)
    if match and not owner:
        owner = match.group("owner")
    return clean_text(text), (owner.strip() if owner else None)


def extract_action_items(lines):
    items, seen = [], set()
    in_section = False

    def add(text, line_number, owner=None):
        text, owner = split_owner(text, owner)
        if len(text) < 3:
            return
        item = ActionItem(text=text, owner=owner, line=line_number)
        if item.fingerprint in seen:
            return
        seen.add(item.fingerprint)
        start = max(0, line_number - 3)
        item.context = [line.strip() for line in lines[start : line_number - 1] if line.strip()][-2:]
        items.append(item)

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            in_section = False
            continue
        if SECTION.match(line):
            in_section = True
            continue
        match = MARKER.match(line)
        if match:
            add(match.group("text"), number, match.group("owner_paren") or match.group("owner_bracket"))
            continue
        match = CHECKBOX.match(line)
        if match:
            add(match.group("text"), number)
            continue
        if in_section:
            match = BULLET.match(line)
            if match:
                add(match.group("text"), number)
            elif HEADING.match(line):
                in_section = False
    return items


def parse_transcript(path, raw):
    """All action items in one transcript file."""
    if path.suffix.lower() == ".json":
        items = json_action_items(raw)
        if items is not None:
            return items
    return extract_action_items(transcript_lines(path, raw))

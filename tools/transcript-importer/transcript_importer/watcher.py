# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Poll a folder for transcripts and import their action items into Plane.

Polling (not inotify) because network shares such as SMB/NFS mounts from a NAS do not
deliver file-system events reliably. A file is read once it has stopped changing for
`settle_seconds`, and again whenever its content changes. Every action item is imported
with `external_source="transcript"` and an external id built from the file path and the
item's wording, so re-processing a transcript updates its work items instead of
duplicating them.
"""

# Python imports
import fnmatch
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .client import TransientError
from .parse import parse_transcript, transcript_lines

log = logging.getLogger("transcript_importer")

EXTERNAL_SOURCE = "transcript"


@dataclass
class Config:
    directory: Path
    project: str
    state_file: Path
    patterns: list[str] = field(default_factory=lambda: ["*.txt", "*.md", "*.vtt", "*.srt", "*.json"])
    labels: list[str] = field(default_factory=lambda: ["transcript"])
    assignees: dict[str, str] = field(default_factory=dict)
    settle_seconds: float = 10.0
    source_url_base: str | None = None
    max_file_bytes: int = 5 * 1024 * 1024


def parse_assignee_map(value):
    """`alice=alice@acme.com,Bob Smith=bob@acme.com` or a JSON object -> lower-cased name map."""
    if not value:
        return {}
    value = value.strip()
    pairs = (
        json.loads(value).items() if value.startswith("{") else (p.split("=", 1) for p in value.split(",") if "=" in p)
    )
    return {name.strip().lower(): email.strip() for name, email in pairs if name.strip() and email.strip()}


class State:
    """Remembers the content hash imported for each file, in a small JSON file."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.files = json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            self.files = {}

    def digest(self, relative):
        return (self.files.get(relative) or {}).get("sha256")

    def record(self, relative, digest, summary):
        self.files[relative] = {"sha256": digest, **summary}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.files, indent=2, sort_keys=True))
        os.replace(tmp, self.path)


class Importer:
    def __init__(self, config, client, extractor=None, clock=time.time):
        self.config = config
        self.client = client
        self.extractor = extractor
        self.clock = clock
        self.state = State(config.state_file)
        self._seen = {}  # path -> (size, mtime, first seen unchanged at)

    # Discovery ---------------------------------------------------------------------------

    def candidates(self):
        for path in sorted(self.config.directory.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.resolve() == self.config.state_file.resolve():
                continue
            if any(fnmatch.fnmatch(path.name.lower(), pattern.lower()) for pattern in self.config.patterns):
                yield path

    def is_settled(self, path):
        """True once size and mtime have not changed for `settle_seconds` (the writer is done)."""
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime)
        previous = self._seen.get(path)
        now = self.clock()
        if previous is None or previous[:2] != signature:
            self._seen[path] = (*signature, now)
            return self.config.settle_seconds <= 0
        return now - previous[2] >= self.config.settle_seconds

    # Processing --------------------------------------------------------------------------

    def build_items(self, path, relative, items):
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        source_url = f"{self.config.source_url_base.rstrip('/')}/{relative}" if self.config.source_url_base else None
        payloads = []
        for item in items:
            description = [item.text, "", f"From call transcript {relative} ({modified})."]
            if item.context:
                description += ["", "Context:", *[f"- {line}" for line in item.context]]
            payload = {
                "project": self.config.project,
                "external_source": EXTERNAL_SOURCE,
                "external_id": f"{relative}#{item.fingerprint}"[:255],
                "title": item.text if len(item.text) <= 255 else item.text[:252] + "...",
                "description": "\n".join(description),
                "labels": self.config.labels,
            }
            if source_url:
                payload["source_url"] = source_url
            assignee = self.resolve_owner(item.owner)
            if assignee:
                payload["assignee"] = assignee
            payloads.append(payload)
        return payloads

    def resolve_owner(self, owner):
        if not owner:
            return None
        if "@" in owner and "." in owner.split("@")[-1]:
            return owner
        owner = owner.strip().lstrip("@").lower()
        return self.config.assignees.get(owner) or self.config.assignees.get(owner.split()[0])

    def process(self, path):
        """Import one file. Returns the number of work items created or updated."""
        relative = path.relative_to(self.config.directory).as_posix()
        if path.stat().st_size > self.config.max_file_bytes:
            log.warning("Skipping %s: larger than %d bytes", relative, self.config.max_file_bytes)
            return 0
        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if self.state.digest(relative) == digest:
            return 0
        raw = raw_bytes.decode("utf-8-sig", errors="replace")

        try:
            items = parse_transcript(path, raw)
        except ValueError as e:
            log.error("Could not read %s: %s", relative, e)
            self.state.record(relative, digest, {"error": str(e), "imported": 0})
            return 0
        if not items and self.extractor is not None:
            items = self.extractor.extract("\n".join(transcript_lines(path, raw)))

        results = self.client.import_items(self.build_items(path, relative, items)) if items else []
        imported = [result for result in results if "error" not in result]
        for item, result in zip(items, results):
            if "error" in result:
                log.error("%s: %r was rejected: %s", relative, item.text, result["error"])
            else:
                log.info(
                    "%s: %s %s %s",
                    relative,
                    "created" if result["created"] else "updated",
                    result["identifier"],
                    result["url"],
                )
        self.state.record(
            relative,
            digest,
            {
                "imported": len(imported),
                "rejected": len(results) - len(imported),
                "work_items": [result["identifier"] for result in imported],
                "processed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return len(imported)

    def scan(self):
        """One pass over the folder. Transient failures leave the file for the next pass."""
        total = 0
        for path in self.candidates():
            try:
                if self.is_settled(path):
                    total += self.process(path)
            except TransientError as e:
                log.warning("Will retry %s: %s", path.name, e)
            except OSError as e:
                log.warning("Could not read %s: %s", path.name, e)
        return total

    def run_forever(self, poll_seconds):
        log.info("Watching %s every %ss", self.config.directory, poll_seconds)
        while True:
            self.scan()
            time.sleep(poll_seconds)

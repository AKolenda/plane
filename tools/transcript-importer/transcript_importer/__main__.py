# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""`python -m transcript_importer watch|once|preview <file>` — configuration comes from the environment."""

# Python imports
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .client import LLMExtractor, PlaneClient
from .parse import parse_transcript
from .watcher import Config, Importer, parse_assignee_map


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"{name} is required")
    return value


def build_importer():
    directory = Path(env("TRANSCRIPT_DIR", required=True))
    config = Config(
        directory=directory,
        project=env("PLANE_PROJECT", required=True),
        state_file=Path(env("TRANSCRIPT_STATE_FILE", "/data/transcript-importer-state.json")),
        patterns=[
            p.strip() for p in env("TRANSCRIPT_PATTERNS", "*.txt,*.md,*.vtt,*.srt,*.json").split(",") if p.strip()
        ],
        labels=[label.strip() for label in env("TRANSCRIPT_LABELS", "transcript").split(",") if label.strip()],
        assignees=parse_assignee_map(env("TRANSCRIPT_ASSIGNEES", "")),
        settle_seconds=float(env("TRANSCRIPT_SETTLE_SECONDS", "10")),
        source_url_base=env("TRANSCRIPT_SOURCE_URL_BASE") or None,
    )
    client = PlaneClient(
        env("PLANE_BASE_URL", required=True),
        env("PLANE_API_KEY", required=True),
        env("PLANE_WORKSPACE_SLUG", required=True),
    )
    extractor = None
    if env("TRANSCRIPT_LLM_BASE_URL"):
        extractor = LLMExtractor(
            env("TRANSCRIPT_LLM_BASE_URL"), env("TRANSCRIPT_LLM_MODEL", "llama3.1"), env("TRANSCRIPT_LLM_API_KEY")
        )
    return Importer(config, client, extractor)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="transcript_importer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("watch", help="poll TRANSCRIPT_DIR forever")
    sub.add_parser("once", help="scan TRANSCRIPT_DIR once and exit")
    preview = sub.add_parser("preview", help="print the action items found in a file without importing")
    preview.add_argument("file", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "preview":
        items = parse_transcript(args.file, args.file.read_text(encoding="utf-8-sig", errors="replace"))
        print(json.dumps([{"text": i.text, "owner": i.owner, "line": i.line} for i in items], indent=2))
        return 0

    importer = build_importer()
    if args.command == "once":
        importer.config.settle_seconds = 0
        importer.scan()
        return 0
    importer.run_forever(float(env("TRANSCRIPT_POLL_SECONDS", "30")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

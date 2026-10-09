# Transcript importer

Watches a folder (for example a TrueNAS SMB/NFS share) for call transcripts, extracts their action items, and imports each one into Plane through `POST /api/v1/workspaces/<slug>/work-items/import/` with `external_source="transcript"`.

- Standard library only (Python 3.12+); no Plane code is imported.
- Polls the folder, because network shares do not deliver file-system events reliably. A file is processed once it has stopped changing for `TRANSCRIPT_SETTLE_SECONDS`, and again when its content changes.
- Each action item's `external_id` is `<path relative to TRANSCRIPT_DIR>#<hash of its wording>`. Re-processing an edited transcript updates the work items whose wording is unchanged and creates new ones for new items. Rewording an item creates a new work item; the old one stays.
- What has been imported is recorded in `TRANSCRIPT_STATE_FILE`. Keep it on a writable volume, not on a read-only share.

## What counts as an action item

Matched case-insensitively, with or without a leading timestamp or `Speaker:`:

| Form         | Example                                                                                                                                        |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Marker line  | `Action item: …`, `AI: …`, `TODO: …`, `To do: …`, `Follow up: …`, `Next step: …`                                                               |
| Checkbox     | `[ ] …`, `- [ ] …`                                                                                                                             |
| Section      | A heading `Action items`, `Next steps`, `Follow-ups`, `To-dos` or `Tasks`, then bullet or numbered lines until a blank line or another heading |
| JSON summary | `{"action_items": ["…", {"text": "…", "owner": "…"}]}`                                                                                         |

Supported files: `.txt`, `.md`, `.vtt`, `.srt`, and `.json` (an `action_items` summary, or `segments` / `utterances` / `transcript` with `speaker` and `text`).

Owners come from `Action item (Dana): …`, `[Dana]`, `Owner: Dana`, `@dana`, `Dana to …` / `Dana will …`, or an email address in the text. Names are mapped to Plane users with `TRANSCRIPT_ASSIGNEES`; unmapped names are ignored, and the owner must be a member of the project.

When `TRANSCRIPT_LLM_BASE_URL` is set, transcripts with none of the markers above are sent to an OpenAI-compatible chat completions API (OpenAI, Ollama, LM Studio, vLLM) to extract action items.

## Configuration

| Variable                     | Default                                | Description                                                                                            |
| ---------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `PLANE_BASE_URL`             | required                               | Plane URL that serves `/api/v1/`, e.g. `http://api:8000` inside Compose or `https://plane.example.com` |
| `PLANE_API_KEY`              | required                               | API token (Profile settings → Personal access tokens) of a user who is a member of the project         |
| `PLANE_WORKSPACE_SLUG`       | required                               | Workspace slug                                                                                         |
| `PLANE_PROJECT`              | required                               | Project identifier (`ENG`) or id that receives the work items                                          |
| `TRANSCRIPT_DIR`             | `/transcripts` in the image            | Folder to watch, searched recursively                                                                  |
| `TRANSCRIPT_STATE_FILE`      | `/data/transcript-importer-state.json` | Where processed files are recorded                                                                     |
| `TRANSCRIPT_PATTERNS`        | `*.txt,*.md,*.vtt,*.srt,*.json`        | File name patterns                                                                                     |
| `TRANSCRIPT_LABELS`          | `transcript`                           | Comma-separated labels added to every work item (created if missing)                                   |
| `TRANSCRIPT_ASSIGNEES`       | empty                                  | `dana=dana@acme.com,Sam Lee=sam@acme.com` or a JSON object                                             |
| `TRANSCRIPT_SOURCE_URL_BASE` | empty                                  | When set, each work item links to `<base>/<relative path>`                                             |
| `TRANSCRIPT_SETTLE_SECONDS`  | `10`                                   | How long a file must stay unchanged before it is read                                                  |
| `TRANSCRIPT_POLL_SECONDS`    | `30`                                   | Pause between scans                                                                                    |
| `TRANSCRIPT_LLM_BASE_URL`    | empty                                  | e.g. `http://ollama:11434/v1` or `https://api.openai.com/v1`                                           |
| `TRANSCRIPT_LLM_MODEL`       | `llama3.1`                             | Model name                                                                                             |
| `TRANSCRIPT_LLM_API_KEY`     | empty                                  | Bearer token for the LLM API                                                                           |
| `LOG_LEVEL`                  | `INFO`                                 | Python log level                                                                                       |

## Run

```bash
# See what would be imported from one file
python -m transcript_importer preview ./call.txt

# One pass over the folder (no settle delay), then exit
python -m transcript_importer once

# Watch forever (the container default)
python -m transcript_importer watch
```

The NovaPro Compose file (`deployments/novapro/`) runs it as the `transcript-importer` service.

## Tests

```bash
cd tools/transcript-importer
python -m unittest discover -s tests -t .
```

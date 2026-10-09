# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Minimal HTTP clients (standard library only) for Plane's import endpoint and an optional LLM."""

# Python imports
import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("transcript_importer")

RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


class TransientError(Exception):
    """The request may succeed later (network failure, rate limit, server error)."""


def post_json(url, body, headers, timeout=30, attempts=4, backoff=2.0):
    """POST JSON and return `(status, decoded body)`; retries transient failures with backoff."""
    data = json.dumps(body).encode()
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url, data=data, method="POST", headers={"Content-Type": "application/json", **headers}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as e:
            payload = e.read()
            if e.code not in RETRY_STATUSES:
                try:
                    return e.code, json.loads(payload or b"null")
                except ValueError:
                    return e.code, {"error": payload.decode(errors="replace")[:500]}
            reason = f"HTTP {e.code}"
            retry_after = e.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else backoff**attempt
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            reason = str(e)
            delay = backoff**attempt
        if attempt == attempts:
            raise TransientError(f"POST {url} failed after {attempts} attempts: {reason}")
        log.warning("POST %s failed (%s); retrying in %.0fs", url, reason, delay)
        time.sleep(delay)
    raise AssertionError("unreachable")


class PlaneClient:
    BATCH_SIZE = 100

    def __init__(self, base_url, api_key, workspace_slug):
        self.url = f"{base_url.rstrip('/')}/api/v1/workspaces/{workspace_slug}/work-items/import/"
        self.headers = {"X-Api-Key": api_key}

    def import_items(self, items):
        """Send items in batches; returns one result per item (`{"error": ...}` for rejected ones)."""
        results = []
        for start in range(0, len(items), self.BATCH_SIZE):
            batch = items[start : start + self.BATCH_SIZE]
            status, body = post_json(self.url, batch, self.headers)
            if status == 207 and isinstance(body, list):
                results.extend(body)
            elif status in (401, 403):
                raise TransientError(f"Plane rejected the API key (HTTP {status}): {body}")
            else:
                results.extend({"error": f"HTTP {status}: {body}"} for _ in batch)
        return results


class LLMExtractor:
    """Ask an OpenAI-compatible chat completions API (OpenAI, Ollama, LM Studio, ...) for action items."""

    PROMPT = (
        "Extract the action items from this call transcript. Reply with only a JSON object "
        '{"action_items": [{"text": "...", "owner": "name or null"}]}. Each text is one '
        "concrete task, written as an imperative sentence. Return an empty list if there are none."
    )
    MAX_CHARS = 60000

    def __init__(self, base_url, model, api_key=None):
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def extract(self, transcript):
        from .parse import ActionItem, clean_text

        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self.PROMPT},
                {"role": "user", "content": transcript[: self.MAX_CHARS]},
            ],
        }
        status, response = post_json(self.url, body, self.headers, timeout=120)
        if status != 200:
            raise TransientError(f"LLM request failed (HTTP {status}): {response}")
        content = response["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        data = json.loads(content[start : end + 1]) if start >= 0 else {}
        items = []
        for entry in data.get("action_items") or []:
            text = entry.get("text") if isinstance(entry, dict) else entry
            if text and str(text).strip():
                owner = entry.get("owner") if isinstance(entry, dict) else None
                items.append(ActionItem(text=clean_text(text), owner=owner or None))
        return items

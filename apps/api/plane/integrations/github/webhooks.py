# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import hashlib
import hmac
import logging

# Module imports
from plane.db.models import GithubConnection, GithubWatchedRepository

from .issue_sync import process_issues_event
from .pull_requests import process_pull_request_event

logger = logging.getLogger("plane.worker")

SIGNATURE_PREFIX = "sha256="


def compute_signature(secret, body):
    return SIGNATURE_PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret, body, signature_header):
    """Check GitHub's `X-Hub-Signature-256` header against the shared webhook secret."""
    if not secret or not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        return False
    return hmac.compare_digest(compute_signature(secret, body), signature_header)


def handle_event(connection, event_name, payload):
    """Route one verified delivery for `connection`. Returns a short summary for logging."""
    if event_name == "installation" and payload.get("action") == "deleted":
        # The app was uninstalled on GitHub; drop the connection and everything it watched
        connection.delete(soft=False)
        return "connection removed"

    if event_name == "installation_repositories":
        removed_ids = [repository["id"] for repository in payload.get("repositories_removed") or []]
        if removed_ids:
            GithubWatchedRepository.objects.filter(connection=connection, repository_id__in=removed_ids).delete(
                soft=False
            )
        return f"removed {len(removed_ids)} repositories"

    repository_id = (payload.get("repository") or {}).get("id")
    if not repository_id:
        return "ignored"
    repository = (
        GithubWatchedRepository.objects.filter(connection=connection, repository_id=repository_id)
        .select_related("connection", "project", "open_state", "closed_state")
        .first()
    )
    if repository is None:
        return "repository not watched"

    if event_name in ("pull_request", "pull_request_review"):
        return process_pull_request_event(repository, event_name, payload)
    if event_name == "issues":
        return process_issues_event(repository, payload)
    return "ignored"


def process_delivery(connection_id, event_name, payload):
    connection = GithubConnection.objects.filter(pk=connection_id).first()
    if connection is None:
        return "connection not found"
    return handle_event(connection, event_name, payload)

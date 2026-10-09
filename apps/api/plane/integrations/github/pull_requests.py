# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Process `pull_request` and `pull_request_review` deliveries for a watched repository."""

# Django imports
from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime

# Module imports
from plane.db.models import GithubPullRequest

from .bot import get_github_bot_user
from .linking import parse_work_item_references, resolve_work_items, sync_pull_request_links
from .status import (
    apply_state,
    classify_pull_request_event,
    current_pull_request_event,
    pull_request_display_state,
    resolve_target_state,
)


def _pull_request_fields(payload):
    return {
        "github_id": payload["id"],
        "title": (payload.get("title") or "")[:1024],
        "html_url": payload.get("html_url") or "",
        "state": pull_request_display_state(payload),
        "base_branch": (payload.get("base") or {}).get("ref") or "",
        "head_branch": (payload.get("head") or {}).get("ref") or "",
        "author_login": (payload.get("user") or {}).get("login") or "",
        "opened_at": parse_datetime(payload["created_at"]) if payload.get("created_at") else None,
        "merged_at": parse_datetime(payload["merged_at"]) if payload.get("merged_at") else None,
        "closed_at": parse_datetime(payload["closed_at"]) if payload.get("closed_at") else None,
    }


def _get_or_create_pull_request(repository, number):
    try:
        with transaction.atomic():
            pull_request, _ = GithubPullRequest.objects.get_or_create(
                repository=repository,
                number=number,
                defaults={"workspace_id": repository.workspace_id, "github_id": 0, "title": "", "html_url": ""},
            )
            return pull_request
    except IntegrityError:
        # A concurrent delivery for the same pull request created it
        return GithubPullRequest.objects.get(repository=repository, number=number)


def process_pull_request_event(repository, event_name, payload):
    """Upsert the pull request, re-link work items from its title and description, and apply state mappings.

    Returns a summary dict, mainly for logging and tests.
    """
    pr_payload = payload.get("pull_request") or {}
    if not pr_payload.get("number"):
        return {"ignored": "missing pull request"}

    event = classify_pull_request_event(event_name, payload)
    updated_at = parse_datetime(pr_payload["updated_at"]) if pr_payload.get("updated_at") else None
    pull_request = _get_or_create_pull_request(repository, pr_payload["number"])

    with transaction.atomic():
        pull_request = GithubPullRequest.objects.select_for_update().get(pk=pull_request.pk)
        # Deliveries can arrive out of order; an older snapshot must not undo a newer one
        if pull_request.github_updated_at and updated_at and updated_at < pull_request.github_updated_at:
            return {"ignored": "stale delivery", "pull_request": pull_request.id}

        for field, value in _pull_request_fields(pr_payload).items():
            setattr(pull_request, field, value)
        pull_request.github_updated_at = updated_at or pull_request.github_updated_at
        if event:
            pull_request.last_event = event
        pull_request.save()

        references = parse_work_item_references(pr_payload.get("title"), pr_payload.get("body"))
        work_items = resolve_work_items(repository.workspace_id, references)
        added, kept = sync_pull_request_links(pull_request, work_items)

        if event:
            targets = [(work_item, event) for work_item in added + kept]
        else:
            # Linked by an edit: bring the work item to where the pull request already is
            targets = [(work_item, current_pull_request_event(pr_payload)) for work_item in added]

        moved = []
        if targets:
            actor = get_github_bot_user(repository.workspace_id)
            base_branch = pull_request.base_branch
            for work_item, target_event in targets:
                state = resolve_target_state(work_item.project_id, target_event, base_branch)
                if apply_state(work_item, state, actor):
                    moved.append(work_item.id)

    return {
        "pull_request": pull_request.id,
        "event": event,
        "linked": [work_item.id for work_item in work_items],
        "added": [work_item.id for work_item in added],
        "moved": moved,
    }

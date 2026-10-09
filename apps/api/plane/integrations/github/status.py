# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Translate pull request webhooks into events and move linked work items between states."""

# Python imports
import json
from fnmatch import fnmatchcase

# Django imports
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

# Module imports
from plane.db.models import GithubPullRequestEvent, GithubPullRequestState, GithubStateMapping

Event = GithubPullRequestEvent


def classify_pull_request_event(event_name, payload):
    """Return the `GithubPullRequestEvent` a webhook delivery represents, or None.

    `event_name` is the `X-GitHub-Event` header. Edits, label changes, pushes and other
    deliveries that do not change the review lifecycle return None.
    """
    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}

    if event_name == "pull_request_review":
        review = payload.get("review") or {}
        if action == "submitted" and (review.get("state") or "").lower() == "approved":
            return Event.APPROVED
        return None

    if event_name != "pull_request":
        return None

    if action in ("opened", "reopened"):
        return Event.DRAFTED if pull_request.get("draft") else Event.OPENED
    if action == "converted_to_draft":
        return Event.DRAFTED
    if action == "ready_for_review":
        return Event.READY_FOR_REVIEW
    if action == "review_requested":
        return Event.REVIEW_REQUESTED
    if action == "closed":
        return Event.MERGED if pull_request.get("merged") else Event.CLOSED
    return None


def current_pull_request_event(pull_request_payload):
    """The event that describes where a pull request is now, used when a work item is linked late."""
    if pull_request_payload.get("merged"):
        return Event.MERGED
    if pull_request_payload.get("state") == "closed":
        return Event.CLOSED
    if pull_request_payload.get("draft"):
        return Event.DRAFTED
    return Event.OPENED


def pull_request_display_state(pull_request_payload):
    if pull_request_payload.get("merged") or pull_request_payload.get("merged_at"):
        return GithubPullRequestState.MERGED
    if pull_request_payload.get("state") == "closed":
        return GithubPullRequestState.CLOSED
    if pull_request_payload.get("draft"):
        return GithubPullRequestState.DRAFT
    return GithubPullRequestState.OPEN


def branch_matches(pattern, branch):
    """An empty pattern matches every branch; otherwise an exact name or a glob such as `release/*`."""
    if not pattern:
        return True
    return pattern == branch or fnmatchcase(branch or "", pattern)


def select_state_mapping(mappings, event, base_branch):
    """Pick the mapping for `event` on `base_branch`.

    A branch-specific mapping beats the catch-all (empty branch) mapping, an exact branch
    name beats a glob, and among globs the longest (most specific) pattern wins.
    """
    candidates = [m for m in mappings if m.event == event and branch_matches(m.base_branch, base_branch)]
    if not candidates:
        return None

    def specificity(mapping):
        if not mapping.base_branch:
            return (0, 0)
        if mapping.base_branch == base_branch:
            return (2, len(mapping.base_branch))
        return (1, len(mapping.base_branch))

    return max(candidates, key=specificity)


def resolve_target_state(project_id, event, base_branch):
    """Return the state a work item in `project_id` should move to, or None when nothing is mapped."""
    if not event:
        return None
    mappings = list(GithubStateMapping.objects.filter(project_id=project_id, event=event).select_related("state"))
    mapping = select_state_mapping(mappings, event, base_branch)
    if mapping is None or mapping.state.deleted_at is not None:
        return None
    return mapping.state


def apply_state(work_item, state, actor):
    """Move `work_item` to `state` as `actor` and record the change in its activity. Returns True if it moved."""
    from plane.bgtasks.issue_activities_task import issue_activity

    if state is None or work_item.state_id == state.id or state.project_id != work_item.project_id:
        return False

    current_instance = json.dumps({"state_id": str(work_item.state_id) if work_item.state_id else None})
    work_item.state = state
    work_item.updated_by = actor
    work_item.save(update_fields=["state", "updated_by", "updated_at"])

    issue_activity.delay(
        type="issue.activity.updated",
        requested_data=json.dumps({"state_id": str(state.id)}, cls=DjangoJSONEncoder),
        actor_id=str(actor.id),
        issue_id=str(work_item.id),
        project_id=str(work_item.project_id),
        current_instance=current_instance,
        epoch=int(timezone.now().timestamp()),
        notification=True,
        origin=settings.APP_BASE_URL or settings.WEB_URL,
    )
    return True

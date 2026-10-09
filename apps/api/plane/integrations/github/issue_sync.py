# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Label-driven issue sync between a watched repository and its Plane project.

* GitHub to Plane: a GitHub issue labelled with the repository's `github_label` becomes a
  work item. Later title, description and open/closed changes on GitHub update it.
* Plane to GitHub (bidirectional only): a work item labelled with `plane_label` becomes a
  GitHub issue, and later name, description and state-group changes update it.

Each pair keeps a snapshot of both sides, so only fields that changed are written and the
webhook or activity echo of the integration's own write is a no-op.
"""

# Python imports
import json
import logging

# Third party imports
import nh3

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone

# Module imports
from plane.db.models import (
    GithubIssueSyncMode,
    GithubSyncedIssue,
    GithubWatchedRepository,
    Issue,
    IssueLink,
    State,
)
from plane.db.models.state import StateGroup
from plane.utils.content_validator import validate_html_content

from . import client as github_client
from .bot import get_github_bot_user

logger = logging.getLogger("plane.worker")

CLOSED_STATE_GROUPS = (StateGroup.COMPLETED.value, StateGroup.CANCELLED.value)
EXPORT_TAGS = {
    "a", "b", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "i", "img", "li", "ol", "p", "pre", "s", "strong", "table", "tbody", "td", "th", "thead", "tr", "ul",
}  # fmt: skip
EXPORT_ATTRIBUTES = {"a": {"href"}, "img": {"src", "alt"}}


# Snapshots ---------------------------------------------------------------------------------


def github_snapshot(github_issue):
    return {
        "title": github_issue.get("title") or "",
        "body": github_issue.get("body") or "",
        "state": github_issue.get("state") or "open",
    }


def plane_snapshot(work_item):
    return {
        "name": work_item.name,
        "description_html": work_item.description_html or "",
        "closed": bool(work_item.state and work_item.state.group in CLOSED_STATE_GROUPS),
    }


def changed_fields(previous, current):
    return {key for key, value in current.items() if previous.get(key) != value}


def has_label(github_issue, label_name):
    wanted = (label_name or "").strip().lower()
    return bool(wanted) and any(
        (label.get("name") or "").lower() == wanted for label in github_issue.get("labels") or []
    )


def work_item_has_label(work_item, label_name):
    wanted = (label_name or "").strip()
    return bool(wanted) and work_item.labels.filter(name__iexact=wanted, deleted_at__isnull=True).exists()


# Conversions -------------------------------------------------------------------------------


def github_body_to_html(repository, body):
    """Render the GitHub markdown body the way GitHub does, then sanitize it for Plane's editor."""
    if not body:
        return "<p></p>"
    try:
        html = github_client.render_markdown(repository.connection, repository.full_name, body)
    except Exception as e:
        logger.warning(f"GitHub markdown render failed for {repository.full_name}: {e}")
        html = "".join(f"<p>{nh3.clean_text(paragraph)}</p>" for paragraph in body.split("\n\n"))
    is_valid, _, clean_html = validate_html_content(html)
    return clean_html if is_valid and clean_html else "<p></p>"


def plane_html_to_github_body(description_html):
    """GitHub renders HTML inside issue bodies; strip Plane editor markup down to portable tags."""
    if not description_html or description_html.strip() in ("<p></p>", ""):
        return ""
    return nh3.clean(description_html, tags=EXPORT_TAGS, attributes=EXPORT_ATTRIBUTES).strip()


# States ------------------------------------------------------------------------------------


def open_state_for(repository):
    if repository.open_state_id and repository.open_state.deleted_at is None:
        return repository.open_state
    states = State.objects.filter(project_id=repository.project_id)
    return states.filter(default=True).first() or states.filter(group=StateGroup.UNSTARTED.value).first()


def closed_state_for(repository):
    if repository.closed_state_id and repository.closed_state.deleted_at is None:
        return repository.closed_state
    return State.objects.filter(project_id=repository.project_id, group=StateGroup.COMPLETED.value).first()


# Activity ----------------------------------------------------------------------------------


def _record_activity(activity_type, work_item, actor, requested_data, current_instance):
    """Write the work item's activity and notify outbound webhooks, as a web edit would."""
    from plane.bgtasks.issue_activities_task import issue_activity
    from plane.bgtasks.webhook_task import model_activity

    issue_activity.delay(
        type=activity_type,
        requested_data=json.dumps(requested_data, cls=DjangoJSONEncoder),
        actor_id=str(actor.id),
        issue_id=str(work_item.id),
        project_id=str(work_item.project_id),
        current_instance=json.dumps(current_instance, cls=DjangoJSONEncoder) if current_instance else None,
        epoch=int(timezone.now().timestamp()),
        notification=True,
    )
    model_activity.delay(
        model_name="issue",
        model_id=str(work_item.id),
        requested_data=json.loads(json.dumps(requested_data, cls=DjangoJSONEncoder)),
        current_instance=json.dumps(current_instance, cls=DjangoJSONEncoder) if current_instance else None,
        actor_id=str(actor.id),
        slug=work_item.workspace.slug,
    )


# GitHub -> Plane ---------------------------------------------------------------------------


def process_issues_event(repository, payload):
    """Handle an `issues` delivery. Returns a short status string for logging and tests."""
    if repository.issue_sync_mode == GithubIssueSyncMode.DISABLED or not repository.project_id:
        return "sync disabled"
    github_issue = payload.get("issue") or {}
    if not github_issue.get("number") or github_issue.get("pull_request"):
        return "ignored"

    action = payload.get("action")
    synced = (
        GithubSyncedIssue.objects.filter(repository=repository, github_issue_number=github_issue["number"])
        .select_related("issue", "issue__state")
        .first()
    )

    if synced is None:
        if action in ("opened", "labeled", "edited", "reopened") and has_label(github_issue, repository.github_label):
            import_github_issue(repository, github_issue)
            return "imported"
        return "ignored"

    if action == "deleted":
        synced.delete(soft=False)
        return "unlinked"
    return "updated" if apply_github_changes(synced, github_issue) else "unchanged"


def import_github_issue(repository, github_issue):
    """Create a work item from a GitHub issue and remember the pair."""
    actor = get_github_bot_user(repository.workspace_id)
    is_closed = github_issue.get("state") == "closed"
    state = closed_state_for(repository) if is_closed else open_state_for(repository)

    try:
        with transaction.atomic():
            work_item = Issue.objects.create(
                project_id=repository.project_id,
                name=(github_issue.get("title") or "Untitled")[:255],
                description_html=github_body_to_html(repository, github_issue.get("body")),
                state=state,
                external_source="github",
                external_id=str(github_issue["id"]),
                created_by=actor,
                updated_by=actor,
            )
            IssueLink.objects.create(
                issue=work_item,
                project_id=repository.project_id,
                url=github_issue["html_url"],
                title=f"{repository.full_name}#{github_issue['number']}",
                created_by=actor,
            )
            synced = GithubSyncedIssue.objects.create(
                repository=repository,
                issue=work_item,
                project_id=repository.project_id,
                github_issue_id=github_issue["id"],
                github_issue_number=github_issue["number"],
                html_url=github_issue["html_url"],
                github_snapshot=github_snapshot(github_issue),
                plane_snapshot=plane_snapshot(work_item),
                last_synced_at=timezone.now(),
            )
    except IntegrityError:
        # A concurrent delivery (e.g. `opened` and `labeled` together) already imported it
        return None

    _record_activity("issue.activity.created", work_item, actor, {"name": work_item.name}, None)
    return synced


def apply_github_changes(synced, github_issue):
    """Copy the fields that changed on GitHub onto the work item. Returns True if anything changed."""
    current = github_snapshot(github_issue)
    changes = changed_fields(synced.github_snapshot, current)
    if not changes:
        return False

    repository = synced.repository
    work_item = synced.issue
    requested, previous = {}, {}

    if "title" in changes:
        previous["name"], requested["name"] = work_item.name, (current["title"] or "Untitled")[:255]
        work_item.name = requested["name"]
    if "body" in changes:
        previous["description_html"] = work_item.description_html
        work_item.description_html = requested["description_html"] = github_body_to_html(repository, current["body"])
        work_item.description_binary = None
    if "state" in changes:
        is_closed_in_plane = bool(work_item.state and work_item.state.group in CLOSED_STATE_GROUPS)
        should_close = current["state"] == "closed"
        if should_close != is_closed_in_plane:
            state = closed_state_for(repository) if should_close else open_state_for(repository)
            if state:
                previous["state_id"] = str(work_item.state_id) if work_item.state_id else None
                requested["state_id"] = str(state.id)
                work_item.state = state

    actor = get_github_bot_user(repository.workspace_id)
    if requested:
        work_item.updated_by = actor
        work_item.save()

    synced.github_snapshot = current
    synced.plane_snapshot = plane_snapshot(work_item)
    synced.last_synced_at = timezone.now()
    synced.save(update_fields=["github_snapshot", "plane_snapshot", "last_synced_at", "updated_at"])

    if requested:
        _record_activity("issue.activity.updated", work_item, actor, requested, previous)
    return bool(requested)


# Plane -> GitHub ---------------------------------------------------------------------------


def project_has_bidirectional_sync(project_id):
    return GithubWatchedRepository.objects.filter(
        project_id=project_id, issue_sync_mode=GithubIssueSyncMode.BIDIRECTIONAL
    ).exists()


def push_work_item(work_item_id):
    """Send a work item's changes to every bidirectional repository of its project.

    Work items already paired with a GitHub issue are updated; unpaired ones carrying the
    repository's Plane label are exported as new GitHub issues.
    """
    work_item = Issue.issue_objects.filter(pk=work_item_id).select_related("state").first()
    if work_item is None:
        return []

    results = []
    repositories = GithubWatchedRepository.objects.filter(
        project_id=work_item.project_id, issue_sync_mode=GithubIssueSyncMode.BIDIRECTIONAL
    ).select_related("connection")
    for repository in repositories:
        synced = GithubSyncedIssue.objects.filter(repository=repository, issue=work_item).first()
        if synced:
            results.append("updated" if push_plane_changes(synced, work_item) else "unchanged")
        elif work_item_has_label(work_item, repository.plane_label):
            results.append("exported" if export_work_item(repository, work_item) else "skipped")
    return results


def export_work_item(repository, work_item):
    # Lock the work item before calling GitHub so two concurrent pushes cannot create two issues
    with transaction.atomic():
        Issue.objects.select_for_update().filter(pk=work_item.pk).first()
        if GithubSyncedIssue.objects.filter(repository=repository, issue=work_item).exists():
            return None
        github_issue = github_client.create_issue(
            repository.connection,
            repository.full_name,
            title=work_item.name,
            body=plane_html_to_github_body(work_item.description_html),
        )
        if work_item.state and work_item.state.group in CLOSED_STATE_GROUPS:
            github_issue = github_client.update_issue(
                repository.connection, repository.full_name, github_issue["number"], state="closed"
            )
        synced = GithubSyncedIssue.objects.create(
            repository=repository,
            issue=work_item,
            project_id=work_item.project_id,
            github_issue_id=github_issue["id"],
            github_issue_number=github_issue["number"],
            html_url=github_issue["html_url"],
            github_snapshot=github_snapshot(github_issue),
            plane_snapshot=plane_snapshot(work_item),
            last_synced_at=timezone.now(),
        )
        IssueLink.objects.create(
            issue=work_item,
            project_id=work_item.project_id,
            url=github_issue["html_url"],
            title=f"{repository.full_name}#{github_issue['number']}",
            created_by=get_github_bot_user(repository.workspace_id),
        )
    return synced


def push_plane_changes(synced, work_item):
    current = plane_snapshot(work_item)
    changes = changed_fields(synced.plane_snapshot, current)
    if not changes:
        return False

    fields = {}
    if "name" in changes:
        fields["title"] = work_item.name
    if "description_html" in changes:
        fields["body"] = plane_html_to_github_body(work_item.description_html)
    if "closed" in changes:
        fields["state"] = "closed" if current["closed"] else "open"
        if current["closed"]:
            is_cancelled = work_item.state.group == StateGroup.CANCELLED.value
            fields["state_reason"] = "not_planned" if is_cancelled else "completed"

    github_issue = github_client.update_issue(
        synced.repository.connection, synced.repository.full_name, synced.github_issue_number, **fields
    )
    synced.github_snapshot = github_snapshot(github_issue)
    synced.plane_snapshot = current
    synced.last_synced_at = timezone.now()
    synced.save(update_fields=["github_snapshot", "plane_snapshot", "last_synced_at", "updated_at"])
    return True

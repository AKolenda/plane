# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Create or update work items from outside sources (call transcripts, Slack, ...).

A work item is identified by `(external_source, external_id)` within the workspace, using
Plane's existing `Issue.external_source` / `Issue.external_id` columns, so importing the same
item again updates it instead of creating a duplicate. Imports only add labels and assignees;
they never remove ones people added in Plane.
"""

# Python imports
import hashlib
import html
import json
import re

# Django imports
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

# Third party imports
from rest_framework.exceptions import ValidationError

# Module imports
from plane.db.models import Issue, IssueAssignee, IssueLabel, IssueLink, Label, Project, ProjectMember
from plane.utils.content_validator import validate_html_content

from .custom_properties import CustomPropertyError, set_values
from .links import work_item_identifier, work_item_url

MAX_TITLE_LENGTH = 255
MAX_EXTERNAL_FIELD_LENGTH = 255
MAX_LABELS = 20
MEMBER_ROLES = (15, 20)  # member, admin
LABEL_COLOR = "#6B7280"


class ExternalImportError(ValidationError):
    """A rejected import item. DRF answers it with 400 `{"error": message}`."""

    def __init__(self, message):
        super().__init__({"error": message})
        self.message = message


# Input normalization -----------------------------------------------------------------------


BULLET = re.compile(r"^\s*([-*•]|\d+[.)])\s+")


def text_to_html(text):
    """Turn plain text or light markdown (paragraphs, `- ` bullets) into editor HTML."""
    blocks = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if all(BULLET.match(line) for line in lines):
            items = "".join(f"<li><p>{html.escape(BULLET.sub('', line))}</p></li>" for line in lines)
            blocks.append(f"<ul>{items}</ul>")
        else:
            blocks.append("<p>" + "<br>".join(html.escape(line) for line in lines) + "</p>")
    return "".join(blocks) or "<p></p>"


def _clean_string(value, field, required=False, max_length=MAX_EXTERNAL_FIELD_LENGTH):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ExternalImportError(f"{field} is required.")
        return None
    if not isinstance(value, (str, int)):
        raise ExternalImportError(f"{field} must be a string.")
    value = str(value).strip()
    if len(value) > max_length:
        raise ExternalImportError(f"{field} must be at most {max_length} characters.")
    return value


def _description_html(item):
    if item.get("description_html"):
        is_valid, error, clean = validate_html_content(str(item["description_html"]))
        if not is_valid:
            raise ExternalImportError(error or "description_html is not valid HTML.")
        return clean
    if item.get("description") is not None:
        if not isinstance(item["description"], str):
            raise ExternalImportError("description must be a string.")
        return text_to_html(item["description"])
    return None


def _source_url(item):
    url = _clean_string(item.get("source_url"), "source_url", max_length=2048)
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        raise ExternalImportError("source_url must be an http(s) URL.")
    return url


def resolve_project(workspace, reference, user):
    reference = _clean_string(reference, "project", required=True, max_length=255)
    projects = Project.objects.filter(workspace=workspace, archived_at__isnull=True)
    project = projects.filter(identifier__iexact=reference).first()
    if project is None and re.fullmatch(r"[0-9a-fA-F-]{36}", reference):
        project = projects.filter(pk=reference).first()
    if project is None:
        raise ExternalImportError(f"Project {reference!r} not found.")
    if not ProjectMember.objects.filter(project=project, member=user, is_active=True, role__in=MEMBER_ROLES).exists():
        raise ExternalImportError(f"You are not a member of project {project.identifier}.")
    return project


def resolve_assignees(project, item):
    references = item.get("assignees")
    if references is None and item.get("assignee") not in (None, ""):
        references = [item["assignee"]]
    if references is None:
        return []
    if not isinstance(references, list):
        raise ExternalImportError("assignees must be a list.")
    members = []
    for reference in references:
        reference = _clean_string(reference, "assignee", required=True)
        if "@" not in reference and not re.fullmatch(r"[0-9a-fA-F-]{36}", reference):
            raise ExternalImportError(f"Assignee {reference!r} must be an email or user id.")
        lookup = Q(member__email__iexact=reference) if "@" in reference else Q(member_id=reference)
        membership = (
            ProjectMember.objects.filter(lookup, project=project, is_active=True, role__in=MEMBER_ROLES)
            .select_related("member")
            .first()
        )
        if membership is None:
            raise ExternalImportError(f"Assignee {reference!r} is not a member of project {project.identifier}.")
        members.append(membership.member)
    return members


def resolve_labels(project, item, actor):
    """Find labels by name (case-insensitive), creating the missing ones in the project."""
    names = item.get("labels") or []
    if not isinstance(names, list) or len(names) > MAX_LABELS:
        raise ExternalImportError(f"labels must be a list of at most {MAX_LABELS} names.")
    labels = []
    for name in names:
        name = _clean_string(name, "label", required=True)
        label = Label.objects.filter(project=project, name__iexact=name).first()
        if label is None:
            label = Label.objects.create(project=project, name=name, color=LABEL_COLOR, created_by=actor)
        if label not in labels:
            labels.append(label)
    return labels


# Upsert ------------------------------------------------------------------------------------


def _lock(workspace_id, external_source, external_id):
    """Serialize imports of the same external item; Issue has no unique constraint on these columns."""
    digest = hashlib.sha256(f"{workspace_id}:{external_source}:{external_id}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def _record(issue, actor, created, requested, previous):
    from plane.bgtasks.issue_activities_task import issue_activity
    from plane.bgtasks.webhook_task import model_activity

    issue_activity.delay(
        type="issue.activity.created" if created else "issue.activity.updated",
        requested_data=json.dumps(requested, cls=DjangoJSONEncoder),
        actor_id=str(actor.id),
        issue_id=str(issue.id),
        project_id=str(issue.project_id),
        current_instance=None if created else json.dumps(previous, cls=DjangoJSONEncoder),
        epoch=int(timezone.now().timestamp()),
        notification=True,
    )
    model_activity.delay(
        model_name="issue",
        model_id=str(issue.id),
        requested_data=json.loads(json.dumps(requested, cls=DjangoJSONEncoder)),
        current_instance=None if created else json.dumps(previous, cls=DjangoJSONEncoder),
        actor_id=str(actor.id),
        slug=issue.workspace.slug,
    )


def import_work_item(workspace, item, actor):
    """Create or update one work item. Returns `(issue, created)`; raises ExternalImportError on bad input."""
    if not isinstance(item, dict):
        raise ExternalImportError("Each item must be an object.")
    external_source = _clean_string(item.get("external_source"), "external_source", required=True)
    external_id = _clean_string(item.get("external_id"), "external_id", required=True)
    title = _clean_string(item.get("title"), "title", required=True, max_length=MAX_TITLE_LENGTH)
    project = resolve_project(workspace, item.get("project"), actor)
    description_html = _description_html(item)
    source_url = _source_url(item)
    assignees = resolve_assignees(project, item)
    custom_properties = item.get("custom_properties")

    with transaction.atomic():
        _lock(workspace.id, external_source, external_id)
        issue = (
            Issue.objects.filter(workspace=workspace, external_source=external_source, external_id=external_id)
            .select_related("project", "workspace")
            .order_by("created_at")
            .first()
        )
        labels = resolve_labels(issue.project if issue else project, item, actor)
        created = issue is None
        requested, previous = {}, {}

        if created:
            issue = Issue.objects.create(
                project=project,
                name=title,
                description_html=description_html or "<p></p>",
                external_source=external_source,
                external_id=external_id,
                created_by=actor,
                updated_by=actor,
            )
            requested = {"name": title}
        else:
            # Re-import: refresh the content that comes from the source
            if issue.name != title:
                previous["name"], requested["name"] = issue.name, title
                issue.name = title
            if description_html is not None and issue.description_html != description_html:
                previous["description_html"] = issue.description_html
                requested["description_html"] = description_html
                issue.description_html = description_html
                issue.description_binary = None
            if requested:
                issue.updated_by = actor
                issue.save()

        project_id = issue.project_id
        existing_assignees = set(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True))
        new_assignees = [member for member in assignees if member.id not in existing_assignees]
        for member in new_assignees:
            IssueAssignee.objects.create(issue=issue, assignee=member, project_id=project_id, created_by=actor)
        if new_assignees:
            previous["assignee_ids"] = [str(pk) for pk in existing_assignees]
            requested["assignee_ids"] = previous["assignee_ids"] + [str(member.id) for member in new_assignees]

        existing_labels = set(IssueLabel.objects.filter(issue=issue).values_list("label_id", flat=True))
        new_labels = [label for label in labels if label.id not in existing_labels]
        for label in new_labels:
            IssueLabel.objects.create(issue=issue, label=label, project_id=project_id, created_by=actor)
        if new_labels:
            previous["label_ids"] = [str(pk) for pk in existing_labels]
            requested["label_ids"] = previous["label_ids"] + [str(label.id) for label in new_labels]

        if source_url and not IssueLink.objects.filter(issue=issue, url=source_url).exists():
            IssueLink.objects.create(
                issue=issue,
                project_id=project_id,
                url=source_url,
                title=f"Source ({external_source})",
                created_by=actor,
            )

        if custom_properties is not None:
            try:
                set_values(issue, custom_properties, actor=actor)
            except CustomPropertyError as e:
                raise ExternalImportError(e.message) from e

    if created or requested:
        _record(issue, actor, created, requested, previous)
    return issue, created


def describe(issue, created):
    return {
        "id": str(issue.id),
        "identifier": work_item_identifier(issue),
        "project_id": str(issue.project_id),
        "external_source": issue.external_source,
        "external_id": issue.external_id,
        "created": created,
        "url": work_item_url(issue.workspace.slug, issue.id),
    }

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A per-user digest: open work assigned to them, blocked work, and recent imports.

Feeds the desktop notification app and the morning digest. Every item carries a stable URL.
"""

# Python imports
from datetime import timedelta

# Django imports
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

# Module imports
from plane.db.models import Issue, ProjectMember
from plane.db.models.state import StateGroup

from .links import work_item_identifier, work_item_url

CLOSED_GROUPS = (StateGroup.COMPLETED.value, StateGroup.CANCELLED.value)
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
DEFAULT_SINCE = timedelta(hours=24)


def serialize(issue, workspace_slug):
    return {
        "id": str(issue.id),
        "identifier": work_item_identifier(issue),
        "name": issue.name,
        "project": {"id": str(issue.project_id), "identifier": issue.project.identifier, "name": issue.project.name},
        "state": {"name": issue.state.name, "group": issue.state.group} if issue.state else None,
        "priority": issue.priority,
        "target_date": issue.target_date.isoformat() if issue.target_date else None,
        "external_source": issue.external_source,
        "created_at": issue.created_at.isoformat(),
        "updated_at": issue.updated_at.isoformat(),
        "url": work_item_url(workspace_slug, issue.id),
    }


def build_digest(
    workspace, user, since=None, blocked_label="blocked", blocked_scope="projects", sources=None, limit=50
):
    """The three digest lists for `user` within the projects they belong to."""
    since = since or timezone.now() - DEFAULT_SINCE
    project_ids = ProjectMember.objects.filter(
        workspace=workspace, member=user, is_active=True, project__archived_at__isnull=True
    ).values_list("project_id", flat=True)
    visible = Issue.issue_objects.filter(workspace=workspace, project_id__in=project_ids).select_related(
        "project", "state"
    )
    open_items = visible.exclude(state__group__in=CLOSED_GROUPS)
    # Conditions on one relation path share a join, so removed (soft-deleted) rows never match
    assigned = open_items.filter(issue_assignee__assignee=user, issue_assignee__deleted_at__isnull=True)

    priority_order = Case(
        *[When(priority=name, then=Value(rank)) for name, rank in PRIORITY_RANK.items()],
        default=Value(len(PRIORITY_RANK)),
        output_field=IntegerField(),
    )
    assigned_open = assigned.annotate(priority_rank=priority_order).order_by(
        "priority_rank", "target_date", "-updated_at"
    )

    blocked = (assigned if blocked_scope == "assigned" else open_items).filter(
        label_issue__label__name__iexact=blocked_label,
        label_issue__deleted_at__isnull=True,
        label_issue__label__deleted_at__isnull=True,
    )
    blocked = blocked.order_by("-updated_at")

    imported = visible.filter(external_source__isnull=False, created_at__gte=since).exclude(external_source="")
    if sources:
        imported = imported.filter(external_source__in=sources)
    imported = imported.order_by("-created_at")

    slug = workspace.slug
    lists = {
        "assigned_open": assigned_open.distinct(),
        "blocked": blocked.distinct(),
        "imported": imported,
    }
    result = {
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        "workspace": slug,
        "generated_at": timezone.now().isoformat(),
        "since": since.isoformat(),
        "counts": {},
    }
    for key, queryset in lists.items():
        result["counts"][key] = queryset.count()
        result[key] = [serialize(issue, slug) for issue in queryset[:limit]]
    return result

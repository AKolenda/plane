# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Link pull requests to work items through `[IDENTIFIER-123]` references."""

# Python imports
import re
from typing import NamedTuple

# Django imports
from django.db.models import Q

# Module imports
from plane.db.models import GithubPullRequestIssue, Issue

# Project identifiers are 1-12 characters without punctuation, upper-cased on save.
# The reference must be wrapped in square brackets so plain mentions such as "ENG-123" in prose,
# version strings, or ticket numbers from other trackers never link by accident.
WORK_ITEM_REFERENCE_PATTERN = re.compile(r"\[\s*([A-Za-z0-9_]{1,12})-(\d{1,9})\s*\]")


class WorkItemReference(NamedTuple):
    identifier: str
    sequence_id: int

    def __str__(self):
        return f"{self.identifier}-{self.sequence_id}"


def parse_work_item_references(*texts):
    """Return the unique `[IDENTIFIER-123]` references in `texts`, in order of first appearance."""
    references = []
    seen = set()
    for text in texts:
        for identifier, sequence_id in WORK_ITEM_REFERENCE_PATTERN.findall(text or ""):
            reference = WorkItemReference(identifier.upper(), int(sequence_id))
            if reference not in seen:
                seen.add(reference)
                references.append(reference)
    return references


def resolve_work_items(workspace_id, references):
    """Return the work items in the workspace that the references point to; unknown ones are skipped."""
    if not references:
        return []
    condition = Q()
    for reference in references:
        condition |= Q(project__identifier=reference.identifier, sequence_id=reference.sequence_id)
    return list(
        Issue.issue_objects.filter(condition, workspace_id=workspace_id)
        .select_related("project", "state")
        .order_by("project__identifier", "sequence_id")
    )


def sync_pull_request_links(pull_request, work_items):
    """Make the pull request link to exactly `work_items`.

    Returns `(added, kept)` lists of work items. References removed from the pull request
    title or description unlink the work item again.
    """
    existing = {
        link.issue_id: link
        for link in GithubPullRequestIssue.objects.filter(pull_request=pull_request).select_related("issue")
    }
    wanted = {work_item.id: work_item for work_item in work_items}

    stale_ids = [link.id for issue_id, link in existing.items() if issue_id not in wanted]
    if stale_ids:
        GithubPullRequestIssue.objects.filter(id__in=stale_ids).delete(soft=False)

    added, kept = [], []
    for issue_id, work_item in wanted.items():
        if issue_id in existing:
            kept.append(work_item)
            continue
        GithubPullRequestIssue.objects.create(
            pull_request=pull_request,
            issue=work_item,
            project_id=work_item.project_id,
            workspace_id=work_item.workspace_id,
        )
        added.append(work_item)
    return added, kept

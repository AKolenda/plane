# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Resolve a work item id to its current page, for links that must survive identifier renames."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, ProjectMember


class WorkItemLocateEndpoint(BaseAPIView):
    """`GET /api/workspaces/<slug>/work-items/<uuid>/locate/` for the `/<slug>/work-items/<uuid>` route.

    Answers 404 both when the work item does not exist and when the user cannot see its
    project, so the link reveals nothing to people outside the project.
    """

    def get(self, request, slug, issue_id):
        issue = (
            Issue.objects.filter(pk=issue_id, workspace__slug=slug, is_draft=False)
            .select_related("project")
            .only("id", "sequence_id", "archived_at", "project_id", "project__identifier", "project__archived_at")
            .first()
        )
        visible = (
            issue is not None
            and ProjectMember.objects.filter(project_id=issue.project_id, member=request.user, is_active=True).exists()
        )
        if not visible:
            return Response({"error": "Work item not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "id": str(issue.id),
                "project_id": str(issue.project_id),
                "project_identifier": issue.project.identifier,
                "sequence_id": issue.sequence_id,
                "is_archived": issue.archived_at is not None or issue.project.archived_at is not None,
            }
        )

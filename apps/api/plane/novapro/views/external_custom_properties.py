# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Public API (X-Api-Key) endpoints for custom properties. Values are keyed by property `key`."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ProjectEntityPermission
from plane.db.models import Issue, IssueCustomProperty
from plane.novapro.custom_properties import CustomPropertyError, set_values, values_for_issues
from plane.novapro.views.custom_properties import IssueCustomPropertySerializer


class ExternalCustomPropertyListEndpoint(BaseAPIView):
    """`GET /api/v1/workspaces/<slug>/projects/<project_id>/custom-properties/`"""

    permission_classes = [ProjectEntityPermission]

    def get(self, request, slug, project_id):
        properties = IssueCustomProperty.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response(IssueCustomPropertySerializer(properties, many=True).data)


class ExternalIssueCustomPropertyValuesEndpoint(BaseAPIView):
    """Read or write one work item's values as `{"<key>": value}`.

    Select values are option labels, user values are `{"id", "email", "display_name"}`
    on read and an id or email on write. `null` clears a value.
    """

    permission_classes = [ProjectEntityPermission]

    def get(self, request, slug, project_id, issue_id):
        Issue.issue_objects.get(workspace__slug=slug, project_id=project_id, pk=issue_id)
        return Response(values_for_issues(project_id, issue_ids=[issue_id], friendly=True).get(str(issue_id), {}))

    def patch(self, request, slug, project_id, issue_id):
        issue = Issue.issue_objects.get(workspace__slug=slug, project_id=project_id, pk=issue_id)
        try:
            set_values(issue, request.data, actor=request.user)
        except CustomPropertyError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(values_for_issues(project_id, issue_ids=[issue_id], friendly=True).get(str(issue_id), {}))

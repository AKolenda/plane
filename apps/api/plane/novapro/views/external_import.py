# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""`POST /api/v1/workspaces/<slug>/work-items/import/`: upsert work items from external sources."""

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.db.models import Workspace
from plane.novapro.external_import import ExternalImportError, describe, import_work_item

MAX_BATCH = 100


class ExternalWorkItemImportEndpoint(BaseAPIView):
    """Create or update work items keyed by `external_source` + `external_id`.

    Send one object, or a list of up to 100 for a batch. A single object answers 201 when it
    created a work item and 200 when it updated one; a batch answers 207 with one result per
    item, in order, each either the work item or `{"error": ...}`.
    """

    permission_classes = [WorkspaceEntityPermission]

    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)

        if isinstance(request.data, list):
            if not request.data or len(request.data) > MAX_BATCH:
                return Response({"error": f"Send between 1 and {MAX_BATCH} items."}, status=status.HTTP_400_BAD_REQUEST)
            results = []
            for item in request.data:
                try:
                    results.append(describe(*import_work_item(workspace, item, request.user)))
                except ExternalImportError as e:
                    results.append({"error": str(e)})
            return Response(results, status=status.HTTP_207_MULTI_STATUS)

        try:
            issue, created = import_work_item(workspace, request.data, request.user)
        except ExternalImportError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(describe(issue, created), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

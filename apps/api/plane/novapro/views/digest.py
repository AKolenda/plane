# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""`GET /api/v1/workspaces/<slug>/digest/`: what a person should look at today."""

# Python imports
import re

# Django imports
from django.utils.dateparse import parse_datetime

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import WorkspaceEntityPermission
from plane.db.models import Workspace, WorkspaceMember
from plane.novapro.digest import build_digest

ADMIN_ROLE = 20
MAX_LIMIT = 200


def _error(message):
    return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)


class DigestEndpoint(BaseAPIView):
    """Open work items assigned to the user, open work items labeled blocked, and imports since `since`.

    Query parameters (all optional):

    * `user`: email or id; defaults to the API key's owner. Other users need a workspace admin key.
    * `since`: ISO 8601 timestamp for the imported list; defaults to 24 hours ago.
    * `blocked_label`: label name, default `blocked`.
    * `blocked_scope`: `projects` (default, every blocked item in the user's projects) or `assigned`.
    * `sources`: comma-separated external sources for the imported list, e.g. `transcript,slack`.
    * `limit`: items per list, default 50, at most 200.
    """

    permission_classes = [WorkspaceEntityPermission]

    def get(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)
        params = request.GET

        user = request.user
        reference = params.get("user")
        if reference and reference not in (str(user.id), user.email):
            is_admin = WorkspaceMember.objects.filter(
                workspace=workspace, member=user, role=ADMIN_ROLE, is_active=True
            ).exists()
            if not is_admin:
                return Response(
                    {"error": "Only workspace admins can read another member's digest."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if "@" not in reference and not re.fullmatch(r"[0-9a-fA-F-]{36}", reference):
                return _error("user must be an email or user id.")
            lookup = {"member__email__iexact": reference} if "@" in reference else {"member_id": reference}
            membership = (
                WorkspaceMember.objects.filter(workspace=workspace, is_active=True, **lookup)
                .select_related("member")
                .first()
            )
            if membership is None:
                return Response({"error": "User not found in this workspace."}, status=status.HTTP_404_NOT_FOUND)
            user = membership.member

        since = None
        if params.get("since"):
            since = parse_datetime(params["since"].replace(" ", "+"))
            if since is None or since.tzinfo is None:
                return _error("since must be an ISO 8601 timestamp with a timezone, e.g. 2026-10-08T07:00:00Z.")

        blocked_scope = params.get("blocked_scope", "projects")
        if blocked_scope not in ("projects", "assigned"):
            return _error("blocked_scope must be projects or assigned.")
        try:
            limit = min(max(int(params.get("limit", 50)), 1), MAX_LIMIT)
        except ValueError:
            return _error("limit must be a number.")
        sources = [s.strip() for s in params.get("sources", "").split(",") if s.strip()] or None

        return Response(
            build_digest(
                workspace,
                user,
                since=since,
                blocked_label=params.get("blocked_label", "blocked").strip() or "blocked",
                blocked_scope=blocked_scope,
                sources=sources,
                limit=limit,
            )
        )

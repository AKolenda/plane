# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging
from urllib.parse import urlencode

# Django imports
from django.db import transaction

# Third party imports
from github import GithubException
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers.github import (
    GithubConnectionSerializer,
    GithubPullRequestSerializer,
    GithubStateMappingUpdateSerializer,
    GithubWatchedRepositorySerializer,
)
from plane.db.models import (
    GithubAuthType,
    GithubConnection,
    GithubPullRequest,
    GithubStateMapping,
    GithubWatchedRepository,
    Workspace,
)
from plane.integrations.github import client as github_client
from plane.integrations.github.config import get_github_settings
from plane.integrations.github.connect import OAUTH_SCOPES, callback_url, sign_state
from plane.license.utils.encryption import decrypt_data

from ..base import BaseAPIView

logger = logging.getLogger("plane.api")


def _github_error_response(error, fallback):
    """Turn a GitHub API failure into a 400 with GitHub's own message when it has one."""
    if isinstance(error, GithubException):
        message = (error.data or {}).get("message") if isinstance(error.data, dict) else None
        return Response({"error": message or fallback}, status=status.HTTP_400_BAD_REQUEST)
    logger.exception(fallback)
    return Response({"error": fallback}, status=status.HTTP_400_BAD_REQUEST)


def webhook_url_for(connection):
    github_settings = get_github_settings()
    return f"{github_settings.webhook_base_url}/api/integrations/github/webhook/{connection.id}/"


class GithubIntegrationEndpoint(BaseAPIView):
    """Instance capabilities plus the workspace's connections."""

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        github_settings = get_github_settings()
        connections = GithubConnection.objects.filter(workspace__slug=slug)
        return Response(
            {
                "host_url": github_settings.host_url,
                "is_enterprise": github_settings.is_enterprise,
                "is_app_configured": github_settings.is_app_configured,
                "is_oauth_configured": github_settings.is_oauth_configured,
                "app_slug": github_settings.app_slug,
                "connections": GithubConnectionSerializer(connections, many=True).data,
            }
        )


class GithubConnectEndpoint(BaseAPIView):
    """Return the GitHub URL that starts an App installation or an OAuth authorization."""

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        github_settings = get_github_settings()
        auth_type = request.data.get("auth_type", GithubAuthType.APP)
        workspace = Workspace.objects.get(slug=slug)
        state = sign_state(workspace.id, request.user.id, auth_type)

        if auth_type == GithubAuthType.APP:
            if not github_settings.is_app_configured:
                return Response({"error": "The GitHub App is not configured."}, status=status.HTTP_400_BAD_REQUEST)
            url = f"{github_settings.host_url}/apps/{github_settings.app_slug}/installations/new?" + urlencode(
                {"state": state}
            )
        elif auth_type == GithubAuthType.OAUTH:
            if not github_settings.is_oauth_configured:
                return Response(
                    {"error": "The GitHub OAuth App is not configured."}, status=status.HTTP_400_BAD_REQUEST
                )
            url = f"{github_settings.host_url}/login/oauth/authorize?" + urlencode(
                {
                    "client_id": github_settings.oauth_client_id,
                    "scope": " ".join(OAUTH_SCOPES),
                    "state": state,
                    "redirect_uri": callback_url(request),
                    "allow_signup": "false",
                }
            )
        else:
            return Response({"error": "Unknown connection type."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"url": url})


class GithubConnectionEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        connection = GithubConnection.objects.get(workspace__slug=slug, pk=pk)
        if connection.auth_type == GithubAuthType.OAUTH:
            for repository in connection.repositories.exclude(webhook_id__isnull=True):
                try:
                    github_client.delete_repository_webhook(connection, repository.full_name, repository.webhook_id)
                except Exception as e:
                    # The token may already be revoked; the connection still goes away
                    logger.warning(f"Could not delete webhook for {repository.full_name}: {e}")
        connection.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GithubAvailableRepositoriesEndpoint(BaseAPIView):
    """Repositories the connection can reach on GitHub, marked with whether they are already watched."""

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, pk):
        connection = GithubConnection.objects.get(workspace__slug=slug, pk=pk)
        try:
            repositories = github_client.list_accessible_repositories(connection)
        except Exception as e:
            return _github_error_response(e, "Could not list repositories from GitHub.")
        watched = dict(GithubWatchedRepository.objects.filter(connection=connection).values_list("repository_id", "id"))
        for repository in repositories:
            repository["watched_id"] = watched.get(repository["id"])
        return Response(repositories)


class GithubWatchedRepositoryEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        repositories = GithubWatchedRepository.objects.filter(workspace__slug=slug).select_related("connection")
        return Response(GithubWatchedRepositorySerializer(repositories, many=True).data)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        connection = GithubConnection.objects.filter(workspace__slug=slug, pk=request.data.get("connection_id")).first()
        if connection is None:
            return Response({"error": "Connection not found."}, status=status.HTTP_404_NOT_FOUND)
        repository_id = request.data.get("repository_id")
        if not str(repository_id or "").isdigit():
            return Response({"error": "repository_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        if GithubWatchedRepository.objects.filter(connection=connection, repository_id=repository_id).exists():
            return Response({"error": "Repository is already watched."}, status=status.HTTP_409_CONFLICT)

        try:
            repository = github_client.get_repository(connection, repository_id)
        except Exception as e:
            return _github_error_response(e, "Could not read the repository from GitHub.")

        with transaction.atomic():
            watched = GithubWatchedRepository.objects.create(
                workspace_id=connection.workspace_id,
                connection=connection,
                repository_id=repository["id"],
                full_name=repository["full_name"],
                html_url=repository["html_url"],
                default_branch=repository["default_branch"],
                is_private=repository["private"],
            )
            if connection.auth_type == GithubAuthType.OAUTH:
                # OAuth connections receive events through a webhook on each watched repository
                try:
                    watched.webhook_id = github_client.create_repository_webhook(
                        connection,
                        repository["full_name"],
                        webhook_url_for(connection),
                        decrypt_data(connection.webhook_secret),
                    )
                except Exception as e:
                    transaction.set_rollback(True)
                    return _github_error_response(
                        e, "Could not create the repository webhook. Admin access to the repository is required."
                    )
                watched.save(update_fields=["webhook_id"])

        return Response(GithubWatchedRepositorySerializer(watched).data, status=status.HTTP_201_CREATED)


class GithubWatchedRepositoryDetailEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def patch(self, request, slug, pk):
        watched = GithubWatchedRepository.objects.get(workspace__slug=slug, pk=pk)
        serializer = GithubWatchedRepositorySerializer(
            watched, data=request.data, partial=True, context={"workspace_id": watched.workspace_id}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        watched = GithubWatchedRepository.objects.select_related("connection").get(workspace__slug=slug, pk=pk)
        if watched.webhook_id:
            try:
                github_client.delete_repository_webhook(watched.connection, watched.full_name, watched.webhook_id)
            except Exception as e:
                logger.warning(f"Could not delete webhook for {watched.full_name}: {e}")
        watched.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GithubStateMappingEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        mappings = GithubStateMapping.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response(
            [{"id": m.id, "event": m.event, "base_branch": m.base_branch, "state_id": m.state_id} for m in mappings]
        )

    @allow_permission(allowed_roles=[ROLE.ADMIN])
    def put(self, request, slug, project_id):
        """Replace the project's mappings with the submitted list."""
        serializer = GithubStateMappingUpdateSerializer(data=request.data, context={"project_id": project_id})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            GithubStateMapping.objects.filter(project_id=project_id).delete(soft=False)
            for item in serializer.validated_data["mappings"]:
                GithubStateMapping.objects.create(
                    project_id=project_id,
                    event=item["event"],
                    base_branch=item["base_branch"],
                    state_id=item["state_id"],
                )
        return self.get(request, slug=slug, project_id=project_id)


class IssueGithubPullRequestEndpoint(BaseAPIView):
    @allow_permission(allowed_roles=[ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        pull_requests = (
            GithubPullRequest.objects.filter(
                workspace__slug=slug,
                issue_links__issue_id=issue_id,
                issue_links__project_id=project_id,
                issue_links__deleted_at__isnull=True,
            )
            .select_related("repository")
            .distinct()
            .order_by("-opened_at")
        )
        return Response(GithubPullRequestSerializer(pull_requests, many=True).data)

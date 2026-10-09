# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views import (
    GithubAvailableRepositoriesEndpoint,
    GithubCallbackEndpoint,
    GithubConnectEndpoint,
    GithubConnectionEndpoint,
    GithubIntegrationEndpoint,
    GithubStateMappingEndpoint,
    GithubWatchedRepositoryDetailEndpoint,
    GithubWatchedRepositoryEndpoint,
    GithubWebhookEndpoint,
    IssueGithubPullRequestEndpoint,
)


urlpatterns = [
    # Called by GitHub
    path("integrations/github/callback/", GithubCallbackEndpoint.as_view(), name="github-callback"),
    path("integrations/github/webhook/", GithubWebhookEndpoint.as_view(), name="github-webhook"),
    path(
        "integrations/github/webhook/<uuid:connection_id>/",
        GithubWebhookEndpoint.as_view(),
        name="github-webhook-connection",
    ),
    # Workspace settings
    path("workspaces/<str:slug>/integrations/github/", GithubIntegrationEndpoint.as_view(), name="github-integration"),
    path(
        "workspaces/<str:slug>/integrations/github/connect/",
        GithubConnectEndpoint.as_view(),
        name="github-connect",
    ),
    path(
        "workspaces/<str:slug>/integrations/github/connections/<uuid:pk>/",
        GithubConnectionEndpoint.as_view(),
        name="github-connection",
    ),
    path(
        "workspaces/<str:slug>/integrations/github/connections/<uuid:pk>/available-repositories/",
        GithubAvailableRepositoriesEndpoint.as_view(),
        name="github-available-repositories",
    ),
    path(
        "workspaces/<str:slug>/integrations/github/repositories/",
        GithubWatchedRepositoryEndpoint.as_view(),
        name="github-repositories",
    ),
    path(
        "workspaces/<str:slug>/integrations/github/repositories/<uuid:pk>/",
        GithubWatchedRepositoryDetailEndpoint.as_view(),
        name="github-repository",
    ),
    # Project settings
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/integrations/github/state-mappings/",
        GithubStateMappingEndpoint.as_view(),
        name="github-state-mappings",
    ),
    # Work item detail
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/github/pull-requests/",
        IssueGithubPullRequestEndpoint.as_view(),
        name="issue-github-pull-requests",
    ),
]

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from plane.db.models.base import BaseModel
from plane.db.models.project import ProjectBaseModel
from plane.db.models.workspace import WorkspaceBaseModel


class GithubAuthType(models.TextChoices):
    APP = "app", "GitHub App"
    OAUTH = "oauth", "OAuth App"


class GithubIssueSyncMode(models.TextChoices):
    DISABLED = "disabled", "Disabled"
    GITHUB_TO_PLANE = "github_to_plane", "GitHub to Plane"
    BIDIRECTIONAL = "bidirectional", "Bidirectional"


class GithubPullRequestEvent(models.TextChoices):
    DRAFTED = "drafted", "Draft opened"
    OPENED = "opened", "Opened"
    REVIEW_REQUESTED = "review_requested", "Review requested"
    READY_FOR_REVIEW = "ready_for_review", "Ready for review"
    APPROVED = "approved", "Approved"
    MERGED = "merged", "Merged"
    CLOSED = "closed", "Closed without merging"


class GithubPullRequestState(models.TextChoices):
    OPEN = "open", "Open"
    DRAFT = "draft", "Draft"
    MERGED = "merged", "Merged"
    CLOSED = "closed", "Closed"


class GithubConnection(BaseModel):
    """A GitHub account or organization connected to a workspace.

    Credentials are stored encrypted with Plane's instance secret: an OAuth access token
    (and the secret used for the repository webhooks it creates) for OAuth connections, or
    only the installation id for GitHub App connections, whose keys live in instance config.
    """

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="github_connections")
    auth_type = models.CharField(max_length=20, choices=GithubAuthType.choices)
    host_url = models.URLField(max_length=255, default="https://github.com")
    api_url = models.URLField(max_length=255, default="https://api.github.com")
    account_id = models.BigIntegerField()
    account_login = models.CharField(max_length=255)
    account_type = models.CharField(max_length=50, default="User")
    account_avatar_url = models.TextField(blank=True, default="")
    installation_id = models.BigIntegerField(null=True, blank=True)
    access_token = models.TextField(blank=True, default="")
    webhook_secret = models.TextField(blank=True, default="")
    connected_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, related_name="github_connections")
    bot_user = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, related_name="github_bot_connections")

    def __str__(self):
        return f"{self.account_login} <{self.workspace_id}>"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "host_url", "auth_type", "account_id"],
                condition=Q(deleted_at__isnull=True),
                name="github_connection_unique_account_when_deleted_at_null",
            ),
            # An installation belongs to exactly one workspace on an instance
            models.UniqueConstraint(
                fields=["host_url", "installation_id"],
                condition=Q(deleted_at__isnull=True, installation_id__isnull=False),
                name="github_connection_unique_installation_when_deleted_at_null",
            ),
        ]
        verbose_name = "GitHub Connection"
        verbose_name_plural = "GitHub Connections"
        db_table = "github_connections"
        ordering = ("-created_at",)


class GithubWatchedRepository(WorkspaceBaseModel):
    """A repository whose pull requests (and optionally issues) Plane listens to.

    `project` is only needed for issue sync: pull requests link to work items in any
    project of the workspace through the `[IDENTIFIER-123]` reference.
    """

    connection = models.ForeignKey("db.GithubConnection", on_delete=models.CASCADE, related_name="repositories")
    repository_id = models.BigIntegerField()
    full_name = models.CharField(max_length=512)
    html_url = models.URLField(max_length=1024)
    default_branch = models.CharField(max_length=255, blank=True, default="")
    is_private = models.BooleanField(default=False)
    webhook_id = models.BigIntegerField(null=True, blank=True)
    issue_sync_mode = models.CharField(
        max_length=20, choices=GithubIssueSyncMode.choices, default=GithubIssueSyncMode.DISABLED
    )
    # GitHub issues carrying this label are imported into Plane
    github_label = models.CharField(max_length=255, default="plane")
    # Plane work items carrying this label are exported to GitHub (bidirectional only)
    plane_label = models.CharField(max_length=255, default="github")
    open_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    closed_state = models.ForeignKey("db.State", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    def __str__(self):
        return self.full_name

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "repository_id"],
                condition=Q(deleted_at__isnull=True),
                name="github_watched_repository_unique_when_deleted_at_null",
            )
        ]
        verbose_name = "GitHub Watched Repository"
        verbose_name_plural = "GitHub Watched Repositories"
        db_table = "github_watched_repositories"
        ordering = ("full_name",)


class GithubPullRequest(BaseModel):
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="github_pull_requests")
    repository = models.ForeignKey("db.GithubWatchedRepository", on_delete=models.CASCADE, related_name="pull_requests")
    github_id = models.BigIntegerField()
    number = models.IntegerField()
    title = models.CharField(max_length=1024)
    html_url = models.URLField(max_length=1024)
    state = models.CharField(max_length=20, choices=GithubPullRequestState.choices, default="open")
    base_branch = models.CharField(max_length=255, blank=True, default="")
    head_branch = models.CharField(max_length=255, blank=True, default="")
    author_login = models.CharField(max_length=255, blank=True, default="")
    last_event = models.CharField(max_length=32, choices=GithubPullRequestEvent.choices, blank=True, default="")
    opened_at = models.DateTimeField(null=True, blank=True)
    merged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # `updated_at` of the newest delivery applied; older deliveries arriving late are not replayed
    github_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.repository.full_name}#{self.number}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "number"],
                condition=Q(deleted_at__isnull=True),
                name="github_pull_request_unique_number_when_deleted_at_null",
            )
        ]
        verbose_name = "GitHub Pull Request"
        verbose_name_plural = "GitHub Pull Requests"
        db_table = "github_pull_requests"
        ordering = ("-created_at",)


class GithubPullRequestIssue(ProjectBaseModel):
    pull_request = models.ForeignKey("db.GithubPullRequest", on_delete=models.CASCADE, related_name="issue_links")
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="github_pull_request_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pull_request", "issue"],
                condition=Q(deleted_at__isnull=True),
                name="github_pull_request_issue_unique_when_deleted_at_null",
            )
        ]
        verbose_name = "GitHub Pull Request Issue"
        verbose_name_plural = "GitHub Pull Request Issues"
        db_table = "github_pull_request_issues"
        ordering = ("-created_at",)


class GithubStateMapping(ProjectBaseModel):
    """Moves linked work items to `state` when a pull request event happens.

    An empty `base_branch` matches every target branch; a non-empty one is an exact
    branch name or a glob such as `release/*`, and wins over the empty fallback.
    """

    event = models.CharField(max_length=32, choices=GithubPullRequestEvent.choices)
    base_branch = models.CharField(max_length=255, blank=True, default="")
    state = models.ForeignKey("db.State", on_delete=models.CASCADE, related_name="github_state_mappings")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "event", "base_branch"],
                condition=Q(deleted_at__isnull=True),
                name="github_state_mapping_unique_when_deleted_at_null",
            )
        ]
        verbose_name = "GitHub State Mapping"
        verbose_name_plural = "GitHub State Mappings"
        db_table = "github_state_mappings"
        ordering = ("created_at",)


class GithubSyncedIssue(ProjectBaseModel):
    """Pairs a Plane work item with a GitHub issue.

    The snapshots hold the last values each side was known to have, so a sync only
    sends the fields that changed and ignores the echo of its own writes.
    """

    repository = models.ForeignKey("db.GithubWatchedRepository", on_delete=models.CASCADE, related_name="synced_issues")
    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="github_synced_issues")
    github_issue_id = models.BigIntegerField()
    github_issue_number = models.IntegerField()
    html_url = models.URLField(max_length=1024)
    github_snapshot = models.JSONField(default=dict)
    plane_snapshot = models.JSONField(default=dict)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "github_issue_number"],
                condition=Q(deleted_at__isnull=True),
                name="github_synced_issue_unique_number_when_deleted_at_null",
            ),
            models.UniqueConstraint(
                fields=["repository", "issue"],
                condition=Q(deleted_at__isnull=True),
                name="github_synced_issue_unique_issue_when_deleted_at_null",
            ),
        ]
        verbose_name = "GitHub Synced Issue"
        verbose_name_plural = "GitHub Synced Issues"
        db_table = "github_synced_issues"
        ordering = ("-created_at",)

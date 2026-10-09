# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import (
    GithubConnection,
    GithubIssueSyncMode,
    GithubPullRequest,
    GithubPullRequestEvent,
    GithubWatchedRepository,
    State,
)

from .base import BaseSerializer


class GithubConnectionSerializer(BaseSerializer):
    class Meta:
        model = GithubConnection
        fields = [
            "id",
            "auth_type",
            "host_url",
            "account_id",
            "account_login",
            "account_type",
            "account_avatar_url",
            "installation_id",
            "connected_by",
            "created_at",
        ]
        read_only_fields = fields


class GithubWatchedRepositorySerializer(BaseSerializer):
    class Meta:
        model = GithubWatchedRepository
        fields = [
            "id",
            "connection",
            "repository_id",
            "full_name",
            "html_url",
            "default_branch",
            "is_private",
            "project",
            "issue_sync_mode",
            "github_label",
            "plane_label",
            "open_state",
            "closed_state",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "connection",
            "repository_id",
            "full_name",
            "html_url",
            "default_branch",
            "is_private",
            "created_at",
        ]

    def validate(self, attrs):
        instance = self.instance
        project = attrs.get("project", instance.project if instance else None)
        sync_mode = attrs.get("issue_sync_mode", instance.issue_sync_mode if instance else None)
        workspace_id = self.context["workspace_id"]

        if project and project.workspace_id != workspace_id:
            raise serializers.ValidationError({"project": "Project does not belong to this workspace."})
        if sync_mode != GithubIssueSyncMode.DISABLED and project is None:
            raise serializers.ValidationError({"project": "Choose a project to sync issues into."})
        for field in ("open_state", "closed_state"):
            state = attrs.get(field, getattr(instance, field) if instance else None)
            if state and (project is None or state.project_id != project.id):
                raise serializers.ValidationError({field: "State must belong to the selected project."})
        for field in ("github_label", "plane_label"):
            if field in attrs and not (attrs[field] or "").strip():
                raise serializers.ValidationError({field: "Label cannot be empty."})
            if field in attrs:
                attrs[field] = attrs[field].strip()
        # Changing the project drops states picked from the previous one
        if instance and "project" in attrs and attrs["project"] != instance.project:
            attrs.setdefault("open_state", None)
            attrs.setdefault("closed_state", None)
        return attrs


class GithubStateMappingItemSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=GithubPullRequestEvent.choices)
    base_branch = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    state_id = serializers.UUIDField()

    def validate_base_branch(self, value):
        return (value or "").strip()


class GithubStateMappingUpdateSerializer(serializers.Serializer):
    mappings = GithubStateMappingItemSerializer(many=True)

    def validate_mappings(self, mappings):
        project_id = self.context["project_id"]
        state_ids = {str(item["state_id"]) for item in mappings}
        valid_ids = {
            str(pk) for pk in State.objects.filter(project_id=project_id, id__in=state_ids).values_list("id", flat=True)
        }
        seen = set()
        for item in mappings:
            if str(item["state_id"]) not in valid_ids:
                raise serializers.ValidationError("Every state must belong to this project.")
            key = (item["event"], item["base_branch"])
            if key in seen:
                branch = item["base_branch"] or "any branch"
                raise serializers.ValidationError(f"Duplicate mapping for {item['event']} on {branch}.")
            seen.add(key)
        return mappings


class GithubPullRequestSerializer(BaseSerializer):
    repository_full_name = serializers.CharField(source="repository.full_name", read_only=True)

    class Meta:
        model = GithubPullRequest
        fields = [
            "id",
            "number",
            "title",
            "html_url",
            "state",
            "base_branch",
            "head_branch",
            "author_login",
            "last_event",
            "repository_full_name",
            "opened_at",
            "merged_at",
            "closed_at",
            "updated_at",
        ]
        read_only_fields = fields

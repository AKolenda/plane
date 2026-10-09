# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

import pytest
from django.utils import timezone

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueLabel,
    Label,
    Project,
    ProjectMember,
    User,
    WorkspaceMember,
)
from plane.db.models.api import APIToken


def url(workspace, **params):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"/api/v1/workspaces/{workspace.slug}/digest/" + (f"?{query}" if query else "")


def assign(issue, user):
    IssueAssignee.objects.create(issue=issue, assignee=user, project=issue.project)


def label(issue, name):
    found = Label.objects.filter(project=issue.project, name=name).first() or Label.objects.create(
        project=issue.project, name=name
    )
    IssueLabel.objects.create(issue=issue, label=found, project=issue.project)


@pytest.fixture
def items(project, states, create_user):
    make = lambda name, **kw: Issue.objects.create(project=project, name=name, **kw)  # noqa: E731
    data = {
        "urgent": make("Urgent fix", priority="urgent", state=states["In Progress"]),
        "low": make("Low chore", priority="low", state=states["Backlog"]),
        "done": make("Already done", priority="urgent", state=states["Done"]),
        "unassigned_blocked": make("Waiting on vendor", state=states["Backlog"]),
        "my_blocked": make("Blocked on review", priority="medium", state=states["Backlog"]),
        "imported": make(
            "From the call", state=states["Backlog"], external_source="transcript", external_id="call.txt#1"
        ),
        "old_import": make("Old import", state=states["Backlog"], external_source="slack", external_id="x"),
    }
    for key in ("urgent", "low", "done", "my_blocked"):
        assign(data[key], create_user)
    label(data["unassigned_blocked"], "Blocked")
    label(data["my_blocked"], "blocked")
    Issue.objects.filter(pk=data["old_import"].pk).update(created_at=timezone.now() - timedelta(days=3))
    return data


def names(entries):
    return [entry["name"] for entry in entries]


@pytest.mark.unit
@pytest.mark.django_db
class TestDigest:
    def test_lists_for_the_key_owner(self, token_client, workspace, items):
        response = token_client.get(url(workspace))
        assert response.status_code == 200, response.data
        data = response.data
        # Open items assigned to me, most urgent first; completed ones are left out
        assert names(data["assigned_open"]) == ["Urgent fix", "Blocked on review", "Low chore"]
        # Blocked label matches case-insensitively across my projects
        assert sorted(names(data["blocked"])) == ["Blocked on review", "Waiting on vendor"]
        # Imports from the last 24 hours by default
        assert names(data["imported"]) == ["From the call"]
        assert data["counts"] == {"assigned_open": 3, "blocked": 2, "imported": 1}

        entry = data["assigned_open"][0]
        assert entry["identifier"] == f"ENG-{items['urgent'].sequence_id}"
        assert entry["state"] == {"name": "In Progress", "group": "started"}
        assert entry["url"].endswith(f"/{workspace.slug}/work-items/{items['urgent'].id}")

    def test_since_and_sources(self, token_client, workspace, items):
        since = (timezone.now() - timedelta(days=7)).isoformat().replace("+00:00", "Z")
        data = token_client.get(url(workspace, since=since)).data
        assert sorted(names(data["imported"])) == ["From the call", "Old import"]
        data = token_client.get(url(workspace, since=since, sources="slack")).data
        assert names(data["imported"]) == ["Old import"]

    def test_blocked_scope_assigned_and_custom_label(self, token_client, workspace, items):
        data = token_client.get(url(workspace, blocked_scope="assigned")).data
        assert names(data["blocked"]) == ["Blocked on review"]
        label(items["low"], "waiting")
        data = token_client.get(url(workspace, blocked_label="waiting")).data
        assert names(data["blocked"]) == ["Low chore"]

    def test_removed_assignment_is_not_listed(self, token_client, workspace, items, create_user):
        IssueAssignee.objects.filter(issue=items["low"], assignee=create_user).delete()
        assert "Low chore" not in names(token_client.get(url(workspace)).data["assigned_open"])

    def test_projects_the_user_is_not_in_are_excluded(self, token_client, workspace, items, create_user):
        other = Project.objects.create(name="Secret", identifier="SEC", workspace=workspace)
        hidden = Issue.objects.create(project=other, name="Hidden", external_source="slack", external_id="h")
        assign(hidden, create_user)
        data = token_client.get(url(workspace)).data
        assert "Hidden" not in names(data["assigned_open"]) + names(data["imported"])

    def test_admin_can_read_another_members_digest(self, token_client, workspace, project, items):
        teammate = User.objects.create(email="teammate@plane.so", username="teammate")
        WorkspaceMember.objects.create(workspace=workspace, member=teammate, role=15)
        ProjectMember.objects.create(project=project, member=teammate, role=15)
        assign(items["low"], teammate)
        data = token_client.get(url(workspace, user="teammate@plane.so")).data
        assert data["user"]["email"] == "teammate@plane.so"
        assert names(data["assigned_open"]) == ["Low chore"]

    def test_members_cannot_read_others(self, api_client, workspace, create_user):
        member = User.objects.create(email="m@plane.so", username="m")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        token = APIToken.objects.create(user=member, label="m", token="plane_api_member", workspace=workspace)
        api_client.credentials(HTTP_X_API_KEY=token.token)
        assert api_client.get(url(workspace, user=create_user.email)).status_code == 403
        assert api_client.get(url(workspace, user="m@plane.so")).status_code == 200

    @pytest.mark.parametrize(
        "params",
        [{"since": "yesterday"}, {"since": "2026-10-08T07:00:00"}, {"blocked_scope": "all"}, {"limit": "many"}],
    )
    def test_bad_parameters(self, token_client, workspace, params):
        assert token_client.get(url(workspace, **params)).status_code == 400

    def test_limit(self, token_client, workspace, items):
        data = token_client.get(url(workspace, limit=1)).data
        assert len(data["assigned_open"]) == 1 and data["counts"]["assigned_open"] == 3

    def test_requires_api_key(self, api_client, workspace):
        assert api_client.get(url(workspace)).status_code == 401

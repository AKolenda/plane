# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import pytest

from plane.db.models import (
    GithubAuthType,
    GithubConnection,
    GithubStateMapping,
    GithubWatchedRepository,
    Issue,
    Project,
    ProjectMember,
    State,
)
from plane.license.utils.encryption import encrypt_data

WEBHOOK_SECRET = "oauth-webhook-secret"


@pytest.fixture(autouse=True)
def background_tasks():
    """Keep celery out of unit tests: record activity, push and webhook tasks instead of queueing them."""
    with (
        patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as activity,
        patch("plane.bgtasks.github_integration_task.push_work_item_to_github.delay") as push,
        patch("plane.bgtasks.github_integration_task.process_github_webhook.delay") as webhook,
        patch("plane.bgtasks.webhook_task.model_activity.delay") as model_activity,
    ):
        yield {"activity": activity, "push": push, "webhook": webhook, "model_activity": model_activity}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Engineering", identifier="ENG", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


@pytest.fixture
def states(project):
    rows = [
        ("Backlog", "backlog", True),
        ("In Progress", "started", False),
        ("In Review", "started", False),
        ("In QA", "started", False),
        ("Deployed", "completed", False),
        ("Cancelled", "cancelled", False),
    ]
    return {
        name: State.objects.create(project=project, name=name, group=group, default=default, color="#000000")
        for name, group, default in rows
    }


@pytest.fixture
def work_item(project, states):
    return Issue.objects.create(project=project, name="Ship the GitHub integration", state=states["Backlog"])


@pytest.fixture
def connection(workspace, create_user):
    return GithubConnection.objects.create(
        workspace=workspace,
        auth_type=GithubAuthType.OAUTH,
        account_id=1001,
        account_login="acme",
        account_type="Organization",
        access_token=encrypt_data("gho_test_token"),
        webhook_secret=encrypt_data(WEBHOOK_SECRET),
        connected_by=create_user,
    )


@pytest.fixture
def repository(connection, project):
    return GithubWatchedRepository.objects.create(
        workspace=connection.workspace,
        connection=connection,
        repository_id=555,
        full_name="acme/api",
        html_url="https://github.com/acme/api",
        default_branch="main",
    )


@pytest.fixture
def mappings(project, states):
    """The mapping from the feature brief: "In QA" on merge to staging, "Deployed" on merge to main."""
    rows = [
        ("opened", "", "In Review"),
        ("drafted", "", "In Progress"),
        ("merged", "staging", "In QA"),
        ("merged", "main", "Deployed"),
        ("closed", "", "Cancelled"),
    ]
    return [
        GithubStateMapping.objects.create(project=project, event=event, base_branch=branch, state=states[state])
        for event, branch, state in rows
    ]


def pull_request_payload(action="opened", number=7, title="Add sync", body="", base="main", **overrides):
    pull_request = {
        "id": 900000 + number,
        "number": number,
        "title": title,
        "body": body,
        "html_url": f"https://github.com/acme/api/pull/{number}",
        "state": "open",
        "draft": False,
        "merged": False,
        "merged_at": None,
        "closed_at": None,
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-01T10:00:00Z",
        "base": {"ref": base},
        "head": {"ref": "feature/sync"},
        "user": {"login": "octocat"},
    }
    pull_request.update(overrides)
    return {"action": action, "pull_request": pull_request, "repository": {"id": 555}}

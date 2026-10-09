# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import pytest

from plane.db.models import Issue, Project, ProjectMember, State
from plane.db.models.api import APIToken


@pytest.fixture(autouse=True)
def background_tasks():
    """Record celery work instead of queueing it."""
    with (
        patch("plane.bgtasks.issue_activities_task.issue_activity.delay") as activity,
        patch("plane.bgtasks.webhook_task.model_activity.delay") as model_activity,
    ):
        yield {"activity": activity, "model_activity": model_activity}


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Engineering", identifier="ENG", workspace=workspace)
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


@pytest.fixture
def states(project):
    rows = [("Backlog", "backlog", True), ("In Progress", "started", False), ("Done", "completed", False)]
    return {
        name: State.objects.create(project=project, name=name, group=group, default=default, color="#000000")
        for name, group, default in rows
    }


@pytest.fixture
def work_item(project, states):
    return Issue.objects.create(project=project, name="Ship custom fields", state=states["Backlog"])


@pytest.fixture
def token_client(api_client, create_user, workspace):
    """An external-API client authenticated with a workspace API token."""
    token = APIToken.objects.create(
        user=create_user, label="NovaPro", token="plane_api_novapro_test", workspace=workspace
    )
    api_client.credentials(HTTP_X_API_KEY=token.token)
    return api_client

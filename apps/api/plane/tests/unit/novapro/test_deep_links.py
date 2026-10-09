# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from django.utils import timezone

from plane.db.models import Issue, Project, User, WorkspaceMember
from plane.novapro.links import work_item_url


def locate(workspace, issue_id):
    return f"/api/workspaces/{workspace.slug}/work-items/{issue_id}/locate/"


@pytest.mark.unit
@pytest.mark.django_db
class TestWorkItemLocate:
    def test_resolves_current_identifier_after_rename(self, session_client, workspace, project, work_item):
        assert session_client.get(locate(workspace, work_item.id)).data["project_identifier"] == "ENG"
        Project.objects.filter(pk=project.pk).update(identifier="CORE")
        data = session_client.get(locate(workspace, work_item.id)).data
        assert data == {
            "id": str(work_item.id),
            "project_id": str(project.id),
            "project_identifier": "CORE",
            "sequence_id": work_item.sequence_id,
            "is_archived": False,
        }

    def test_archived(self, session_client, workspace, work_item):
        Issue.objects.filter(pk=work_item.pk).update(archived_at=timezone.now())
        assert session_client.get(locate(workspace, work_item.id)).data["is_archived"] is True

    def test_hidden_from_non_members_and_unknown_ids(self, api_client, workspace, work_item):
        outsider = User.objects.create(email="o@plane.so", username="o")
        WorkspaceMember.objects.create(workspace=workspace, member=outsider, role=15)
        api_client.force_authenticate(user=outsider)
        assert api_client.get(locate(workspace, work_item.id)).status_code == 404
        api_client.force_authenticate(user=None)

    def test_unknown_id(self, session_client, workspace, project):
        assert session_client.get(locate(workspace, "00000000-0000-0000-0000-000000000000")).status_code == 404

    def test_requires_login(self, api_client, workspace, work_item):
        assert api_client.get(locate(workspace, work_item.id)).status_code in (401, 403)


@pytest.mark.unit
def test_work_item_url(settings):
    settings.APP_BASE_URL = "https://plane.novapro.example/"
    assert work_item_url("acme", "abc") == "https://plane.novapro.example/acme/work-items/abc"

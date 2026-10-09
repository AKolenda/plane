# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.db.models import IssueCustomProperty, IssueCustomPropertyValue, ProjectMember, User


def base(workspace, project):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}"


@pytest.mark.unit
@pytest.mark.django_db
class TestCustomPropertyApi:
    def test_create_list_update_delete(self, session_client, workspace, project, work_item):
        url = f"{base(workspace, project)}/custom-properties/"
        created = session_client.post(
            url, {"name": "Severity", "property_type": "select", "options": ["Low", "High"]}, format="json"
        )
        assert created.status_code == 201, created.data
        assert created.data["key"] == "severity" and len(created.data["options"]) == 2

        assert [p["name"] for p in session_client.get(url).data] == ["Severity"]

        detail = f"{url}{created.data['id']}/"
        options = created.data["options"] + [{"label": "Critical"}]
        updated = session_client.patch(detail, {"name": "Impact", "options": options}, format="json")
        assert updated.status_code == 200 and updated.data["name"] == "Impact"
        assert updated.data["options"][0]["id"] == created.data["options"][0]["id"]

        assert session_client.patch(detail, {"property_type": "text"}, format="json").status_code == 400

        session_client.patch(
            f"{base(workspace, project)}/issues/{work_item.id}/custom-property-values/",
            {"impact": "Low"},
            format="json",
        )
        assert session_client.delete(detail).status_code == 204
        assert not IssueCustomProperty.objects.exists() and not IssueCustomPropertyValue.objects.exists()

    def test_duplicate_name_conflicts(self, session_client, workspace, project):
        url = f"{base(workspace, project)}/custom-properties/"
        session_client.post(url, {"name": "Customer", "property_type": "text"}, format="json")
        assert session_client.post(url, {"name": "Customer", "property_type": "text"}, format="json").status_code == 409

    def test_select_needs_options(self, session_client, workspace, project):
        response = session_client.post(
            f"{base(workspace, project)}/custom-properties/",
            {"name": "Severity", "property_type": "select"},
            format="json",
        )
        assert response.status_code == 400

    def test_values_per_issue_and_per_project(self, session_client, workspace, project, work_item):
        url = f"{base(workspace, project)}/custom-properties/"
        points = session_client.post(url, {"name": "Points", "property_type": "number"}, format="json").data
        values_url = f"{base(workspace, project)}/issues/{work_item.id}/custom-property-values/"

        response = session_client.patch(values_url, {"points": 8}, format="json")
        assert response.status_code == 200 and response.data == {points["id"]: 8}
        assert session_client.get(values_url).data == {points["id"]: 8}

        bulk = session_client.get(f"{base(workspace, project)}/custom-property-values/")
        assert bulk.data == {str(work_item.id): {points["id"]: 8}}

        bad = session_client.patch(values_url, {"points": "eight"}, format="json")
        assert bad.status_code == 400 and "Points" in bad.data["detail"]

    def test_only_admins_define_properties_and_guests_cannot_write_values(
        self, api_client, workspace, project, work_item
    ):
        from plane.db.models import WorkspaceMember

        guest = User.objects.create(email="guest@plane.so", username="guest")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=project, member=guest, role=5)
        api_client.force_authenticate(user=guest)

        url = f"{base(workspace, project)}/custom-properties/"
        assert api_client.get(url).status_code == 200
        assert api_client.post(url, {"name": "X", "property_type": "text"}, format="json").status_code == 403
        values_url = f"{base(workspace, project)}/issues/{work_item.id}/custom-property-values/"
        assert api_client.patch(values_url, {}, format="json").status_code == 403


@pytest.mark.unit
@pytest.mark.django_db
class TestExternalCustomPropertyApi:
    def test_read_and_write_by_key_with_api_key(self, token_client, workspace, project, work_item, create_user):
        IssueCustomProperty.objects.create(
            project=project,
            name="Severity",
            key="severity",
            property_type="select",
            options=[{"id": "a", "label": "Low"}, {"id": "b", "label": "High"}],
        )
        IssueCustomProperty.objects.create(project=project, name="Owner", key="owner", property_type="user")
        base_url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}"

        listed = token_client.get(f"{base_url}/custom-properties/")
        assert listed.status_code == 200 and {p["key"] for p in listed.data} == {"severity", "owner"}

        url = f"{base_url}/work-items/{work_item.id}/custom-properties/"
        written = token_client.patch(url, {"severity": "high", "owner": create_user.email}, format="json")
        assert written.status_code == 200, written.data
        assert written.data["severity"] == "High"
        assert written.data["owner"]["email"] == create_user.email
        assert token_client.get(url).data == written.data

        bad = token_client.patch(url, {"severity": "Critical"}, format="json")
        assert bad.status_code == 400 and "unknown option" in bad.data["error"]

    def test_requires_api_key(self, api_client, workspace, project):
        response = api_client.get(f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/custom-properties/")
        assert response.status_code == 401

    def test_unknown_work_item_is_404(self, token_client, workspace, project):
        url = (
            f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/"
            "00000000-0000-0000-0000-000000000000/custom-properties/"
        )
        assert token_client.get(url).status_code == 404

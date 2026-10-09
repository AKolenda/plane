# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueCustomProperty,
    IssueLabel,
    IssueLink,
    Label,
    Project,
    ProjectMember,
    User,
)
from plane.novapro.external_import import text_to_html


def url(workspace):
    return f"/api/v1/workspaces/{workspace.slug}/work-items/import/"


def payload(**overrides):
    item = {
        "project": "ENG",
        "external_source": "transcript",
        "external_id": "call-2026-10-08#1",
        "title": "Send the revised quote to Acme",
        "description": "From the Tuesday call.\n\n- confirm pricing\n- attach SOW",
        "source_url": "https://nas.local/transcripts/2026-10-08-acme.txt",
        "labels": ["call", "follow-up"],
    }
    item.update(overrides)
    return item


@pytest.mark.unit
class TestTextToHtml:
    def test_paragraphs_and_bullets(self):
        html = text_to_html("Hello <b>there</b>\nsecond line\n\n- one\n2) two")
        assert (
            html
            == "<p>Hello &lt;b&gt;there&lt;/b&gt;<br>second line</p><ul><li><p>one</p></li><li><p>two</p></li></ul>"
        )

    def test_empty(self):
        assert text_to_html("  ") == "<p></p>"


@pytest.mark.unit
@pytest.mark.django_db
class TestExternalImport:
    def test_create_then_reimport_updates(
        self, token_client, workspace, project, states, create_user, background_tasks
    ):
        first = token_client.post(url(workspace), payload(assignee=create_user.email), format="json")
        assert first.status_code == 201, first.data
        assert first.data["created"] is True and first.data["identifier"].startswith("ENG-")
        assert first.data["url"].endswith(f"/{workspace.slug}/work-items/{first.data['id']}")

        issue = Issue.objects.get(pk=first.data["id"])
        assert issue.external_source == "transcript" and issue.external_id == "call-2026-10-08#1"
        assert "<li><p>confirm pricing</p></li>" in issue.description_html
        assert set(IssueLabel.objects.filter(issue=issue).values_list("label__name", flat=True)) == {
            "call",
            "follow-up",
        }
        assert IssueAssignee.objects.filter(issue=issue, assignee=create_user).exists()
        assert IssueLink.objects.filter(issue=issue, url=payload()["source_url"]).count() == 1
        assert background_tasks["model_activity"].call_args.kwargs["current_instance"] is None

        again = token_client.post(
            url(workspace), payload(title="Send the revised quote to Acme by Friday", labels=["Call"]), format="json"
        )
        assert again.status_code == 200 and again.data["id"] == first.data["id"] and again.data["created"] is False
        issue.refresh_from_db()
        assert issue.name == "Send the revised quote to Acme by Friday"
        assert Issue.objects.filter(external_source="transcript").count() == 1
        # Labels match case-insensitively, the link is not duplicated, and the assignee stays
        assert Label.objects.filter(project=project, name__iexact="call").count() == 1
        assert IssueLink.objects.filter(issue=issue).count() == 1
        assert IssueAssignee.objects.filter(issue=issue).count() == 1
        assert background_tasks["model_activity"].call_args.kwargs["requested_data"] == {
            "name": "Send the revised quote to Acme by Friday"
        }

    def test_unchanged_reimport_records_nothing(self, token_client, workspace, project, states, background_tasks):
        token_client.post(url(workspace), payload(), format="json")
        background_tasks["activity"].reset_mock()
        assert token_client.post(url(workspace), payload(), format="json").status_code == 200
        background_tasks["activity"].assert_not_called()

    def test_reimport_keeps_labels_and_assignees_added_in_plane(self, token_client, workspace, project, states):
        created = token_client.post(url(workspace), payload(labels=["call"]), format="json").data
        issue = Issue.objects.get(pk=created["id"])
        manual = Label.objects.create(project=project, name="urgent")
        IssueLabel.objects.create(issue=issue, label=manual, project=project)

        token_client.post(url(workspace), payload(labels=["call"]), format="json")

        assert IssueLabel.objects.filter(issue=issue, label=manual).exists()

    def test_reimport_updates_in_the_original_project(self, token_client, workspace, project, states, create_user):
        other = Project.objects.create(name="Web", identifier="WEB", workspace=workspace)
        ProjectMember.objects.create(project=other, member=create_user, role=20)
        created = token_client.post(url(workspace), payload(), format="json").data
        moved = token_client.post(url(workspace), payload(project="WEB"), format="json")
        assert moved.status_code == 200 and moved.data["id"] == created["id"]
        assert moved.data["project_id"] == str(project.id)

    def test_project_by_id_and_custom_properties(self, token_client, workspace, project, states):
        IssueCustomProperty.objects.create(project=project, name="Customer", key="customer", property_type="text")
        response = token_client.post(
            url(workspace), payload(project=str(project.id), custom_properties={"customer": "Acme"}), format="json"
        )
        assert response.status_code == 201, response.data
        values = token_client.get(
            f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-items/{response.data['id']}/custom-properties/"
        ).data
        assert values == {"customer": "Acme"}

    @pytest.mark.parametrize(
        "overrides,message",
        [
            ({"title": ""}, "title is required"),
            ({"external_id": None}, "external_id is required"),
            ({"project": "NOPE"}, "not found"),
            ({"assignee": "stranger@plane.so"}, "not a member"),
            ({"assignee": "not-an-id"}, "email or user id"),
            ({"source_url": "javascript:alert(1)"}, "http(s)"),
            ({"labels": "call"}, "labels must be a list"),
            ({"title": "x" * 300}, "at most 255"),
        ],
    )
    def test_validation(self, token_client, workspace, project, states, overrides, message):
        response = token_client.post(url(workspace), payload(**overrides), format="json")
        assert response.status_code == 400 and message in response.data["error"]
        assert not Issue.objects.exists()

    def test_bad_custom_property_rolls_back_the_import(self, token_client, workspace, project, states):
        IssueCustomProperty.objects.create(project=project, name="Points", key="points", property_type="number")
        response = token_client.post(url(workspace), payload(custom_properties={"points": "many"}), format="json")
        assert response.status_code == 400
        assert not Issue.objects.exists()

    def test_batch(self, token_client, workspace, project, states):
        response = token_client.post(
            url(workspace),
            [payload(external_id="a"), payload(external_id="b", title=""), payload(external_id="a", title="Renamed")],
            format="json",
        )
        assert response.status_code == 207
        assert response.data[0]["created"] is True
        assert "title is required" in response.data[1]["error"]
        assert response.data[2]["created"] is False and response.data[2]["id"] == response.data[0]["id"]

    def test_guests_cannot_import(self, api_client, workspace, project, states):
        from plane.db.models import WorkspaceMember
        from plane.db.models.api import APIToken

        guest = User.objects.create(email="guest@plane.so", username="guest")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        token = APIToken.objects.create(user=guest, label="g", token="plane_api_guest", workspace=workspace)
        api_client.credentials(HTTP_X_API_KEY=token.token)
        assert api_client.post(url(workspace), payload(), format="json").status_code == 403

    def test_requires_api_key(self, api_client, workspace):
        assert api_client.post(url(workspace), payload(), format="json").status_code == 401


@pytest.mark.unit
@pytest.mark.django_db(transaction=True)
def test_concurrent_imports_of_one_item_create_one_work_item(workspace, project, states, create_user):
    """Issue has no unique constraint on the external columns; the advisory lock must serialize."""
    import threading

    from django.db import connection

    from plane.novapro.external_import import import_work_item

    barrier = threading.Barrier(4)
    results, errors = [], []

    def run():
        try:
            barrier.wait()
            results.append(import_work_item(workspace, payload(), create_user)[1])
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(results) == [False, False, False, True]
    assert Issue.objects.filter(external_source="transcript", external_id=payload()["external_id"]).count() == 1

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch

import pytest

from plane.db.models import GithubSyncedIssue, Issue, IssueLabel, IssueLink, Label
from plane.integrations.github.issue_sync import (
    plane_html_to_github_body,
    process_issues_event,
    push_work_item,
)

CLIENT = "plane.integrations.github.issue_sync.github_client"


def github_issue(number=42, title="Crash on save", body="It **crashes**", state="open", labels=("plane",)):
    return {
        "id": 700000 + number,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "html_url": f"https://github.com/acme/api/issues/{number}",
        "labels": [{"name": name} for name in labels],
    }


def issues_payload(action, **issue):
    return {"action": action, "issue": github_issue(**issue), "repository": {"id": 555}}


@pytest.fixture
def sync_repository(repository, project, states):
    repository.project = project
    repository.issue_sync_mode = "github_to_plane"
    repository.save()
    return repository


@pytest.fixture
def render():
    with patch(f"{CLIENT}.render_markdown", side_effect=lambda connection, repo, text: f"<p>{text}</p>") as mock:
        yield mock


@pytest.mark.unit
@pytest.mark.django_db
class TestGithubToPlane:
    def test_labelled_issue_is_imported(self, sync_repository, project, render, background_tasks):
        assert process_issues_event(sync_repository, issues_payload("labeled")) == "imported"

        synced = GithubSyncedIssue.objects.get(repository=sync_repository, github_issue_number=42)
        work_item = synced.issue
        assert work_item.project_id == project.id
        assert work_item.name == "Crash on save"
        assert "crashes" in work_item.description_html
        assert work_item.state.name == "Backlog"
        assert work_item.external_source == "github"
        assert IssueLink.objects.filter(issue=work_item, url="https://github.com/acme/api/issues/42").exists()
        assert background_tasks["activity"].call_args.kwargs["type"] == "issue.activity.created"

    def test_label_match_is_case_insensitive(self, sync_repository, render):
        assert process_issues_event(sync_repository, issues_payload("opened", labels=("Plane",))) == "imported"

    def test_unlabelled_issue_is_ignored(self, sync_repository, render):
        assert process_issues_event(sync_repository, issues_payload("opened", labels=("bug",))) == "ignored"
        assert not GithubSyncedIssue.objects.exists()

    def test_disabled_sync_ignores_everything(self, repository, render):
        assert process_issues_event(repository, issues_payload("labeled")) == "sync disabled"

    def test_pull_requests_in_issue_events_are_ignored(self, sync_repository, render):
        payload = issues_payload("labeled")
        payload["issue"]["pull_request"] = {"url": "https://api.github.com/repos/acme/api/pulls/42"}
        assert process_issues_event(sync_repository, payload) == "ignored"

    def test_closed_issue_imports_into_completed_state(self, sync_repository, render):
        process_issues_event(sync_repository, issues_payload("labeled", state="closed"))
        assert GithubSyncedIssue.objects.get().issue.state.name == "Deployed"

    def test_configured_open_state_is_used(self, sync_repository, states, render):
        sync_repository.open_state = states["In Progress"]
        sync_repository.save()
        process_issues_event(sync_repository, issues_payload("labeled"))
        assert GithubSyncedIssue.objects.get().issue.state.name == "In Progress"

    def test_edits_update_only_changed_fields(self, sync_repository, render):
        process_issues_event(sync_repository, issues_payload("labeled"))
        work_item = GithubSyncedIssue.objects.get().issue
        Issue.objects.filter(pk=work_item.pk).update(description_html="<p>edited in Plane</p>")

        result = process_issues_event(sync_repository, issues_payload("edited", title="Crash on save (Windows)"))

        work_item.refresh_from_db()
        assert result == "updated"
        assert work_item.name == "Crash on save (Windows)"
        # The body did not change on GitHub, so the Plane edit survives
        assert work_item.description_html == "<p>edited in Plane</p>"

    def test_close_and_reopen_follow_github(self, sync_repository, render):
        process_issues_event(sync_repository, issues_payload("labeled"))
        process_issues_event(sync_repository, issues_payload("closed", state="closed"))
        assert GithubSyncedIssue.objects.get().issue.state.name == "Deployed"
        process_issues_event(sync_repository, issues_payload("reopened", state="open"))
        assert GithubSyncedIssue.objects.get().issue.state.name == "Backlog"

    def test_repeated_delivery_is_a_no_op(self, sync_repository, render):
        process_issues_event(sync_repository, issues_payload("labeled"))
        assert process_issues_event(sync_repository, issues_payload("edited")) == "unchanged"

    def test_concurrent_import_does_not_duplicate(self, sync_repository, render):
        process_issues_event(sync_repository, issues_payload("opened"))
        assert process_issues_event(sync_repository, issues_payload("labeled")) == "unchanged"
        assert GithubSyncedIssue.objects.count() == 1


@pytest.fixture
def bidirectional_repository(sync_repository):
    sync_repository.issue_sync_mode = "bidirectional"
    sync_repository.save()
    return sync_repository


def github_response(number=42, title="t", body="", state="open"):
    return {
        "id": 700000 + number,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "html_url": f"https://github.com/acme/api/issues/{number}",
    }


@pytest.mark.unit
@pytest.mark.django_db
class TestPlaneToGithub:
    def _label(self, work_item, name="github"):
        label = Label.objects.create(project=work_item.project, name=name)
        IssueLabel.objects.create(issue=work_item, label=label, project=work_item.project)

    def test_labelled_work_item_is_exported(self, bidirectional_repository, work_item):
        self._label(work_item)
        with patch(f"{CLIENT}.create_issue", return_value=github_response(title=work_item.name)) as create:
            assert push_work_item(work_item.id) == ["exported"]

        create.assert_called_once()
        assert create.call_args.kwargs["title"] == work_item.name
        synced = GithubSyncedIssue.objects.get(issue=work_item)
        assert synced.github_issue_number == 42
        assert IssueLink.objects.filter(issue=work_item, url=synced.html_url).exists()

    def test_unlabelled_work_item_is_not_exported(self, bidirectional_repository, work_item):
        with patch(f"{CLIENT}.create_issue") as create:
            assert push_work_item(work_item.id) == []
        create.assert_not_called()

    def test_one_way_sync_never_writes_to_github(self, sync_repository, work_item):
        self._label(work_item)
        with patch(f"{CLIENT}.create_issue") as create:
            assert push_work_item(work_item.id) == []
        create.assert_not_called()

    def test_only_changed_fields_are_sent(self, bidirectional_repository, work_item, states):
        self._label(work_item)
        with patch(f"{CLIENT}.create_issue", return_value=github_response(title=work_item.name)):
            push_work_item(work_item.id)

        work_item.state = states["Deployed"]
        work_item.save()
        with patch(f"{CLIENT}.update_issue", return_value=github_response(state="closed")) as update:
            assert push_work_item(work_item.id) == ["updated"]
        assert update.call_args.kwargs == {"state": "closed", "state_reason": "completed"}

        work_item.name = "Renamed"
        work_item.save()
        with patch(f"{CLIENT}.update_issue", return_value=github_response(title="Renamed", state="closed")) as update:
            push_work_item(work_item.id)
        assert update.call_args.kwargs == {"title": "Renamed"}

    def test_cancelled_state_closes_as_not_planned(self, bidirectional_repository, work_item, states):
        self._label(work_item)
        with patch(f"{CLIENT}.create_issue", return_value=github_response()):
            push_work_item(work_item.id)
        work_item.state = states["Cancelled"]
        work_item.save()
        with patch(f"{CLIENT}.update_issue", return_value=github_response(state="closed")) as update:
            push_work_item(work_item.id)
        assert update.call_args.kwargs["state_reason"] == "not_planned"

    def test_unchanged_work_item_makes_no_api_call(self, bidirectional_repository, work_item):
        self._label(work_item)
        with patch(f"{CLIENT}.create_issue", return_value=github_response(title=work_item.name)):
            push_work_item(work_item.id)
        with patch(f"{CLIENT}.update_issue") as update:
            assert push_work_item(work_item.id) == ["unchanged"]
        update.assert_not_called()

    def test_github_echo_of_plane_change_is_ignored(self, bidirectional_repository, work_item, render):
        self._label(work_item)
        with patch(f"{CLIENT}.create_issue", return_value=github_response(title=work_item.name)):
            push_work_item(work_item.id)
        work_item.name = "Renamed in Plane"
        work_item.save()
        with patch(f"{CLIENT}.update_issue", return_value=github_response(title="Renamed in Plane")):
            push_work_item(work_item.id)

        echo = {"action": "edited", "issue": {**github_response(title="Renamed in Plane"), "labels": []}}
        assert process_issues_event(bidirectional_repository, echo) == "unchanged"

    def test_imported_issue_is_not_pushed_back(self, bidirectional_repository, render):
        process_issues_event(bidirectional_repository, issues_payload("labeled"))
        work_item = GithubSyncedIssue.objects.get().issue
        with patch(f"{CLIENT}.update_issue") as update:
            assert push_work_item(work_item.id) == ["unchanged"]
        update.assert_not_called()


@pytest.mark.unit
class TestPlaneHtmlToGithub:
    def test_editor_markup_is_stripped(self):
        html = (
            '<p class="editor-paragraph-block">Hi <strong>there</strong>'
            '<mention-component id="x"></mention-component></p>'
        )
        assert plane_html_to_github_body(html) == "<p>Hi <strong>there</strong></p>"

    def test_empty_description(self):
        assert plane_html_to_github_body("<p></p>") == ""

    def test_scripts_are_removed(self):
        assert "script" not in plane_html_to_github_body("<p>x</p><script>alert(1)</script>")

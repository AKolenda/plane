# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.db.models import GithubPullRequest, GithubPullRequestIssue, Issue, Project, Workspace
from plane.integrations.github.linking import (
    WorkItemReference,
    parse_work_item_references,
    resolve_work_items,
    sync_pull_request_links,
)


@pytest.mark.unit
class TestParseWorkItemReferences:
    def test_bracketed_reference_in_title(self):
        assert parse_work_item_references("[ENG-123] Add GitHub sync") == [WorkItemReference("ENG", 123)]

    def test_bare_reference_does_not_link(self):
        assert parse_work_item_references("Fixes ENG-123 and see ENG-9") == []

    def test_title_and_description_are_both_scanned_in_order(self):
        refs = parse_work_item_references("[ENG-2] Title", "Also closes [WEB-10] and [ENG-1].")
        assert refs == [WorkItemReference("ENG", 2), WorkItemReference("WEB", 10), WorkItemReference("ENG", 1)]

    def test_duplicates_collapse_and_identifier_is_upper_cased(self):
        refs = parse_work_item_references("[eng-5] retry", "[ENG-5] again [ Eng-5 ]")
        assert refs == [WorkItemReference("ENG", 5)]

    @pytest.mark.parametrize(
        "text",
        ["[ENG-]", "[-12]", "[ENG 12]", "[ENG-12a]", "[ENG--12]", "[TOOLONGIDENTIFIER-1]", "(ENG-12)", ""],
    )
    def test_malformed_references_are_ignored(self, text):
        assert parse_work_item_references(text) == []

    def test_missing_texts_are_ignored(self):
        assert parse_work_item_references(None, None) == []

    def test_adjacent_references(self):
        assert parse_work_item_references("[ENG-1][ENG-2]") == [
            WorkItemReference("ENG", 1),
            WorkItemReference("ENG", 2),
        ]


@pytest.mark.unit
@pytest.mark.django_db
class TestResolveAndSyncLinks:
    def test_resolves_items_across_projects_in_the_workspace(self, workspace, project, work_item):
        other_project = Project.objects.create(name="Web", identifier="WEB", workspace=workspace)
        other_item = Issue.objects.create(project=other_project, name="Other")

        found = resolve_work_items(
            workspace.id,
            [WorkItemReference("ENG", work_item.sequence_id), WorkItemReference("WEB", other_item.sequence_id)],
        )
        assert {item.id for item in found} == {work_item.id, other_item.id}

    def test_unknown_and_other_workspace_references_are_skipped(self, workspace, project, work_item, create_user):
        other_workspace = Workspace.objects.create(name="Other", slug="other-ws", owner=create_user)
        other_project = Project.objects.create(name="Eng", identifier="ENG", workspace=other_workspace)
        Issue.objects.create(project=other_project, name="Elsewhere")

        found = resolve_work_items(
            workspace.id, [WorkItemReference("ENG", work_item.sequence_id), WorkItemReference("ENG", 999)]
        )
        assert [item.id for item in found] == [work_item.id]

    def test_sync_adds_keeps_and_removes_links(self, workspace, project, work_item, repository):
        second = Issue.objects.create(project=project, name="Second")
        pull_request = GithubPullRequest.objects.create(
            workspace=workspace, repository=repository, github_id=1, number=1, title="t", html_url="https://x.test"
        )

        added, kept = sync_pull_request_links(pull_request, [work_item])
        assert [i.id for i in added] == [work_item.id] and kept == []

        added, kept = sync_pull_request_links(pull_request, [work_item, second])
        assert [i.id for i in added] == [second.id] and [i.id for i in kept] == [work_item.id]

        sync_pull_request_links(pull_request, [second])
        linked = GithubPullRequestIssue.objects.filter(pull_request=pull_request).values_list("issue_id", flat=True)
        assert set(linked) == {second.id}

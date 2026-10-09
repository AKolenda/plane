# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from types import SimpleNamespace

import pytest

from plane.db.models import (
    GithubPullRequest,
    GithubPullRequestIssue,
    GithubStateMapping,
    Issue,
    Project,
    State,
    User,
)
from plane.integrations.github.pull_requests import process_pull_request_event
from plane.integrations.github.status import (
    branch_matches,
    classify_pull_request_event,
    current_pull_request_event,
    select_state_mapping,
)

from .conftest import pull_request_payload


@pytest.mark.unit
class TestClassifyPullRequestEvent:
    @pytest.mark.parametrize(
        "event_name,action,pr,review_state,expected",
        [
            ("pull_request", "opened", {"draft": False}, None, "opened"),
            ("pull_request", "opened", {"draft": True}, None, "drafted"),
            ("pull_request", "reopened", {"draft": False}, None, "opened"),
            ("pull_request", "converted_to_draft", {"draft": True}, None, "drafted"),
            ("pull_request", "ready_for_review", {}, None, "ready_for_review"),
            ("pull_request", "review_requested", {}, None, "review_requested"),
            ("pull_request", "closed", {"merged": True}, None, "merged"),
            ("pull_request", "closed", {"merged": False}, None, "closed"),
            ("pull_request", "edited", {}, None, None),
            ("pull_request", "synchronize", {}, None, None),
            ("pull_request", "labeled", {}, None, None),
            ("pull_request_review", "submitted", {}, "approved", "approved"),
            ("pull_request_review", "submitted", {}, "APPROVED", "approved"),
            ("pull_request_review", "submitted", {}, "changes_requested", None),
            ("pull_request_review", "dismissed", {}, "approved", None),
            ("issues", "opened", {}, None, None),
        ],
    )
    def test_actions(self, event_name, action, pr, review_state, expected):
        payload = {"action": action, "pull_request": pr}
        if review_state:
            payload["review"] = {"state": review_state}
        assert classify_pull_request_event(event_name, payload) == expected

    @pytest.mark.parametrize(
        "pr,expected",
        [
            ({"state": "closed", "merged": True}, "merged"),
            ({"state": "closed", "merged": False}, "closed"),
            ({"state": "open", "draft": True}, "drafted"),
            ({"state": "open", "draft": False}, "opened"),
        ],
    )
    def test_current_event(self, pr, expected):
        assert current_pull_request_event(pr) == expected


def mapping(event, base_branch, name):
    return SimpleNamespace(event=event, base_branch=base_branch, name=name)


@pytest.mark.unit
class TestSelectStateMapping:
    MAPPINGS = [
        mapping("merged", "", "Done"),
        mapping("merged", "release/*", "Releasing"),
        mapping("merged", "release/2026-*", "Release 2026"),
        mapping("merged", "staging", "In QA"),
        mapping("merged", "main", "Deployed"),
        mapping("opened", "", "In Review"),
    ]

    @pytest.mark.parametrize(
        "event,branch,expected",
        [
            ("merged", "main", "Deployed"),
            ("merged", "staging", "In QA"),
            ("merged", "develop", "Done"),
            ("merged", "release/1.2", "Releasing"),
            ("merged", "release/2026-10", "Release 2026"),
            ("opened", "main", "In Review"),
            ("closed", "main", None),
        ],
    )
    def test_most_specific_mapping_wins(self, event, branch, expected):
        selected = select_state_mapping(self.MAPPINGS, event, branch)
        assert (selected.name if selected else None) == expected

    def test_exact_branch_beats_matching_glob(self):
        mappings = [mapping("merged", "ma*", "Glob"), mapping("merged", "main", "Exact")]
        assert select_state_mapping(mappings, "merged", "main").name == "Exact"

    @pytest.mark.parametrize(
        "pattern,branch,expected",
        [("", "anything", True), ("main", "main", True), ("main", "main2", False), ("hotfix/*", "hotfix/x", True)],
    )
    def test_branch_matches(self, pattern, branch, expected):
        assert branch_matches(pattern, branch) is expected


@pytest.mark.unit
@pytest.mark.django_db
class TestPullRequestStateUpdates:
    def _state_of(self, work_item):
        return Issue.objects.get(pk=work_item.pk).state.name

    def test_opened_pull_request_links_and_moves_work_item(
        self, repository, work_item, mappings, states, background_tasks
    ):
        payload = pull_request_payload(title=f"[ENG-{work_item.sequence_id}] Add sync")

        result = process_pull_request_event(repository, "pull_request", payload)

        assert result["linked"] == [work_item.id] and result["moved"] == [work_item.id]
        assert self._state_of(work_item) == "In Review"
        pull_request = GithubPullRequest.objects.get(repository=repository, number=7)
        assert pull_request.state == "open" and pull_request.last_event == "opened"
        # The change is recorded as an activity authored by the workspace's GitHub bot
        call = background_tasks["activity"].call_args.kwargs
        assert call["type"] == "issue.activity.updated" and call["issue_id"] == str(work_item.id)
        assert json.loads(call["requested_data"]) == {"state_id": str(states["In Review"].id)}
        actor = User.objects.get(pk=call["actor_id"])
        assert actor.is_bot and actor.bot_type == "GITHUB"

    def test_reference_in_description_links(self, repository, work_item, mappings):
        payload = pull_request_payload(body=f"Implements [ENG-{work_item.sequence_id}]")
        process_pull_request_event(repository, "pull_request", payload)
        assert GithubPullRequestIssue.objects.filter(issue=work_item).exists()

    @pytest.mark.parametrize("base,expected", [("staging", "In QA"), ("main", "Deployed")])
    def test_merge_target_branch_picks_the_state(self, repository, work_item, mappings, base, expected):
        title = f"[ENG-{work_item.sequence_id}] Add sync"
        process_pull_request_event(repository, "pull_request", pull_request_payload(title=title, base=base))
        merged = pull_request_payload(
            action="closed",
            title=title,
            base=base,
            state="closed",
            merged=True,
            merged_at="2026-10-02T10:00:00Z",
            closed_at="2026-10-02T10:00:00Z",
            updated_at="2026-10-02T10:00:00Z",
        )

        process_pull_request_event(repository, "pull_request", merged)

        assert self._state_of(work_item) == expected
        assert GithubPullRequest.objects.get(repository=repository, number=7).state == "merged"

    def test_closed_without_merge(self, repository, work_item, mappings):
        title = f"[ENG-{work_item.sequence_id}] Abandon"
        closed = pull_request_payload(action="closed", title=title, state="closed", updated_at="2026-10-03T00:00:00Z")
        process_pull_request_event(repository, "pull_request", closed)
        assert self._state_of(work_item) == "Cancelled"

    def test_draft_then_ready(self, repository, work_item, mappings, states):
        title = f"[ENG-{work_item.sequence_id}] WIP"
        process_pull_request_event(repository, "pull_request", pull_request_payload(title=title, draft=True))
        assert self._state_of(work_item) == "In Progress"
        assert GithubPullRequest.objects.get(number=7).state == "draft"

        # No mapping for ready_for_review: the work item stays put but the PR state updates
        ready = pull_request_payload(action="ready_for_review", title=title, updated_at="2026-10-01T11:00:00Z")
        result = process_pull_request_event(repository, "pull_request", ready)
        assert result["moved"] == [] and self._state_of(work_item) == "In Progress"
        assert GithubPullRequest.objects.get(number=7).state == "open"

    def test_approved_review(self, repository, work_item, project, states):
        GithubStateMapping.objects.create(project=project, event="approved", state=states["In QA"])
        payload = pull_request_payload(action="submitted", title=f"[ENG-{work_item.sequence_id}] x")
        payload["review"] = {"state": "approved"}
        process_pull_request_event(repository, "pull_request_review", payload)
        assert self._state_of(work_item) == "In QA"

    def test_without_mapping_only_links(self, repository, work_item):
        result = process_pull_request_event(
            repository, "pull_request", pull_request_payload(title=f"[ENG-{work_item.sequence_id}] x")
        )
        assert result["linked"] == [work_item.id] and result["moved"] == []
        assert self._state_of(work_item) == "Backlog"

    def test_edit_adding_reference_applies_current_state(self, repository, work_item, mappings):
        process_pull_request_event(repository, "pull_request", pull_request_payload(title="No reference yet"))
        assert self._state_of(work_item) == "Backlog"

        edited = pull_request_payload(
            action="edited", title=f"[ENG-{work_item.sequence_id}] Now linked", updated_at="2026-10-01T12:00:00Z"
        )
        result = process_pull_request_event(repository, "pull_request", edited)

        assert result["added"] == [work_item.id]
        assert self._state_of(work_item) == "In Review"

    def test_edit_on_already_linked_item_does_not_move_it_again(self, repository, work_item, mappings, states):
        title = f"[ENG-{work_item.sequence_id}] x"
        process_pull_request_event(repository, "pull_request", pull_request_payload(title=title))
        # Someone moves the work item by hand; a later PR edit must not override them
        Issue.objects.filter(pk=work_item.pk).update(state=states["In Progress"])
        edited = pull_request_payload(action="edited", title=title + " typo", updated_at="2026-10-01T12:00:00Z")
        process_pull_request_event(repository, "pull_request", edited)
        assert self._state_of(work_item) == "In Progress"

    def test_edit_removing_reference_unlinks(self, repository, work_item, mappings):
        process_pull_request_event(
            repository, "pull_request", pull_request_payload(title=f"[ENG-{work_item.sequence_id}] x")
        )
        edited = pull_request_payload(action="edited", title="Unrelated", updated_at="2026-10-01T12:00:00Z")
        result = process_pull_request_event(repository, "pull_request", edited)
        assert result["linked"] == []
        assert not GithubPullRequestIssue.objects.filter(issue=work_item).exists()

    def test_stale_delivery_is_ignored(self, repository, work_item, mappings):
        title = f"[ENG-{work_item.sequence_id}] x"
        merged = pull_request_payload(
            action="closed", title=title, state="closed", merged=True, updated_at="2026-10-05T00:00:00Z"
        )
        process_pull_request_event(repository, "pull_request", merged)
        assert self._state_of(work_item) == "Deployed"

        late_open = pull_request_payload(title=title, updated_at="2026-10-01T00:00:00Z")
        result = process_pull_request_event(repository, "pull_request", late_open)

        assert result["ignored"] == "stale delivery"
        assert self._state_of(work_item) == "Deployed"
        assert GithubPullRequest.objects.get(number=7).state == "merged"

    def test_state_from_another_project_is_never_applied(self, repository, work_item, workspace, mappings):
        other_project = Project.objects.create(name="Web", identifier="WEB", workspace=workspace)
        other_item = Issue.objects.create(project=other_project, name="Web item")
        foreign_state = State.objects.create(project=other_project, name="Shipped", group="completed", color="#000")
        GithubStateMapping.objects.create(project=other_project, event="opened", state=foreign_state)
        title = f"[ENG-{work_item.sequence_id}][WEB-{other_item.sequence_id}] cross-project"

        process_pull_request_event(repository, "pull_request", pull_request_payload(title=title))

        assert self._state_of(work_item) == "In Review"
        assert Issue.objects.get(pk=other_item.pk).state_id == foreign_state.id

    def test_work_item_already_in_target_state_is_not_touched(
        self, repository, work_item, mappings, states, background_tasks
    ):
        Issue.objects.filter(pk=work_item.pk).update(state=states["In Review"])
        result = process_pull_request_event(
            repository, "pull_request", pull_request_payload(title=f"[ENG-{work_item.sequence_id}] x")
        )
        assert result["moved"] == []
        background_tasks["activity"].assert_not_called()

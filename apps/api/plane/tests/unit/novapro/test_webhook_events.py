# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from plane.bgtasks.webhook_task import webhook_send_task
from plane.db.models import Webhook
from plane.novapro.webhook_events import classify_event


@pytest.mark.unit
class TestClassifyEvent:
    @pytest.mark.parametrize(
        "event,action,activity,expected",
        [
            ("issue", "created", {"field": None}, ("issue.created", None)),
            ("issue", "updated", {"field": "name"}, ("issue.updated", None)),
            ("issue", "deleted", None, ("issue.deleted", None)),
            (
                "issue",
                "updated",
                {"field": "state_id", "old_value": "s1", "new_value": "s2"},
                ("issue.state_changed", {"from": "s1", "to": "s2"}),
            ),
            (
                "issue",
                "updated",
                {"field": "state", "old_value": None, "new_value": {"id": "s2"}},
                ("issue.state_changed", {"from": None, "to": "s2"}),
            ),
            (
                "issue",
                "updated",
                {"field": "assignee_ids", "old_value": ["a", "b"], "new_value": ["b", "c"]},
                ("issue.assigned", {"added": ["c"], "removed": ["a"]}),
            ),
            (
                "issue",
                "updated",
                {"field": "assignees", "old_value": [], "new_value": [{"id": "u1"}]},
                ("issue.assigned", {"added": ["u1"], "removed": []}),
            ),
            ("project", "created", {"field": None}, ("project.created", None)),
            ("issue_comment", "updated", {"field": "comment_html"}, ("issue_comment.updated", None)),
        ],
    )
    def test_event_types(self, event, action, activity, expected):
        assert classify_event(event, action, activity) == expected


@pytest.mark.unit
@pytest.mark.django_db
class TestWebhookDelivery:
    def test_state_change_delivery_is_typed_and_signed(self, workspace):
        webhook = Webhook.objects.create(workspace=workspace, url="https://hooks.example.com/plane", issue=True)
        response = MagicMock(status_code=200, headers={}, text="ok")
        with patch("plane.bgtasks.webhook_task.pinned_fetch", return_value=response) as fetch:
            webhook_send_task(
                webhook_id=str(webhook.id),
                slug=workspace.slug,
                event="issue",
                event_data={"id": "i1"},
                action="updated",
                current_site="https://plane.example.com",
                activity={"field": "state_id", "old_value": "s1", "new_value": "s2"},
            )

        kwargs = fetch.call_args.kwargs
        payload, headers = kwargs["json"], kwargs["headers"]
        assert payload["event"] == "issue" and payload["action"] == "updated"
        assert payload["event_type"] == "issue.state_changed"
        assert payload["changes"] == {"from": "s1", "to": "s2"}
        assert headers["X-Plane-Event-Type"] == "issue.state_changed"
        # Receivers verify the HMAC over the JSON body they receive
        expected = hmac.new(webhook.secret_key.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()
        assert headers["X-Plane-Signature"] == expected

    def test_created_delivery_has_no_changes(self, workspace):
        webhook = Webhook.objects.create(workspace=workspace, url="https://hooks.example.com/plane", issue=True)
        response = MagicMock(status_code=200, headers={}, text="ok")
        with patch("plane.bgtasks.webhook_task.pinned_fetch", return_value=response) as fetch:
            webhook_send_task(
                webhook_id=str(webhook.id),
                slug=workspace.slug,
                event="issue",
                event_data={"id": "i1"},
                action="created",
                current_site="https://plane.example.com",
                activity={"field": None},
            )
        payload = fetch.call_args.kwargs["json"]
        assert payload["event_type"] == "issue.created" and "changes" not in payload


@pytest.mark.unit
@pytest.mark.django_db
def test_github_state_automation_notifies_webhooks(work_item, states, create_user, background_tasks):
    from plane.integrations.github.status import apply_state

    previous = work_item.state_id
    assert apply_state(work_item, states["In Progress"], create_user)
    call = background_tasks["model_activity"].call_args.kwargs
    assert call["requested_data"] == {"state_id": str(states["In Progress"].id)}
    assert json.loads(call["current_instance"]) == {"state_id": str(previous)}

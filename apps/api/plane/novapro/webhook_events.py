# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Specific event types for outbound webhooks.

Upstream deliveries say `event: issue, action: updated` and name the changed field in
`activity.field`. Receivers that only care about state changes or assignments would have to
decode field names that differ between the web app (`state_id`, `assignee_ids`) and the
public API (`state`, `assignees`). `event_type` does that once:

* `issue.created`, `issue.updated`, `issue.deleted`
* `issue.state_changed` with `changes = {"from": <state id>, "to": <state id>}`
* `issue.assigned` with `changes = {"added": [<user id>], "removed": [<user id>]}`
* `<event>.<action>` for every other event (`project.created`, `issue_comment.updated`, ...)
"""

STATE_FIELDS = {"state", "state_id"}
ASSIGNEE_FIELDS = {"assignees", "assignee_ids"}


def _ids(value):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    return [str(item.get("id") if isinstance(item, dict) else item) for item in value if item]


def classify_event(event, action, activity):
    """Return `(event_type, changes)` for one delivery; `changes` is None unless it adds detail."""
    activity = activity or {}
    field = activity.get("field")
    if event == "issue" and action == "updated":
        old, new = _ids(activity.get("old_value")), _ids(activity.get("new_value"))
        if field in STATE_FIELDS:
            return "issue.state_changed", {"from": old[0] if old else None, "to": new[0] if new else None}
        if field in ASSIGNEE_FIELDS:
            return "issue.assigned", {
                "added": [user for user in new if user not in old],
                "removed": [user for user in old if user not in new],
            }
    return f"{event}.{action}", None

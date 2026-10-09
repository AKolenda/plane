# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Stable, shareable links to work items."""

# Django imports
from django.conf import settings


def app_base_url():
    return (settings.APP_BASE_URL or settings.WEB_URL or "").rstrip("/")


def work_item_url(workspace_slug, issue_id):
    """A link that keeps working when the project identifier is renamed or the work item moves.

    `/<workspace>/work-items/<uuid>` resolves the work item and redirects to its page, so it
    is safe to store in notifications, digests and external systems.
    """
    return f"{app_base_url()}/{workspace_slug}/work-items/{issue_id}"


def work_item_identifier(issue):
    return f"{issue.project.identifier}-{issue.sequence_id}"

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging

# Third party imports
from celery import shared_task

# Module imports
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")


@shared_task
def process_github_webhook(connection_id, event_name, payload, delivery_id=None):
    from plane.integrations.github.webhooks import process_delivery

    try:
        result = process_delivery(connection_id, event_name, payload)
        logger.info(f"GitHub delivery {delivery_id} ({event_name}) for connection {connection_id}: {result}")
    except Exception as e:
        log_exception(e)


@shared_task
def push_work_item_to_github(work_item_id):
    from plane.integrations.github.issue_sync import push_work_item

    try:
        push_work_item(work_item_id)
    except Exception as e:
        log_exception(e)


def schedule_github_push(work_item_id, project_id):
    """Queue a Plane-to-GitHub sync when the work item's project has a bidirectional repository."""
    from plane.integrations.github.issue_sync import project_has_bidirectional_sync

    if work_item_id and project_id and project_has_bidirectional_sync(project_id):
        push_work_item_to_github.delay(str(work_item_id))

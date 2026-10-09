# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Public API (X-Api-Key) routes for NovaPro additions, mounted under /api/v1/."""

from django.urls import path

from plane.novapro.views.digest import DigestEndpoint
from plane.novapro.views.external_import import ExternalWorkItemImportEndpoint
from plane.novapro.views.external_custom_properties import (
    ExternalCustomPropertyListEndpoint,
    ExternalIssueCustomPropertyValuesEndpoint,
)

PROJECT = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path("workspaces/<str:slug>/digest/", DigestEndpoint.as_view(http_method_names=["get"]), name="digest"),
    path(
        "workspaces/<str:slug>/work-items/import/",
        ExternalWorkItemImportEndpoint.as_view(http_method_names=["post"]),
        name="external-work-item-import",
    ),
    path(
        f"{PROJECT}/custom-properties/",
        ExternalCustomPropertyListEndpoint.as_view(http_method_names=["get"]),
        name="external-custom-properties",
    ),
    path(
        f"{PROJECT}/work-items/<uuid:issue_id>/custom-properties/",
        ExternalIssueCustomPropertyValuesEndpoint.as_view(http_method_names=["get", "patch"]),
        name="external-issue-custom-properties",
    ),
]

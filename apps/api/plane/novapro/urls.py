# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Web-app (session) routes for NovaPro additions, mounted under /api/."""

from django.urls import path

from plane.novapro.views.custom_properties import (
    IssueCustomPropertyDetailEndpoint,
    IssueCustomPropertyEndpoint,
    IssueCustomPropertyValuesEndpoint,
    ProjectCustomPropertyValuesEndpoint,
)

PROJECT = "workspaces/<str:slug>/projects/<uuid:project_id>"

urlpatterns = [
    path(f"{PROJECT}/custom-properties/", IssueCustomPropertyEndpoint.as_view(), name="custom-properties"),
    path(
        f"{PROJECT}/custom-properties/<uuid:pk>/",
        IssueCustomPropertyDetailEndpoint.as_view(),
        name="custom-property",
    ),
    path(
        f"{PROJECT}/custom-property-values/",
        ProjectCustomPropertyValuesEndpoint.as_view(),
        name="project-custom-property-values",
    ),
    path(
        f"{PROJECT}/issues/<uuid:issue_id>/custom-property-values/",
        IssueCustomPropertyValuesEndpoint.as_view(),
        name="issue-custom-property-values",
    ),
]

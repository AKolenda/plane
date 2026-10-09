# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Web-app (session) endpoints for project custom properties and their values."""

# Django imports
from django.db import IntegrityError

# Third party imports
from rest_framework import serializers, status
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ROLE, allow_permission
from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, IssueCustomProperty
from plane.novapro.custom_properties import (
    CustomPropertyError,
    make_key,
    normalize_options,
    set_values,
    values_for_issues,
)


class IssueCustomPropertySerializer(serializers.ModelSerializer):
    key = serializers.SlugField(max_length=64, required=False)

    class Meta:
        model = IssueCustomProperty
        fields = ["id", "name", "key", "property_type", "description", "options", "sort_order", "project"]
        read_only_fields = ["id", "project"]

    def validate(self, attrs):
        instance = self.instance
        if instance and "property_type" in attrs and attrs["property_type"] != instance.property_type:
            raise serializers.ValidationError({"property_type": "The type of a property cannot change."})
        property_type = attrs.get("property_type", instance.property_type if instance else None)
        try:
            if "name" in attrs:
                attrs["name"] = attrs["name"].strip()
                if not attrs["name"]:
                    raise CustomPropertyError("Name is required.")
            if not instance and not attrs.get("key"):
                attrs["key"] = make_key(attrs.get("name", ""))
            if "options" in attrs or not instance:
                attrs["options"] = normalize_options(
                    property_type, attrs.get("options", []), instance.options if instance else None
                )
        except CustomPropertyError as e:
            raise serializers.ValidationError({"detail": str(e)}) from e
        return attrs


def _duplicate_response():
    return Response(
        {"detail": "A property with this name or key already exists in the project."},
        status=status.HTTP_409_CONFLICT,
    )


class IssueCustomPropertyEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        properties = IssueCustomProperty.objects.filter(workspace__slug=slug, project_id=project_id)
        return Response(IssueCustomPropertySerializer(properties, many=True).data)

    @allow_permission([ROLE.ADMIN])
    def post(self, request, slug, project_id):
        serializer = IssueCustomPropertySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            prop = serializer.save(project_id=project_id)
        except IntegrityError:
            return _duplicate_response()
        return Response(IssueCustomPropertySerializer(prop).data, status=status.HTTP_201_CREATED)


class IssueCustomPropertyDetailEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN])
    def patch(self, request, slug, project_id, pk):
        prop = IssueCustomProperty.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        serializer = IssueCustomPropertySerializer(prop, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            serializer.save()
        except IntegrityError:
            return _duplicate_response()
        return Response(serializer.data)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id, pk):
        prop = IssueCustomProperty.objects.get(workspace__slug=slug, project_id=project_id, pk=pk)
        prop.values.all().delete(soft=False)
        prop.delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectCustomPropertyValuesEndpoint(BaseAPIView):
    """All values in the project at once, keyed by work item, for list and spreadsheet layouts."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        issue_ids = [value for value in request.GET.get("issue_ids", "").split(",") if value]
        return Response(values_for_issues(project_id, issue_ids=issue_ids or None))


class IssueCustomPropertyValuesEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        Issue.issue_objects.get(workspace__slug=slug, project_id=project_id, pk=issue_id)
        return Response(values_for_issues(project_id, issue_ids=[issue_id]).get(str(issue_id), {}))

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def patch(self, request, slug, project_id, issue_id):
        """Set some values: `{"<property id or key>": value | null}`. Unlisted properties keep their value."""
        issue = Issue.issue_objects.get(workspace__slug=slug, project_id=project_id, pk=issue_id)
        try:
            set_values(issue, request.data, actor=request.user)
        except CustomPropertyError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(values_for_issues(project_id, issue_ids=[issue_id]).get(str(issue_id), {}))

# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class CustomPropertyType(models.TextChoices):
    TEXT = "text", "Text"
    NUMBER = "number", "Number"
    DATE = "date", "Date"
    SELECT = "select", "Select"
    USER = "user", "User"


class IssueCustomProperty(ProjectBaseModel):
    """A per-project field that work items in the project can carry.

    `key` is the stable, slug-like name API clients use (`severity`); `name` is the label
    people see. Select options live in `options` as `[{"id": "...", "label": "..."}]` so a
    label can be renamed without touching stored values, which reference the option id.
    """

    name = models.CharField(max_length=255)
    key = models.SlugField(max_length=64)
    property_type = models.CharField(max_length=20, choices=CustomPropertyType.choices)
    description = models.TextField(blank=True, default="")
    options = models.JSONField(default=list, blank=True)
    sort_order = models.FloatField(default=65535)

    def __str__(self):
        return f"{self.name} <{self.project_id}>"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "key"],
                condition=Q(deleted_at__isnull=True),
                name="issue_custom_property_unique_key_when_deleted_at_null",
            ),
            models.UniqueConstraint(
                fields=["project", "name"],
                condition=Q(deleted_at__isnull=True),
                name="issue_custom_property_unique_name_when_deleted_at_null",
            ),
        ]
        verbose_name = "Issue Custom Property"
        verbose_name_plural = "Issue Custom Properties"
        db_table = "issue_custom_properties"
        ordering = ("sort_order", "created_at")


class IssueCustomPropertyValue(ProjectBaseModel):
    """The value of one custom property on one work item. Only the column matching the type is set."""

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="custom_property_values")
    property = models.ForeignKey("db.IssueCustomProperty", on_delete=models.CASCADE, related_name="values")
    value_text = models.TextField(null=True, blank=True)
    value_number = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_option = models.CharField(max_length=64, null=True, blank=True)
    value_user = models.ForeignKey(
        "db.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="custom_property_values"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "property"],
                condition=Q(deleted_at__isnull=True),
                name="issue_custom_property_value_unique_when_deleted_at_null",
            )
        ]
        verbose_name = "Issue Custom Property Value"
        verbose_name_plural = "Issue Custom Property Values"
        db_table = "issue_custom_property_values"

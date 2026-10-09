# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Per-project custom properties on work items: option handling, value parsing and serialization.

Values are exchanged in two shapes:

* raw (web app): text, number, `YYYY-MM-DD`, select option id, user id.
* friendly (external API): the same, except select values are option labels and user
  values are `{"id", "email", "display_name"}`. Input accepts either shape, so API clients
  may send an option label or a user's email.
"""

# Python imports
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

# Django imports
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_date
from django.utils.text import slugify

# Module imports
from plane.db.models import (
    CustomPropertyType,
    IssueCustomProperty,
    IssueCustomPropertyValue,
    ProjectMember,
)

MAX_TEXT_LENGTH = 10000
MAX_OPTIONS = 200
VALUE_COLUMNS = ("value_text", "value_number", "value_date", "value_option", "value_user")


class CustomPropertyError(ValueError):
    """An invalid property definition or value; the message is safe to return to the client."""


# Definitions -------------------------------------------------------------------------------


def make_key(name):
    key = slugify(name).replace("-", "_")[:64]
    if not key:
        raise CustomPropertyError("Name must contain letters or digits.")
    return key


def normalize_options(property_type, options, existing=None):
    """Validate select options and give new ones a stable id. Non-select types have no options."""
    if property_type != CustomPropertyType.SELECT:
        return []
    if not isinstance(options, list) or not options:
        raise CustomPropertyError("A select property needs at least one option.")
    if len(options) > MAX_OPTIONS:
        raise CustomPropertyError(f"A select property can have at most {MAX_OPTIONS} options.")
    known_ids = {option["id"] for option in existing or []}
    normalized, labels = [], set()
    for option in options:
        label = (option.get("label") if isinstance(option, dict) else option) or ""
        label = str(label).strip()
        if not label:
            raise CustomPropertyError("Options need a label.")
        if label.lower() in labels:
            raise CustomPropertyError(f"Duplicate option: {label}.")
        labels.add(label.lower())
        option_id = option.get("id") if isinstance(option, dict) else None
        if not option_id or (existing is not None and option_id not in known_ids):
            option_id = uuid.uuid4().hex
        normalized.append({"id": str(option_id), "label": label[:255]})
    return normalized


# Values ------------------------------------------------------------------------------------


def _option_by_id_or_label(prop, raw):
    raw = str(raw).strip()
    for option in prop.options:
        if option["id"] == raw:
            return option
    for option in prop.options:
        if option["label"].lower() == raw.lower():
            return option
    raise CustomPropertyError(f"{prop.name}: unknown option {raw!r}.")


def _project_member(prop, raw):
    raw = str(raw).strip()
    lookup = {"member__email__iexact": raw} if "@" in raw else {"member_id": raw}
    try:
        membership = (
            ProjectMember.objects.filter(project_id=prop.project_id, is_active=True, **lookup)
            .select_related("member")
            .first()
        )
    except (ValueError, ValidationError) as e:  # malformed UUID
        raise CustomPropertyError(f"{prop.name}: unknown user {raw!r}.") from e
    if membership is None:
        raise CustomPropertyError(f"{prop.name}: {raw!r} is not a member of this project.")
    return membership.member


def parse_value(prop, raw):
    """Turn an incoming value into column values. `None` or `""` clears the value."""
    columns = dict.fromkeys(VALUE_COLUMNS)
    if raw is None or raw == "":
        return columns

    kind = prop.property_type
    if kind == CustomPropertyType.TEXT:
        if not isinstance(raw, (str, int, float)):
            raise CustomPropertyError(f"{prop.name}: expected text.")
        text = str(raw)
        if len(text) > MAX_TEXT_LENGTH:
            raise CustomPropertyError(f"{prop.name}: text is longer than {MAX_TEXT_LENGTH} characters.")
        columns["value_text"] = text
    elif kind == CustomPropertyType.NUMBER:
        if isinstance(raw, bool):
            raise CustomPropertyError(f"{prop.name}: expected a number.")
        try:
            number = Decimal(str(raw).strip())
        except InvalidOperation as e:
            raise CustomPropertyError(f"{prop.name}: expected a number.") from e
        if not number.is_finite() or abs(number) >= Decimal(10) ** 14:
            raise CustomPropertyError(f"{prop.name}: number is out of range.")
        columns["value_number"] = number.quantize(Decimal("0.000001"))
    elif kind == CustomPropertyType.DATE:
        parsed = raw if isinstance(raw, date) else parse_date(str(raw).strip()[:10])
        if parsed is None:
            raise CustomPropertyError(f"{prop.name}: expected a date (YYYY-MM-DD).")
        columns["value_date"] = parsed
    elif kind == CustomPropertyType.SELECT:
        columns["value_option"] = _option_by_id_or_label(prop, raw)["id"]
    elif kind == CustomPropertyType.USER:
        if isinstance(raw, dict):
            raw = raw.get("id") or raw.get("email")
        columns["value_user"] = _project_member(prop, raw)
    return columns


def _number(value):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def serialize_value(prop, row, friendly=False):
    """The stored value in raw or friendly shape; dangling options and missing users read as None."""
    if row is None:
        return None
    kind = prop.property_type
    if kind == CustomPropertyType.TEXT:
        return row.value_text
    if kind == CustomPropertyType.NUMBER:
        return _number(row.value_number)
    if kind == CustomPropertyType.DATE:
        return row.value_date.isoformat() if row.value_date else None
    if kind == CustomPropertyType.SELECT:
        option = next((o for o in prop.options if o["id"] == row.value_option), None)
        if option is None:
            return None
        return option["label"] if friendly else option["id"]
    if kind == CustomPropertyType.USER:
        if not row.value_user_id:
            return None
        if not friendly:
            return str(row.value_user_id)
        user = row.value_user
        return {"id": str(user.id), "email": user.email, "display_name": user.display_name}
    return None


def _stored(row):
    return (row.value_text, row.value_number, row.value_date, row.value_option, row.value_user_id)


def _incoming(columns):
    user = columns["value_user"]
    return (
        columns["value_text"],
        columns["value_number"],
        columns["value_date"],
        columns["value_option"],
        user.id if user else None,
    )


def project_properties(project_id):
    return list(IssueCustomProperty.objects.filter(project_id=project_id))


def values_for_issues(project_id, issue_ids=None, friendly=False):
    """`{issue_id: {property_id (or key when friendly): value}}` for the project's work items."""
    properties = {prop.id: prop for prop in project_properties(project_id)}
    rows = IssueCustomPropertyValue.objects.filter(project_id=project_id, property_id__in=properties.keys())
    if issue_ids is not None:
        rows = rows.filter(issue_id__in=issue_ids)
    if friendly:
        rows = rows.select_related("value_user")
    result = {}
    for row in rows:
        prop = properties[row.property_id]
        value = serialize_value(prop, row, friendly=friendly)
        if value is None:
            continue
        result.setdefault(str(row.issue_id), {})[prop.key if friendly else str(prop.id)] = value
    return result


def resolve_property(properties, reference):
    """Find a property by id or key."""
    reference = str(reference)
    for prop in properties:
        if str(prop.id) == reference or prop.key == reference:
            return prop
    raise CustomPropertyError(f"Unknown custom property {reference!r}.")


def set_values(issue, values, actor=None):
    """Write `{property id or key: value}` onto the work item. All or nothing; returns changed property ids."""
    if not isinstance(values, dict):
        raise CustomPropertyError("Custom property values must be an object.")
    properties = project_properties(issue.project_id)
    parsed = [(resolve_property(properties, ref), raw) for ref, raw in values.items()]
    parsed = [(prop, parse_value(prop, raw)) for prop, raw in parsed]

    changed = []
    with transaction.atomic():
        existing = {
            row.property_id: row
            for row in IssueCustomPropertyValue.objects.select_for_update().filter(
                issue=issue, property_id__in=[prop.id for prop, _ in parsed]
            )
        }
        for prop, columns in parsed:
            row = existing.get(prop.id)
            is_empty = all(value is None for value in columns.values())
            if is_empty:
                if row is not None:
                    row.delete(soft=False)
                    changed.append(prop.id)
                continue
            if row is None:
                row = IssueCustomPropertyValue(
                    issue=issue, property=prop, project_id=issue.project_id, created_by=actor
                )
            elif _stored(row) == _incoming(columns):
                continue
            for column, value in columns.items():
                setattr(row, column, value)
            row.updated_by = actor
            row.save()
            changed.append(prop.id)
    return changed

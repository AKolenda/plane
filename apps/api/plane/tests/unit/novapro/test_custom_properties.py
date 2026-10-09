# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import date
from decimal import Decimal

import pytest

from plane.db.models import IssueCustomProperty, IssueCustomPropertyValue, ProjectMember, User
from plane.novapro.custom_properties import (
    CustomPropertyError,
    make_key,
    normalize_options,
    parse_value,
    set_values,
    values_for_issues,
)


@pytest.mark.unit
class TestDefinitions:
    def test_make_key(self):
        assert make_key("Customer Impact") == "customer_impact"
        with pytest.raises(CustomPropertyError):
            make_key("!!!")

    def test_select_options_get_ids_and_must_be_unique(self):
        options = normalize_options("select", [{"label": "Low"}, "High"])
        assert [o["label"] for o in options] == ["Low", "High"] and all(o["id"] for o in options)
        with pytest.raises(CustomPropertyError, match="Duplicate"):
            normalize_options("select", ["Low", "low"])
        with pytest.raises(CustomPropertyError, match="at least one"):
            normalize_options("select", [])

    def test_renaming_an_option_keeps_its_id(self):
        existing = normalize_options("select", ["Low"])
        renamed = normalize_options("select", [{"id": existing[0]["id"], "label": "Minor"}], existing)
        assert renamed == [{"id": existing[0]["id"], "label": "Minor"}]

    def test_unknown_option_ids_are_replaced(self):
        existing = normalize_options("select", ["Low"])
        options = normalize_options("select", [{"id": "forged", "label": "X"}], existing)
        assert options[0]["id"] != "forged"

    def test_non_select_types_drop_options(self):
        assert normalize_options("text", ["ignored"]) == []


@pytest.fixture
def properties(project):
    def make(name, kind, options=()):
        return IssueCustomProperty.objects.create(
            project=project,
            name=name,
            key=make_key(name),
            property_type=kind,
            options=normalize_options(kind, list(options)),
        )

    return {
        "text": make("Customer", "text"),
        "number": make("Story points", "number"),
        "date": make("Due to customer", "date"),
        "select": make("Severity", "select", ["Low", "High"]),
        "user": make("Reviewer", "user"),
    }


@pytest.mark.unit
@pytest.mark.django_db
class TestParseValue:
    def test_number(self, properties):
        assert parse_value(properties["number"], "3.5")["value_number"] == Decimal("3.5")
        for bad in ("abc", True, "1e20", "NaN"):
            with pytest.raises(CustomPropertyError):
                parse_value(properties["number"], bad)

    def test_date(self, properties):
        assert parse_value(properties["date"], "2026-10-09")["value_date"] == date(2026, 10, 9)
        assert parse_value(properties["date"], "2026-10-09T10:00:00Z")["value_date"] == date(2026, 10, 9)
        with pytest.raises(CustomPropertyError):
            parse_value(properties["date"], "next week")

    def test_select_by_id_or_label(self, properties):
        high = properties["select"].options[1]
        assert parse_value(properties["select"], high["id"])["value_option"] == high["id"]
        assert parse_value(properties["select"], "high")["value_option"] == high["id"]
        with pytest.raises(CustomPropertyError, match="unknown option"):
            parse_value(properties["select"], "Critical")

    def test_user_must_be_project_member(self, properties, create_user):
        assert parse_value(properties["user"], str(create_user.id))["value_user"] == create_user
        assert parse_value(properties["user"], create_user.email.upper())["value_user"] == create_user
        outsider = User.objects.create(email="outsider@plane.so", username="outsider")
        for bad in (str(outsider.id), "outsider@plane.so", "not-a-uuid"):
            with pytest.raises(CustomPropertyError):
                parse_value(properties["user"], bad)

    def test_text_limits(self, properties):
        assert parse_value(properties["text"], "Acme")["value_text"] == "Acme"
        with pytest.raises(CustomPropertyError):
            parse_value(properties["text"], "x" * 10001)
        with pytest.raises(CustomPropertyError):
            parse_value(properties["text"], {"nested": True})

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_clears(self, properties, empty):
        assert all(value is None for value in parse_value(properties["number"], empty).values())


@pytest.mark.unit
@pytest.mark.django_db
class TestSetValues:
    def test_round_trip_raw_and_friendly(self, project, work_item, properties, create_user):
        changed = set_values(
            work_item,
            {
                "customer": "Acme",
                "story_points": 5,
                str(properties["date"].id): "2026-11-01",
                "severity": "High",
                "reviewer": create_user.email,
            },
            actor=create_user,
        )
        assert len(changed) == 5

        raw = values_for_issues(project.id)[str(work_item.id)]
        assert raw[str(properties["select"].id)] == properties["select"].options[1]["id"]
        assert raw[str(properties["number"].id)] == 5
        assert raw[str(properties["user"].id)] == str(create_user.id)

        friendly = values_for_issues(project.id, friendly=True)[str(work_item.id)]
        assert friendly["severity"] == "High"
        assert friendly["due_to_customer"] == "2026-11-01"
        assert friendly["reviewer"]["email"] == create_user.email

    def test_unchanged_values_are_not_reported(self, work_item, properties):
        set_values(work_item, {"customer": "Acme"})
        assert set_values(work_item, {"customer": "Acme"}) == []

    def test_clearing_removes_the_row(self, work_item, properties):
        set_values(work_item, {"customer": "Acme"})
        assert set_values(work_item, {"customer": None}) == [properties["text"].id]
        assert not IssueCustomPropertyValue.objects.filter(issue=work_item).exists()

    def test_one_bad_value_writes_nothing(self, work_item, properties):
        with pytest.raises(CustomPropertyError):
            set_values(work_item, {"customer": "Acme", "story_points": "many"})
        assert not IssueCustomPropertyValue.objects.filter(issue=work_item).exists()

    def test_unknown_property(self, work_item, properties):
        with pytest.raises(CustomPropertyError, match="Unknown custom property"):
            set_values(work_item, {"nope": 1})

    def test_deleted_option_reads_as_empty(self, project, work_item, properties):
        set_values(work_item, {"severity": "Low"})
        prop = properties["select"]
        prop.options = [option for option in prop.options if option["label"] != "Low"]
        prop.save()
        assert values_for_issues(project.id) == {}

    def test_removed_member_keeps_stored_value_but_cannot_be_set_again(self, project, work_item, properties):
        member = User.objects.create(email="m@plane.so", username="m")
        membership = ProjectMember.objects.create(project=project, member=member, role=15)
        set_values(work_item, {"reviewer": member.email})
        membership.is_active = False
        membership.save()
        with pytest.raises(CustomPropertyError):
            set_values(work_item, {"reviewer": member.email})

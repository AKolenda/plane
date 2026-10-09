# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""NovaPro: passwords have no strength or length rules; any non-empty password is accepted."""

import uuid

import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from plane.db.models import User
from plane.license.models import Instance

WEAK_PASSWORD = "a"


@pytest.fixture
def setup_instance(db):
    instance, _ = Instance.objects.update_or_create(
        id=Instance.objects.first().id if Instance.objects.exists() else uuid.uuid4(),
        defaults={
            "instance_name": "Test Instance",
            "instance_id": str(uuid.uuid4()),
            "current_version": "1.0.0",
            "domain": "http://localhost:8000",
            "last_checked_at": timezone.now(),
            "is_setup_done": True,
        },
    )
    return instance


@pytest.fixture
def django_client():
    return Client(HTTP_USER_AGENT="Mozilla/5.0 (X11; Linux x86_64; rv:15.0) Gecko/20100101 Firefox/15.0.1")


@pytest.mark.contract
class TestNoPasswordRules:
    @pytest.mark.django_db
    def test_sign_up_accepts_weak_password(self, django_client, setup_instance):
        response = django_client.post(
            reverse("sign-up"), {"email": "weak@plane.so", "password": WEAK_PASSWORD}, follow=False
        )

        assert response.status_code == 302
        assert "PASSWORD_TOO_WEAK" not in response.url
        assert "error_code" not in response.url
        assert User.objects.get(email="weak@plane.so").check_password(WEAK_PASSWORD)

    @pytest.mark.django_db
    def test_set_password_accepts_weak_password(self, django_client, setup_instance):
        user = User.objects.create(email="autoset@plane.so", is_password_autoset=True)
        django_client.force_login(user)

        response = django_client.post(reverse("set-password"), {"password": WEAK_PASSWORD})

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.check_password(WEAK_PASSWORD)
        assert user.is_password_autoset is False

    @pytest.mark.django_db
    def test_reset_password_command_accepts_weak_password(self, monkeypatch):
        user = User.objects.create(email="cli@plane.so")
        monkeypatch.setattr("getpass.getpass", lambda *_args, **_kwargs: WEAK_PASSWORD)

        call_command("reset_password", "cli@plane.so")

        user.refresh_from_db()
        assert user.check_password(WEAK_PASSWORD)

    def test_django_validators_disabled(self):
        # Raises ValidationError if any AUTH_PASSWORD_VALIDATORS are configured.
        validate_password(WEAK_PASSWORD)

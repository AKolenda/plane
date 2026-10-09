# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from plane.db.models import GithubConnection, GithubWatchedRepository
from plane.integrations.github.config import GithubIntegrationSettings
from plane.integrations.github.webhooks import compute_signature, handle_event, verify_signature

from .conftest import WEBHOOK_SECRET, pull_request_payload

APP_SECRET = "app-webhook-secret"


def app_settings(**overrides):
    values = {
        "host_url": "https://github.com",
        "api_url": "https://api.github.com",
        "webhook_base_url": "https://plane.example.com",
        "app_id": "1",
        "app_slug": "plane-ce",
        "app_private_key": "key",
        "app_webhook_secret": APP_SECRET,
        "app_client_id": "",
        "app_client_secret": "",
        "oauth_client_id": "",
        "oauth_client_secret": "",
    }
    values.update(overrides)
    return GithubIntegrationSettings(**values)


@pytest.fixture
def redis():
    store = set()
    fake = MagicMock()
    fake.set.side_effect = lambda key, value, nx, ex: (key not in store) and not store.add(key)
    with patch("plane.app.views.github.public.redis_instance", return_value=fake):
        yield store


def deliver(url, payload, secret, event="pull_request", delivery="d-1", signature=None):
    body = json.dumps(payload).encode()
    return Client().post(
        url,
        data=body,
        content_type="application/json",
        HTTP_X_GITHUB_EVENT=event,
        HTTP_X_GITHUB_DELIVERY=delivery,
        HTTP_X_HUB_SIGNATURE_256=signature or compute_signature(secret, body),
    )


@pytest.mark.unit
class TestSignature:
    def test_valid_signature(self):
        body = b'{"zen": "Keep it logically awesome."}'
        assert verify_signature("s3cret", body, compute_signature("s3cret", body))

    @pytest.mark.parametrize("header", ["", "sha1=abc", "sha256=deadbeef"])
    def test_invalid_signatures(self, header):
        assert not verify_signature("s3cret", b"{}", header)

    def test_wrong_secret(self):
        body = b"{}"
        assert not verify_signature("other", body, compute_signature("s3cret", body))

    def test_missing_secret_never_verifies(self):
        assert not verify_signature("", b"{}", compute_signature("", b"{}"))


@pytest.mark.unit
@pytest.mark.django_db
class TestOAuthWebhookEndpoint:
    def url(self, connection):
        return f"/api/integrations/github/webhook/{connection.id}/"

    def test_verified_delivery_is_queued(self, connection, redis, background_tasks):
        response = deliver(self.url(connection), pull_request_payload(), WEBHOOK_SECRET)
        assert response.status_code == 202
        args = background_tasks["webhook"].call_args.args
        assert args[0] == str(connection.id) and args[1] == "pull_request"

    def test_bad_signature_is_rejected(self, connection, redis, background_tasks):
        response = deliver(self.url(connection), pull_request_payload(), "wrong-secret")
        assert response.status_code == 401
        background_tasks["webhook"].assert_not_called()

    def test_ping(self, connection, redis, background_tasks):
        response = deliver(self.url(connection), {"zen": "hi"}, WEBHOOK_SECRET, event="ping")
        assert response.status_code == 200 and response.json() == {"message": "pong"}
        background_tasks["webhook"].assert_not_called()

    def test_duplicate_delivery_is_processed_once(self, connection, redis, background_tasks):
        deliver(self.url(connection), pull_request_payload(), WEBHOOK_SECRET, delivery="same")
        deliver(self.url(connection), pull_request_payload(), WEBHOOK_SECRET, delivery="same")
        assert background_tasks["webhook"].call_count == 1

    def test_unknown_connection(self, db, redis):
        response = deliver("/api/integrations/github/webhook/00000000-0000-0000-0000-000000000000/", {}, WEBHOOK_SECRET)
        assert response.status_code == 404

    def test_invalid_json(self, connection, redis):
        body = b"not json"
        response = Client().post(
            self.url(connection),
            data=body,
            content_type="application/json",
            HTTP_X_GITHUB_EVENT="pull_request",
            HTTP_X_HUB_SIGNATURE_256=compute_signature(WEBHOOK_SECRET, body),
        )
        assert response.status_code == 400


@pytest.mark.unit
@pytest.mark.django_db
class TestAppWebhookEndpoint:
    URL = "/api/integrations/github/webhook/"

    @pytest.fixture(autouse=True)
    def configured(self):
        with patch("plane.app.views.github.public.get_github_settings", return_value=app_settings()):
            yield

    def test_routes_by_installation(self, connection, redis, background_tasks):
        connection.auth_type = "app"
        connection.installation_id = 77
        connection.save()
        payload = {**pull_request_payload(), "installation": {"id": 77}}

        response = deliver(self.URL, payload, APP_SECRET)

        assert response.status_code == 202
        assert background_tasks["webhook"].call_args.args[0] == str(connection.id)

    def test_unknown_installation_is_acknowledged(self, db, redis, background_tasks):
        payload = {**pull_request_payload(), "installation": {"id": 12345}}
        assert deliver(self.URL, payload, APP_SECRET).status_code == 202
        background_tasks["webhook"].assert_not_called()

    def test_bad_signature(self, db, redis):
        assert deliver(self.URL, {"installation": {"id": 1}}, "nope").status_code == 401


@pytest.mark.unit
@pytest.mark.django_db
class TestHandleEvent:
    def test_unwatched_repository_is_ignored(self, connection):
        payload = pull_request_payload()
        payload["repository"]["id"] = 999
        assert handle_event(connection, "pull_request", payload) == "repository not watched"

    def test_app_uninstall_removes_connection(self, connection, repository):
        handle_event(connection, "installation", {"action": "deleted", "installation": {"id": 1}})
        assert not GithubConnection.objects.filter(pk=connection.pk).exists()
        assert not GithubWatchedRepository.objects.filter(pk=repository.pk).exists()

    def test_repository_removed_from_installation(self, connection, repository):
        handle_event(
            connection, "installation_repositories", {"action": "removed", "repositories_removed": [{"id": 555}]}
        )
        assert not GithubWatchedRepository.objects.filter(pk=repository.pk).exists()

    def test_pull_request_is_routed(self, repository, work_item, mappings):
        payload = pull_request_payload(title=f"[ENG-{work_item.sequence_id}] x")
        result = handle_event(repository.connection, "pull_request", payload)
        assert result["linked"] == [work_item.id]

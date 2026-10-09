# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Endpoints GitHub calls: the install/authorize redirect and webhook deliveries."""

# Python imports
import json
import logging
from urllib.parse import urlencode

# Django imports
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

# Module imports
from plane.bgtasks.github_integration_task import process_github_webhook
from plane.db.models import GithubAuthType, GithubConnection, Workspace
from plane.integrations.github.config import get_github_settings
from plane.integrations.github.connect import ConnectError, complete_connection, load_state
from plane.integrations.github.webhooks import verify_signature
from plane.license.utils.encryption import decrypt_data
from plane.settings.redis import redis_instance
from plane.utils.host import base_host

logger = logging.getLogger("plane.api")

DELIVERY_DEDUP_SECONDS = 24 * 60 * 60


class GithubCallbackEndpoint(View):
    """GitHub redirects here after an App installation or an OAuth authorization."""

    def get(self, request):
        app_url = base_host(request=request, is_app=True).rstrip("/")
        params = request.GET

        workspace_slug = None
        try:
            state = load_state(params.get("state"))
            workspace_slug = Workspace.objects.filter(pk=state["w"]).values_list("slug", flat=True).first()
            if not request.user.is_authenticated:
                raise ConnectError("Sign in to Plane, then connect GitHub again.")
            if params.get("error"):
                raise ConnectError(params.get("error_description") or "GitHub authorization was cancelled.")
            complete_connection(request.user, params)
            query = {"github": "connected"}
        except ConnectError as e:
            query = {"github": "error", "message": str(e)}
        except Exception:
            logger.exception("GitHub connection callback failed")
            query = {"github": "error", "message": "GitHub connection failed. Check the integration settings."}

        if not workspace_slug:
            return HttpResponseRedirect(f"{app_url}/?{urlencode(query)}")
        return HttpResponseRedirect(f"{app_url}/{workspace_slug}/settings/github?{urlencode(query)}")


@method_decorator(csrf_exempt, name="dispatch")
class GithubWebhookEndpoint(View):
    """Receive GitHub webhook deliveries.

    `/webhook/` serves the GitHub App (one secret for the whole instance); `/webhook/<id>/`
    serves the repository webhooks Plane creates for an OAuth connection (one secret each).
    Verified deliveries are processed in the background.
    """

    def post(self, request, connection_id=None):
        body = request.body
        signature = request.headers.get("X-Hub-Signature-256", "")
        event_name = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")

        if connection_id is None:
            github_settings = get_github_settings()
            if not verify_signature(github_settings.app_webhook_secret, body, signature):
                return JsonResponse({"error": "Invalid signature"}, status=401)
            payload = self._parse(body)
            if payload is None:
                return JsonResponse({"error": "Invalid payload"}, status=400)
            installation_id = (payload.get("installation") or {}).get("id")
            connection_ids = (
                list(
                    GithubConnection.objects.filter(
                        auth_type=GithubAuthType.APP,
                        host_url=github_settings.host_url,
                        installation_id=installation_id,
                    ).values_list("id", flat=True)
                )
                if installation_id
                else []
            )
        else:
            connection = GithubConnection.objects.filter(pk=connection_id, auth_type=GithubAuthType.OAUTH).first()
            if connection is None:
                return JsonResponse({"error": "Unknown connection"}, status=404)
            if not verify_signature(decrypt_data(connection.webhook_secret), body, signature):
                return JsonResponse({"error": "Invalid signature"}, status=401)
            payload = self._parse(body)
            if payload is None:
                return JsonResponse({"error": "Invalid payload"}, status=400)
            connection_ids = [connection.id]

        if event_name == "ping":
            return JsonResponse({"message": "pong"})
        if not connection_ids:
            return JsonResponse({"message": "No workspace is connected to this installation"}, status=202)
        if delivery_id and not self._first_delivery(delivery_id):
            return JsonResponse({"message": "Duplicate delivery"}, status=202)

        try:
            for pk in connection_ids:
                process_github_webhook.delay(str(pk), event_name, payload, delivery_id)
        except Exception:
            # Let GitHub's redelivery through when the task could not be queued
            self._forget_delivery(delivery_id)
            raise
        return JsonResponse({"message": "Accepted"}, status=202)

    @staticmethod
    def _parse(body):
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _first_delivery(delivery_id):
        """GitHub retries and manual redeliveries reuse the delivery id; process each id once."""
        try:
            return bool(redis_instance().set(f"github:delivery:{delivery_id}", 1, nx=True, ex=DELIVERY_DEDUP_SECONDS))
        except Exception:
            # Redis being unavailable must not drop deliveries
            return True

    @staticmethod
    def _forget_delivery(delivery_id):
        try:
            redis_instance().delete(f"github:delivery:{delivery_id}")
        except Exception:
            pass

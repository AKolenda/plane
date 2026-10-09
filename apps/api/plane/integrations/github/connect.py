# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Connect a workspace to GitHub: signed state, the install/authorize callback, and connection storage."""

# Python imports
import secrets

# Django imports
from django.conf import settings
from django.core import signing

# Module imports
from plane.db.models import GithubAuthType, GithubConnection, WorkspaceMember
from plane.license.utils.encryption import encrypt_data

from . import client as github_client
from .bot import get_github_bot_user
from .config import get_github_settings

STATE_SALT = "plane.integrations.github.connect"
STATE_MAX_AGE_SECONDS = 15 * 60
# `repo` covers private repositories, issues and pull requests; `admin:repo_hook` lets Plane
# create the webhook on each repository you choose to watch.
OAUTH_SCOPES = ("repo", "admin:repo_hook")
CALLBACK_PATH = "/api/integrations/github/callback/"
ADMIN_ROLE = 20


class ConnectError(Exception):
    """A callback failure whose message is safe to show to the user."""


def sign_state(workspace_id, user_id, auth_type):
    return signing.dumps({"w": str(workspace_id), "u": str(user_id), "t": auth_type}, salt=STATE_SALT)


def load_state(state):
    try:
        return signing.loads(state or "", salt=STATE_SALT, max_age=STATE_MAX_AGE_SECONDS)
    except signing.BadSignature as e:
        raise ConnectError("The GitHub connection request expired. Try connecting again.") from e


def callback_url(request):
    base_url = (settings.WEB_URL or request.build_absolute_uri("/")).rstrip("/")
    return f"{base_url}{CALLBACK_PATH}"


def complete_connection(user, params):
    """Finish the GitHub redirect for `user` and return the saved connection.

    GitHub App installs arrive with `installation_id` (and a `code` when the app asks for
    user authorization during installation); OAuth authorizations arrive with `code` only.
    """
    state = load_state(params.get("state"))
    if str(user.id) != state["u"]:
        raise ConnectError("This GitHub connection was started by another user.")
    if not WorkspaceMember.objects.filter(
        workspace_id=state["w"], member=user, role=ADMIN_ROLE, is_active=True
    ).exists():
        raise ConnectError("Only workspace admins can connect GitHub.")

    github_settings = get_github_settings()
    if state["t"] == GithubAuthType.APP:
        return _complete_app_installation(user, state["w"], params, github_settings)
    if state["t"] == GithubAuthType.OAUTH:
        return _complete_oauth(user, state["w"], params, github_settings)
    raise ConnectError("Unknown connection type.")


def _complete_app_installation(user, workspace_id, params, github_settings):
    installation_id = params.get("installation_id")
    if not str(installation_id or "").isdigit():
        raise ConnectError("GitHub did not return an installation. Try connecting again.")

    # With app client credentials, prove the user can see the installation they claim;
    # otherwise anyone who learned an installation id could attach it to their workspace.
    if github_settings.app_client_id and github_settings.app_client_secret:
        code = params.get("code")
        if not code:
            raise ConnectError("Enable “Request user authorization (OAuth) during installation” on the GitHub App.")
        user_token = github_client.exchange_oauth_code(
            github_settings.api_url, github_settings.app_client_id, github_settings.app_client_secret, code
        )
        if not github_client.user_can_access_installation(user_token, github_settings.api_url, installation_id):
            raise ConnectError("Your GitHub account cannot access this installation.")

    taken = (
        GithubConnection.objects.filter(host_url=github_settings.host_url, installation_id=installation_id)
        .exclude(workspace_id=workspace_id)
        .exists()
    )
    if taken:
        raise ConnectError("This GitHub installation is already connected to another workspace.")

    account = github_client.get_installation_account(installation_id, github_settings)
    return save_connection(
        workspace_id, user, GithubAuthType.APP, account, github_settings, installation_id=installation_id
    )


def _complete_oauth(user, workspace_id, params, github_settings):
    code = params.get("code")
    if not code:
        raise ConnectError("GitHub authorization was cancelled.")
    access_token = github_client.exchange_oauth_code(
        github_settings.api_url, github_settings.oauth_client_id, github_settings.oauth_client_secret, code
    )
    account = github_client.get_authenticated_account(github_client.token_client(access_token, github_settings.api_url))
    return save_connection(
        workspace_id, user, GithubAuthType.OAUTH, account, github_settings, access_token=access_token
    )


def save_connection(workspace_id, user, auth_type, account, github_settings, installation_id=None, access_token=None):
    lookup = {
        "workspace_id": workspace_id,
        "host_url": github_settings.host_url,
        "auth_type": auth_type,
        "account_id": account["id"],
    }
    connection = GithubConnection.objects.filter(**lookup).first() or GithubConnection(**lookup)
    connection.api_url = github_settings.api_url
    connection.account_login = account["login"]
    connection.account_type = account["type"]
    connection.account_avatar_url = account["avatar_url"]
    connection.connected_by = user
    connection.bot_user = get_github_bot_user(workspace_id)
    if installation_id is not None:
        connection.installation_id = int(installation_id)
    if access_token is not None:
        connection.access_token = encrypt_data(access_token)
    if auth_type == GithubAuthType.OAUTH and not connection.webhook_secret:
        connection.webhook_secret = encrypt_data(secrets.token_hex(32))
    connection.save()
    return connection

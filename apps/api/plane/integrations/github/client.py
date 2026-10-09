# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Thin wrappers around PyGithub for the calls the integration makes.

Every function takes a `GithubConnection` (or the instance settings) and works the same
against github.com and GitHub Enterprise Server: the connection stores its API base URL.
"""

# Third party imports
from github import Auth, Github, GithubIntegration

# Module imports
from plane.db.models import GithubAuthType
from plane.license.utils.encryption import decrypt_data

from .config import get_github_settings

REQUEST_TIMEOUT_SECONDS = 15
MAX_LISTED_REPOSITORIES = 1000
# Events the repository webhooks created for OAuth connections subscribe to. GitHub App
# connections subscribe to the same events in the app's settings.
WEBHOOK_EVENTS = ["pull_request", "pull_request_review", "issues"]


class GithubIntegrationNotConfigured(Exception):
    pass


def get_app_integration(github_settings=None):
    github_settings = github_settings or get_github_settings()
    if not github_settings.is_app_configured:
        raise GithubIntegrationNotConfigured("GitHub App credentials are not configured")
    return GithubIntegration(
        auth=Auth.AppAuth(int(github_settings.app_id), github_settings.app_private_key),
        base_url=github_settings.api_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def get_client(connection):
    """Return an authenticated `Github` client acting for the connection."""
    if connection.auth_type == GithubAuthType.APP:
        return get_app_integration().get_github_for_installation(connection.installation_id)
    return token_client(decrypt_data(connection.access_token), connection.api_url)


def token_client(token, api_url):
    return Github(auth=Auth.Token(token), base_url=api_url, timeout=REQUEST_TIMEOUT_SECONDS)


def exchange_oauth_code(api_url, client_id, client_secret, code):
    """Exchange an OAuth `code` for a user access token (OAuth App or GitHub App user authorization)."""
    application = Github(base_url=api_url, timeout=REQUEST_TIMEOUT_SECONDS).get_oauth_application(
        client_id, client_secret
    )
    return application.get_access_token(code).token


def get_authenticated_account(client):
    user = client.get_user()
    return {"id": user.id, "login": user.login, "type": user.type or "User", "avatar_url": user.avatar_url or ""}


def get_installation_account(installation_id, github_settings=None):
    installation = get_app_integration(github_settings).get_app_installation(int(installation_id))
    account = installation.raw_data.get("account") or {}
    return {
        "id": account.get("id"),
        "login": account.get("login") or account.get("slug") or "",
        "type": account.get("type") or "Organization",
        "avatar_url": account.get("avatar_url") or "",
    }


def user_can_access_installation(user_token, api_url, installation_id):
    """True when the user who authorized the app during installation can see the installation."""
    installations = token_client(user_token, api_url).get_user().get_installations()
    return any(installation.id == int(installation_id) for installation in installations)


def _repository_to_dict(repository):
    permissions = repository.raw_data.get("permissions") or {}
    return {
        "id": repository.id,
        "full_name": repository.full_name,
        "html_url": repository.html_url,
        "private": repository.private,
        "default_branch": repository.default_branch or "",
        "can_admin": bool(permissions.get("admin")),
    }


def list_accessible_repositories(connection):
    """Repositories the connection can watch: the installation's repositories, or the OAuth user's."""
    if connection.auth_type == GithubAuthType.APP:
        installation = get_app_integration().get_app_installation(connection.installation_id)
        repositories = installation.get_repos()
    else:
        repositories = (
            get_client(connection)
            .get_user()
            .get_repos(affiliation="owner,collaborator,organization_member", sort="full_name")
        )
    result = []
    for repository in repositories:
        result.append(_repository_to_dict(repository))
        if len(result) >= MAX_LISTED_REPOSITORIES:
            break
    return result


def get_repository(connection, repository_id):
    return _repository_to_dict(get_client(connection).get_repo(int(repository_id)))


def create_repository_webhook(connection, full_name, url, secret):
    """Create a repository webhook (OAuth connections only) and return its id."""
    hook = (
        get_client(connection)
        .get_repo(full_name)
        .create_hook(
            "web",
            {"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"},
            events=WEBHOOK_EVENTS,
            active=True,
        )
    )
    return hook.id


def delete_repository_webhook(connection, full_name, webhook_id):
    get_client(connection).get_repo(full_name).get_hook(int(webhook_id)).delete()


def render_markdown(connection, full_name, text):
    """Render GitHub-flavoured markdown to HTML the way GitHub shows it in the repository."""
    if not text:
        return ""
    client = get_client(connection)
    return client.render_markdown(text, context=client.get_repo(full_name))


def create_issue(connection, full_name, title, body):
    issue = get_client(connection).get_repo(full_name).create_issue(title=title, body=body)
    return issue.raw_data


def update_issue(connection, full_name, number, **fields):
    issue = get_client(connection).get_repo(full_name).get_issue(int(number))
    issue.edit(**fields)
    return issue.raw_data

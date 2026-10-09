# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from plane.db.models import (
    GithubConnection,
    GithubPullRequest,
    GithubPullRequestIssue,
    GithubStateMapping,
    GithubWatchedRepository,
    Project,
    State,
)
from plane.integrations.github.config import api_url_for_host, normalize_host_url, normalize_private_key
from plane.integrations.github.connect import ConnectError, complete_connection, sign_state

from .test_github_webhook_endpoint import app_settings

PEM = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"


@pytest.mark.unit
class TestConfig:
    @pytest.mark.parametrize(
        "host,api",
        [
            ("https://github.com", "https://api.github.com"),
            ("https://github.com/", "https://api.github.com"),
            ("", "https://api.github.com"),
            ("https://ghe.acme.com", "https://ghe.acme.com/api/v3"),
            ("https://ghe.acme.com:8443/", "https://ghe.acme.com:8443/api/v3"),
        ],
    )
    def test_api_url_for_host(self, host, api):
        assert api_url_for_host(host) == api

    def test_invalid_host(self):
        with pytest.raises(ValueError):
            normalize_host_url("ghe.acme.com")

    @pytest.mark.parametrize(
        "value",
        [PEM, PEM.replace("\n", "\\n"), __import__("base64").b64encode(PEM.encode()).decode()],
    )
    def test_private_key_formats(self, value):
        assert normalize_private_key(value) == PEM


@pytest.mark.unit
@pytest.mark.django_db
class TestStateMappingApi:
    def url(self, workspace, project):
        return f"/api/workspaces/{workspace.slug}/projects/{project.id}/integrations/github/state-mappings/"

    def test_replace_and_list(self, session_client, workspace, project, states, mappings):
        payload = {
            "mappings": [
                {"event": "merged", "base_branch": "staging", "state_id": str(states["In QA"].id)},
                {"event": "merged", "base_branch": " main ", "state_id": str(states["Deployed"].id)},
                {"event": "review_requested", "state_id": str(states["In Review"].id)},
            ]
        }
        response = session_client.put(self.url(workspace, project), payload, format="json")

        assert response.status_code == 200, response.data
        assert {(m["event"], m["base_branch"]) for m in response.data} == {
            ("merged", "staging"),
            ("merged", "main"),
            ("review_requested", ""),
        }
        assert GithubStateMapping.objects.filter(project=project).count() == 3

    def test_rejects_state_from_another_project(self, session_client, workspace, project, states):
        other = Project.objects.create(name="Web", identifier="WEB", workspace=workspace)
        foreign = State.objects.create(project=other, name="Done", group="completed", color="#000")
        payload = {"mappings": [{"event": "merged", "state_id": str(foreign.id)}]}
        response = session_client.put(self.url(workspace, project), payload, format="json")
        assert response.status_code == 400

    def test_rejects_duplicates_and_unknown_events(self, session_client, workspace, project, states):
        state_id = str(states["In QA"].id)
        duplicate = {"mappings": [{"event": "merged", "state_id": state_id}, {"event": "merged", "state_id": state_id}]}
        assert session_client.put(self.url(workspace, project), duplicate, format="json").status_code == 400
        unknown = {"mappings": [{"event": "deployed", "state_id": state_id}]}
        assert session_client.put(self.url(workspace, project), unknown, format="json").status_code == 400


@pytest.mark.unit
@pytest.mark.django_db
class TestIssuePullRequestsApi:
    def test_lists_linked_pull_requests(self, session_client, workspace, project, work_item, repository):
        pull_request = GithubPullRequest.objects.create(
            workspace=workspace,
            repository=repository,
            github_id=1,
            number=12,
            title="[ENG-1] Sync",
            html_url="https://github.com/acme/api/pull/12",
            state="merged",
            base_branch="main",
        )
        GithubPullRequest.objects.create(
            workspace=workspace, repository=repository, github_id=2, number=13, title="Other", html_url="https://x.test"
        )
        GithubPullRequestIssue.objects.create(pull_request=pull_request, issue=work_item, project=project)

        response = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{work_item.id}/github/pull-requests/"
        )

        assert response.status_code == 200
        assert [(pr["number"], pr["state"], pr["repository_full_name"]) for pr in response.data] == [
            (12, "merged", "acme/api")
        ]


@pytest.mark.unit
@pytest.mark.django_db
class TestRepositoryApi:
    def base(self, workspace):
        return f"/api/workspaces/{workspace.slug}/integrations/github"

    def test_watch_creates_webhook_for_oauth_connections(self, session_client, workspace, connection):
        repository = {
            "id": 555,
            "full_name": "acme/api",
            "html_url": "https://github.com/acme/api",
            "private": True,
            "default_branch": "main",
            "can_admin": True,
        }
        with (
            patch("plane.app.views.github.base.github_client.get_repository", return_value=repository),
            patch("plane.app.views.github.base.github_client.create_repository_webhook", return_value=31) as hook,
            patch("plane.app.views.github.base.get_github_settings", return_value=app_settings()),
        ):
            response = session_client.post(
                f"{self.base(workspace)}/repositories/",
                {"connection_id": str(connection.id), "repository_id": 555},
                format="json",
            )

        assert response.status_code == 201, response.data
        watched = GithubWatchedRepository.objects.get(connection=connection)
        assert watched.webhook_id == 31 and watched.full_name == "acme/api"
        assert hook.call_args.args[2] == f"https://plane.example.com/api/integrations/github/webhook/{connection.id}/"

    def test_failed_webhook_creation_rolls_back(self, session_client, workspace, connection):
        repository = {"id": 555, "full_name": "acme/api", "html_url": "u", "private": False, "default_branch": ""}
        with (
            patch("plane.app.views.github.base.github_client.get_repository", return_value=repository),
            patch(
                "plane.app.views.github.base.github_client.create_repository_webhook", side_effect=RuntimeError("403")
            ),
        ):
            response = session_client.post(
                f"{self.base(workspace)}/repositories/",
                {"connection_id": str(connection.id), "repository_id": 555},
                format="json",
            )
        assert response.status_code == 400
        assert not GithubWatchedRepository.objects.exists()

    def test_enabling_sync_requires_a_project(self, session_client, workspace, repository):
        response = session_client.patch(
            f"{self.base(workspace)}/repositories/{repository.id}/", {"issue_sync_mode": "bidirectional"}, format="json"
        )
        assert response.status_code == 400

    def test_configure_sync(self, session_client, workspace, project, states, repository):
        response = session_client.patch(
            f"{self.base(workspace)}/repositories/{repository.id}/",
            {
                "project": str(project.id),
                "issue_sync_mode": "bidirectional",
                "github_label": " plane-sync ",
                "closed_state": str(states["Deployed"].id),
            },
            format="json",
        )
        assert response.status_code == 200, response.data
        repository.refresh_from_db()
        assert repository.issue_sync_mode == "bidirectional" and repository.github_label == "plane-sync"
        assert repository.closed_state_id == states["Deployed"].id

    def test_non_admin_cannot_manage(self, api_client, workspace, repository):
        from plane.db.models import User, WorkspaceMember

        member = User.objects.create(email="member@plane.so", username="member")
        WorkspaceMember.objects.create(workspace=workspace, member=member, role=15)
        api_client.force_authenticate(user=member)
        assert api_client.get(f"{self.base(workspace)}/repositories/").status_code == 403

    def test_connect_returns_install_url_with_signed_state(self, session_client, workspace):
        with patch("plane.app.views.github.base.get_github_settings", return_value=app_settings()):
            response = session_client.post(f"{self.base(workspace)}/connect/", {"auth_type": "app"}, format="json")
        url = urlparse(response.data["url"])
        assert url.netloc == "github.com" and url.path == "/apps/plane-ce/installations/new"
        assert parse_qs(url.query)["state"]

    def test_connect_oauth_on_enterprise_server(self, session_client, workspace):
        settings = app_settings(
            host_url="https://ghe.acme.com",
            api_url="https://ghe.acme.com/api/v3",
            oauth_client_id="cid",
            oauth_client_secret="secret",
        )
        with patch("plane.app.views.github.base.get_github_settings", return_value=settings):
            response = session_client.post(f"{self.base(workspace)}/connect/", {"auth_type": "oauth"}, format="json")
        url = urlparse(response.data["url"])
        query = parse_qs(url.query)
        assert url.netloc == "ghe.acme.com" and url.path == "/login/oauth/authorize"
        assert query["scope"] == ["repo admin:repo_hook"] and query["client_id"] == ["cid"]


@pytest.mark.unit
@pytest.mark.django_db
class TestCompleteConnection:
    ACCOUNT = {"id": 4242, "login": "acme", "type": "Organization", "avatar_url": ""}

    @pytest.fixture(autouse=True)
    def configured(self):
        with patch("plane.integrations.github.connect.get_github_settings", return_value=app_settings()):
            yield

    def test_app_installation(self, workspace, create_user):
        state = sign_state(workspace.id, create_user.id, "app")
        with patch(
            "plane.integrations.github.connect.github_client.get_installation_account", return_value=self.ACCOUNT
        ):
            connection = complete_connection(create_user, {"state": state, "installation_id": "77"})
        assert connection.installation_id == 77 and connection.account_login == "acme"
        assert connection.bot_user.is_bot

    def test_installation_cannot_move_to_a_second_workspace(self, workspace, create_user):
        from plane.db.models import Workspace

        GithubConnection.objects.create(
            workspace=Workspace.objects.create(name="Other", slug="other", owner=create_user),
            auth_type="app",
            account_id=4242,
            account_login="acme",
            installation_id=77,
        )
        state = sign_state(workspace.id, create_user.id, "app")
        with pytest.raises(ConnectError, match="another workspace"):
            complete_connection(create_user, {"state": state, "installation_id": "77"})

    def test_state_from_another_user_is_rejected(self, workspace, create_user):
        from plane.db.models import User

        other = User.objects.create(email="x@plane.so", username="x")
        state = sign_state(workspace.id, other.id, "app")
        with pytest.raises(ConnectError, match="another user"):
            complete_connection(create_user, {"state": state, "installation_id": "77"})

    def test_tampered_state_is_rejected(self, workspace, create_user):
        with pytest.raises(ConnectError, match="expired"):
            complete_connection(create_user, {"state": "forged", "installation_id": "77"})

    def test_installation_ownership_is_verified_when_app_client_is_configured(self, workspace, create_user):
        settings = app_settings(app_client_id="Iv1.x", app_client_secret="s")
        state = sign_state(workspace.id, create_user.id, "app")
        with (
            patch("plane.integrations.github.connect.get_github_settings", return_value=settings),
            patch("plane.integrations.github.connect.github_client.exchange_oauth_code", return_value="ghu_x"),
            patch("plane.integrations.github.connect.github_client.user_can_access_installation", return_value=False),
        ):
            with pytest.raises(ConnectError, match="cannot access"):
                complete_connection(create_user, {"state": state, "installation_id": "77", "code": "c"})

    def test_oauth_stores_encrypted_token(self, workspace, create_user):
        settings = app_settings(oauth_client_id="cid", oauth_client_secret="secret")
        state = sign_state(workspace.id, create_user.id, "oauth")
        with (
            patch("plane.integrations.github.connect.get_github_settings", return_value=settings),
            patch("plane.integrations.github.connect.github_client.exchange_oauth_code", return_value="gho_secret"),
            patch(
                "plane.integrations.github.connect.github_client.get_authenticated_account", return_value=self.ACCOUNT
            ),
        ):
            connection = complete_connection(create_user, {"state": state, "code": "c"})

        from plane.license.utils.encryption import decrypt_data

        assert connection.access_token != "gho_secret"
        assert decrypt_data(connection.access_token) == "gho_secret"
        assert decrypt_data(connection.webhook_secret)

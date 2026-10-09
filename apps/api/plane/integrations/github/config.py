# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import base64
import binascii
import os
from dataclasses import dataclass
from urllib.parse import urlparse

# Django imports
from django.conf import settings

# Module imports
from plane.license.utils.instance_value import get_configuration_value

GITHUB_DOT_COM = "https://github.com"
GITHUB_DOT_COM_API = "https://api.github.com"

CONFIG_KEYS = (
    "GITHUB_INTEGRATION_HOST_URL",
    "GITHUB_INTEGRATION_API_URL",
    "GITHUB_INTEGRATION_WEBHOOK_BASE_URL",
    "GITHUB_APP_ID",
    "GITHUB_APP_SLUG",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_APP_WEBHOOK_SECRET",
    "GITHUB_APP_CLIENT_ID",
    "GITHUB_APP_CLIENT_SECRET",
    "GITHUB_INTEGRATION_OAUTH_CLIENT_ID",
    "GITHUB_INTEGRATION_OAUTH_CLIENT_SECRET",
)


def normalize_host_url(host_url):
    """Return `scheme://host[:port]` without a trailing slash, defaulting to github.com."""
    host_url = (host_url or GITHUB_DOT_COM).strip().rstrip("/")
    parsed = urlparse(host_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid GitHub host URL: {host_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def api_url_for_host(host_url):
    """github.com uses api.github.com; GitHub Enterprise Server serves its REST API under /api/v3."""
    host_url = normalize_host_url(host_url)
    if host_url == GITHUB_DOT_COM:
        return GITHUB_DOT_COM_API
    return f"{host_url}/api/v3"


def normalize_private_key(value):
    """Accept a raw PEM, a PEM with literal `\\n` escapes (common in .env files), or a base64-encoded PEM."""
    value = (value or "").strip()
    if not value:
        return ""
    if "-----BEGIN" in value:
        return value.replace("\\n", "\n")
    try:
        decoded = base64.b64decode(value, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return value
    return decoded.strip() if "-----BEGIN" in decoded else value


@dataclass(frozen=True)
class GithubIntegrationSettings:
    host_url: str
    api_url: str
    webhook_base_url: str
    app_id: str
    app_slug: str
    app_private_key: str
    app_webhook_secret: str
    app_client_id: str
    app_client_secret: str
    oauth_client_id: str
    oauth_client_secret: str

    @property
    def is_app_configured(self):
        return bool(self.app_id and self.app_slug and self.app_private_key and self.app_webhook_secret)

    @property
    def is_oauth_configured(self):
        return bool(self.oauth_client_id and self.oauth_client_secret)

    @property
    def is_enterprise(self):
        return self.host_url != GITHUB_DOT_COM


def get_github_settings():
    """Read the integration settings from instance configuration, falling back to the environment.

    Instance configuration rows are seeded from the environment the first time
    `configure_instance` runs; an empty row still lets a later env var take effect.
    """
    values = get_configuration_value([{"key": key, "default": os.environ.get(key)} for key in CONFIG_KEYS])
    config = {key: (value or os.environ.get(key) or "") for key, value in zip(CONFIG_KEYS, values)}
    host_url = normalize_host_url(config["GITHUB_INTEGRATION_HOST_URL"])
    webhook_base_url = config["GITHUB_INTEGRATION_WEBHOOK_BASE_URL"] or settings.WEB_URL or ""
    return GithubIntegrationSettings(
        host_url=host_url,
        api_url=(config["GITHUB_INTEGRATION_API_URL"] or api_url_for_host(host_url)).rstrip("/"),
        webhook_base_url=webhook_base_url.rstrip("/"),
        app_id=str(config["GITHUB_APP_ID"]).strip(),
        app_slug=config["GITHUB_APP_SLUG"].strip(),
        app_private_key=normalize_private_key(config["GITHUB_APP_PRIVATE_KEY"]),
        app_webhook_secret=config["GITHUB_APP_WEBHOOK_SECRET"],
        app_client_id=config["GITHUB_APP_CLIENT_ID"].strip(),
        app_client_secret=config["GITHUB_APP_CLIENT_SECRET"],
        oauth_client_id=config["GITHUB_INTEGRATION_OAUTH_CLIENT_ID"].strip(),
        oauth_client_secret=config["GITHUB_INTEGRATION_OAUTH_CLIENT_SECRET"],
    )

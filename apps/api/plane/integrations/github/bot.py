# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import uuid
from urllib.parse import urlparse

# Django imports
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError

# Module imports
from plane.db.models import BotTypeEnum, User


def get_github_bot_user(workspace_id):
    """The per-workspace bot that authors state changes and work items coming from GitHub."""
    username = f"github_bot_{workspace_id}"
    user = User.objects.filter(username=username).first()
    if user:
        return user
    domain = urlparse(settings.WEB_URL or "https://plane.so").hostname or "plane.so"
    try:
        return User.objects.create(
            username=username,
            display_name="GitHub",
            first_name="GitHub",
            last_name="",
            is_bot=True,
            bot_type=BotTypeEnum.GITHUB,
            email=f"{username}@{domain}",
            password=make_password(uuid.uuid4().hex),
            is_password_autoset=True,
        )
    except IntegrityError:
        # Another worker created it first
        return User.objects.get(username=username)

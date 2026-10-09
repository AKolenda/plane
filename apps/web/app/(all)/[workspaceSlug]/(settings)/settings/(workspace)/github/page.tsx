/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
// components
import { NotAuthorizedView } from "@/components/auth-screens/not-authorized-view";
import { PageHead } from "@/components/core/page-title";
import { GithubWorkspaceSettings } from "@/components/github-integration";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useWorkspace } from "@/hooks/store/use-workspace";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";
import { GithubWorkspaceSettingsHeader } from "./header";

function GithubWorkspaceSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug } = params;
  const { t } = useTranslation();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const { currentWorkspace } = useWorkspace();
  const canPerformWorkspaceAdminActions = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.WORKSPACE);

  const pageTitle = currentWorkspace?.name ? `${currentWorkspace.name} - ${t("github_integration.name")}` : undefined;

  if (workspaceUserInfo && !canPerformWorkspaceAdminActions) {
    return <NotAuthorizedView section="settings" className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<GithubWorkspaceSettingsHeader />}>
      <PageHead title={pageTitle} />
      {canPerformWorkspaceAdminActions && <GithubWorkspaceSettings workspaceSlug={workspaceSlug} />}
    </SettingsContentWrapper>
  );
}

export default observer(GithubWorkspaceSettingsPage);

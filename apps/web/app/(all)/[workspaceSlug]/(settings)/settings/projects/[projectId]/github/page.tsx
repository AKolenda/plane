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
import { GithubStateMappingSettings } from "@/components/github-integration";
import { SettingsContentWrapper } from "@/components/settings/content-wrapper";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
// local imports
import type { Route } from "./+types/page";
import { GithubProjectSettingsHeader } from "./header";

function GithubProjectSettingsPage({ params }: Route.ComponentProps) {
  const { workspaceSlug, projectId } = params;
  const { t } = useTranslation();
  const { currentProjectDetails } = useProject();
  const { workspaceUserInfo, allowPermissions } = useUserPermissions();
  const canPerformProjectAdminActions = allowPermissions(
    [EUserPermissions.ADMIN],
    EUserPermissionsLevel.PROJECT,
    workspaceSlug,
    projectId
  );

  const pageTitle = currentProjectDetails?.name
    ? `${currentProjectDetails.name} - ${t("github_integration.name")}`
    : undefined;

  if (workspaceUserInfo && !canPerformProjectAdminActions) {
    return <NotAuthorizedView section="settings" isProjectView className="h-auto" />;
  }

  return (
    <SettingsContentWrapper header={<GithubProjectSettingsHeader />}>
      <PageHead title={pageTitle} />
      {canPerformProjectAdminActions && (
        <GithubStateMappingSettings workspaceSlug={workspaceSlug} projectId={projectId} />
      )}
    </SettingsContentWrapper>
  );
}

export default observer(GithubProjectSettingsPage);

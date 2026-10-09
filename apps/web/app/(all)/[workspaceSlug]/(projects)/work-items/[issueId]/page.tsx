/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTheme } from "next-themes";
import { redirect } from "react-router";
import { useTranslation } from "@plane/i18n";
// assets
import emptyIssueDark from "@/app/assets/empty-state/search/issues-dark.webp?url";
import emptyIssueLight from "@/app/assets/empty-state/search/issues-light.webp?url";
// components
import { EmptyState } from "@/components/common/empty-state";
import { LogoSpinner } from "@/components/common/logo-spinner";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// services
import { WorkItemLocateService, workItemPath } from "@/services/work-item-locate.service";
// types
import type { Route } from "./+types/page";

const locateService = new WorkItemLocateService();

/**
 * `/<workspace>/work-items/<id>`: the stable link handed to notifications, digests, webhooks and
 * imports. It keeps working after a project's identifier is renamed because it resolves the work
 * item by id at open time, then redirects to its current page.
 */
export async function clientLoader({ params }: Route.ClientLoaderArgs) {
  const { workspaceSlug, issueId } = params;

  try {
    const location = await locateService.locate(workspaceSlug, issueId);

    if (location) {
      throw redirect(workItemPath(workspaceSlug, location));
    }

    return { error: true, workspaceSlug };
  } catch (error) {
    // If it's a redirect, rethrow it
    if (error instanceof Response) {
      throw error;
    }
    // Otherwise return error state
    return { error: true, workspaceSlug };
  }
}

export default function WorkItemLinkPage({ loaderData }: Route.ComponentProps) {
  const router = useAppRouter();
  const { t } = useTranslation();
  const { resolvedTheme } = useTheme();

  if (loaderData.error) {
    return (
      <div className="flex size-full items-center justify-center">
        <EmptyState
          image={resolvedTheme === "dark" ? emptyIssueDark : emptyIssueLight}
          title={t("issue.empty_state.issue_detail.title")}
          description={t("issue.empty_state.issue_detail.description")}
          primaryButton={{
            text: t("issue.empty_state.issue_detail.primary_button.text"),
            onClick: () => router.push(`/${loaderData.workspaceSlug}/workspace-views/all-issues/`),
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex size-full items-center justify-center">
      <LogoSpinner />
    </div>
  );
}

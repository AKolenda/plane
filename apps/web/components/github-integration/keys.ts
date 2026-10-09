/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export const githubIntegrationKey = (workspaceSlug: string) => `GITHUB_INTEGRATION_${workspaceSlug}`;
export const githubRepositoriesKey = (workspaceSlug: string) => `GITHUB_REPOSITORIES_${workspaceSlug}`;
export const githubAvailableRepositoriesKey = (workspaceSlug: string, connectionId: string) =>
  `GITHUB_AVAILABLE_REPOSITORIES_${workspaceSlug}_${connectionId}`;
export const githubStateMappingsKey = (projectId: string) => `GITHUB_STATE_MAPPINGS_${projectId}`;
export const githubIssuePullRequestsKey = (issueId: string) => `GITHUB_ISSUE_PULL_REQUESTS_${issueId}`;

/** Flatten a DRF error body (`{"field": ["msg"]}`, nested lists, or `{"error": "msg"}`) into one line. */
export function formatApiError(error: unknown): string | undefined {
  const messages: string[] = [];
  const collect = (value: unknown) => {
    if (typeof value === "string") messages.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  collect(error);
  return messages.length ? messages.join(" ") : undefined;
}

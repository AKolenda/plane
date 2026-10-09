/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
// plane imports
import { Collapsible } from "@makeplane/propel/components/collapsible";
import { GitMergeOutline, GitPullRequestOutline } from "@makeplane/propel/icons";
import { useTranslation } from "@plane/i18n";
import type { TGithubPullRequest, TGithubPullRequestState } from "@plane/types";
import { cn } from "@plane/utils";
// services
import { GithubIntegrationService } from "@/services/integrations";
// local imports
import { githubIssuePullRequestsKey } from "./keys";

const githubService = new GithubIntegrationService();

const STATE_STYLES: Record<TGithubPullRequestState, string> = {
  open: "text-success-primary",
  draft: "text-placeholder",
  merged: "text-accent-primary",
  closed: "text-danger-primary",
};

function PullRequestRow({ pullRequest }: { pullRequest: TGithubPullRequest }) {
  const { t } = useTranslation();
  const StateIcon = pullRequest.state === "merged" ? GitMergeOutline : GitPullRequestOutline;
  const stateStyle = STATE_STYLES[pullRequest.state];

  return (
    <li className="flex h-10 items-center gap-2.5 rounded-sm border-[0.5px] border-subtle bg-surface-2 px-3 hover:bg-layer-1">
      <StateIcon className={cn("size-4 flex-shrink-0", stateStyle)} />
      <a
        href={pullRequest.html_url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex w-0 flex-1 items-center gap-1.5 text-body-xs-regular"
      >
        <span className="flex-shrink-0 text-tertiary">
          {pullRequest.repository_full_name}#{pullRequest.number}
        </span>
        <span className="truncate">{pullRequest.title}</span>
      </a>
      <span className="hidden flex-shrink-0 truncate text-caption-sm-regular text-placeholder sm:block sm:max-w-40">
        {pullRequest.base_branch}
      </span>
      <span className={cn("w-16 flex-shrink-0 text-end text-caption-md-medium", stateStyle)}>
        {t(`github_integration.pr_states.${pullRequest.state}`)}
      </span>
    </li>
  );
}

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
};

/** Pull requests linked to the work item through `[IDENTIFIER-123]`; renders nothing when there are none. */
export function IssuePullRequestsCollapsible(props: Props) {
  const { workspaceSlug, projectId, issueId } = props;
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);
  const { data: pullRequests } = useSWR(
    githubIssuePullRequestsKey(issueId),
    () => githubService.getIssuePullRequests(workspaceSlug, projectId, issueId),
    { revalidateOnFocus: true, shouldRetryOnError: false }
  );

  if (!pullRequests || pullRequests.length === 0) return null;

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={setIsOpen}
      trigger={
        <span className="inline-flex items-center gap-2">
          {t("github_integration.pull_requests")}
          <span className="text-14 leading-3! text-tertiary">{pullRequests.length}</span>
        </span>
      }
    >
      <ul className="flex flex-col gap-2 py-2">
        {pullRequests.map((pullRequest) => (
          <PullRequestRow key={pullRequest.id} pullRequest={pullRequest} />
        ))}
      </ul>
    </Collapsible>
  );
}

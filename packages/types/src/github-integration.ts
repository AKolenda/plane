/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TGithubAuthType = "app" | "oauth";

export type TGithubIssueSyncMode = "disabled" | "github_to_plane" | "bidirectional";

export type TGithubPullRequestEvent =
  | "drafted"
  | "opened"
  | "review_requested"
  | "ready_for_review"
  | "approved"
  | "merged"
  | "closed";

export type TGithubPullRequestState = "open" | "draft" | "merged" | "closed";

export type TGithubConnection = {
  id: string;
  auth_type: TGithubAuthType;
  host_url: string;
  account_id: number;
  account_login: string;
  account_type: string;
  account_avatar_url: string;
  installation_id: number | null;
  connected_by: string | null;
  created_at: string;
};

export type TGithubIntegration = {
  host_url: string;
  is_enterprise: boolean;
  is_app_configured: boolean;
  is_oauth_configured: boolean;
  app_slug: string;
  connections: TGithubConnection[];
};

export type TGithubAvailableRepository = {
  id: number;
  full_name: string;
  html_url: string;
  private: boolean;
  default_branch: string;
  can_admin: boolean;
  watched_id: string | null;
};

export type TGithubWatchedRepository = {
  id: string;
  connection: string;
  repository_id: number;
  full_name: string;
  html_url: string;
  default_branch: string;
  is_private: boolean;
  project: string | null;
  issue_sync_mode: TGithubIssueSyncMode;
  github_label: string;
  plane_label: string;
  open_state: string | null;
  closed_state: string | null;
  created_at: string;
};

export type TGithubWatchedRepositoryUpdate = Partial<
  Pick<
    TGithubWatchedRepository,
    "project" | "issue_sync_mode" | "github_label" | "plane_label" | "open_state" | "closed_state"
  >
>;

export type TGithubStateMapping = {
  id?: string;
  event: TGithubPullRequestEvent;
  base_branch: string;
  state_id: string;
};

export type TGithubPullRequest = {
  id: string;
  number: number;
  title: string;
  html_url: string;
  state: TGithubPullRequestState;
  base_branch: string;
  head_branch: string;
  author_login: string;
  last_event: TGithubPullRequestEvent | "";
  repository_full_name: string;
  opened_at: string | null;
  merged_at: string | null;
  closed_at: string | null;
  updated_at: string;
};

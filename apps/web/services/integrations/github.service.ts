/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  TGithubAuthType,
  TGithubAvailableRepository,
  TGithubIntegration,
  TGithubPullRequest,
  TGithubStateMapping,
  TGithubWatchedRepository,
  TGithubWatchedRepositoryUpdate,
} from "@plane/types";
import { APIService } from "@/services/api.service";

export class GithubIntegrationService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/integrations/github`;
  }

  async getIntegration(workspaceSlug: string): Promise<TGithubIntegration> {
    return this.get(`${this.base(workspaceSlug)}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getConnectUrl(workspaceSlug: string, authType: TGithubAuthType): Promise<{ url: string }> {
    return this.post(`${this.base(workspaceSlug)}/connect/`, { auth_type: authType })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async disconnect(workspaceSlug: string, connectionId: string): Promise<void> {
    return this.delete(`${this.base(workspaceSlug)}/connections/${connectionId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getAvailableRepositories(workspaceSlug: string, connectionId: string): Promise<TGithubAvailableRepository[]> {
    return this.get(`${this.base(workspaceSlug)}/connections/${connectionId}/available-repositories/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getRepositories(workspaceSlug: string): Promise<TGithubWatchedRepository[]> {
    return this.get(`${this.base(workspaceSlug)}/repositories/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async watchRepository(
    workspaceSlug: string,
    connectionId: string,
    repositoryId: number
  ): Promise<TGithubWatchedRepository> {
    return this.post(`${this.base(workspaceSlug)}/repositories/`, {
      connection_id: connectionId,
      repository_id: repositoryId,
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateRepository(
    workspaceSlug: string,
    repositoryId: string,
    data: TGithubWatchedRepositoryUpdate
  ): Promise<TGithubWatchedRepository> {
    return this.patch(`${this.base(workspaceSlug)}/repositories/${repositoryId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async unwatchRepository(workspaceSlug: string, repositoryId: string): Promise<void> {
    return this.delete(`${this.base(workspaceSlug)}/repositories/${repositoryId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getStateMappings(workspaceSlug: string, projectId: string): Promise<TGithubStateMapping[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/integrations/github/state-mappings/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async saveStateMappings(
    workspaceSlug: string,
    projectId: string,
    mappings: TGithubStateMapping[]
  ): Promise<TGithubStateMapping[]> {
    return this.put(`/api/workspaces/${workspaceSlug}/projects/${projectId}/integrations/github/state-mappings/`, {
      mappings,
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getIssuePullRequests(workspaceSlug: string, projectId: string, issueId: string): Promise<TGithubPullRequest[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/github/pull-requests/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

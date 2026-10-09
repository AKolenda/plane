/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";

export type TWorkItemLocation = {
  id: string;
  project_id: string;
  project_identifier: string;
  sequence_id: number;
  is_archived: boolean;
};

export class WorkItemLocateService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  /** Where a work item lives now, by id, so links survive project identifier renames. */
  async locate(workspaceSlug: string, issueId: string): Promise<TWorkItemLocation> {
    return this.get(`/api/workspaces/${workspaceSlug}/work-items/${issueId}/locate/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

/** The page a located work item opens on. */
export function workItemPath(workspaceSlug: string, location: TWorkItemLocation) {
  return location.is_archived
    ? `/${workspaceSlug}/projects/${location.project_id}/archives/issues/${location.id}`
    : `/${workspaceSlug}/browse/${location.project_identifier}-${location.sequence_id}`;
}

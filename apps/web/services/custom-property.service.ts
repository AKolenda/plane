/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  TCustomProperty,
  TCustomPropertyPayload,
  TCustomPropertyValues,
  TProjectCustomPropertyValues,
} from "@plane/types";
import { APIService } from "@/services/api.service";

export class CustomPropertyService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  async list(workspaceSlug: string, projectId: string): Promise<TCustomProperty[]> {
    return this.get(`${this.base(workspaceSlug, projectId)}/custom-properties/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async create(workspaceSlug: string, projectId: string, data: TCustomPropertyPayload): Promise<TCustomProperty> {
    return this.post(`${this.base(workspaceSlug, projectId)}/custom-properties/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async update(
    workspaceSlug: string,
    projectId: string,
    propertyId: string,
    data: TCustomPropertyPayload
  ): Promise<TCustomProperty> {
    return this.patch(`${this.base(workspaceSlug, projectId)}/custom-properties/${propertyId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(workspaceSlug: string, projectId: string, propertyId: string): Promise<void> {
    return this.delete(`${this.base(workspaceSlug, projectId)}/custom-properties/${propertyId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async projectValues(workspaceSlug: string, projectId: string): Promise<TProjectCustomPropertyValues> {
    return this.get(`${this.base(workspaceSlug, projectId)}/custom-property-values/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async setIssueValues(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    values: TCustomPropertyValues
  ): Promise<TCustomPropertyValues> {
    return this.patch(`${this.base(workspaceSlug, projectId)}/issues/${issueId}/custom-property-values/`, values)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}

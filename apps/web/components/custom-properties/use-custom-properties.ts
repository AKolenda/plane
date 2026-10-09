/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import useSWR from "swr";
import type { TCustomPropertyValues } from "@plane/types";
import { CustomPropertyService } from "@/services/custom-property.service";

export const customPropertyService = new CustomPropertyService();

export const customPropertiesKey = (projectId: string) => `CUSTOM_PROPERTIES_${projectId}`;
export const customPropertyValuesKey = (projectId: string) => `CUSTOM_PROPERTY_VALUES_${projectId}`;

/** The project's property definitions; every caller shares one request through the SWR cache. */
export function useCustomProperties(workspaceSlug: string | undefined, projectId: string | undefined) {
  return useSWR(
    workspaceSlug && projectId ? customPropertiesKey(projectId) : null,
    () => customPropertyService.list(workspaceSlug!, projectId!),
    { revalidateOnFocus: false }
  );
}

/** Every work item's values in the project, keyed by work item id, shared by rows of a layout. */
export function useCustomPropertyValues(workspaceSlug: string | undefined, projectId: string | undefined) {
  const result = useSWR(
    workspaceSlug && projectId ? customPropertyValuesKey(projectId) : null,
    () => customPropertyService.projectValues(workspaceSlug!, projectId!),
    { revalidateOnFocus: false }
  );

  /** Save values for one work item and merge the response into the shared cache. */
  const setIssueValues = async (issueId: string, values: TCustomPropertyValues) => {
    if (!workspaceSlug || !projectId) return;
    const saved = await customPropertyService.setIssueValues(workspaceSlug, projectId, issueId, values);
    await result.mutate((current) => ({ ...current, [issueId]: saved }), false);
  };

  return { ...result, setIssueValues };
}

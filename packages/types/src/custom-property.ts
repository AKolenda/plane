/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TCustomPropertyType = "text" | "number" | "date" | "select" | "user";

export type TCustomPropertyOption = {
  id?: string;
  label: string;
};

export type TCustomProperty = {
  id: string;
  name: string;
  key: string;
  property_type: TCustomPropertyType;
  description: string;
  options: Required<TCustomPropertyOption>[];
  sort_order: number;
  project: string;
};

/** Body for creating or updating a property; options without an id are new. */
export type TCustomPropertyPayload = {
  name?: string;
  property_type?: TCustomPropertyType;
  description?: string;
  options?: TCustomPropertyOption[];
};

/** Raw values: text, number, `YYYY-MM-DD`, select option id, or user id. */
export type TCustomPropertyValue = string | number | null;

/** `{ propertyId: value }` for one work item. */
export type TCustomPropertyValues = Record<string, TCustomPropertyValue>;

/** `{ issueId: { propertyId: value } }` for a project. */
export type TProjectCustomPropertyValues = Record<string, TCustomPropertyValues>;

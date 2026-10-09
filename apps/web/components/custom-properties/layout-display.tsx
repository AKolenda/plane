/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TCustomProperty, TCustomPropertyValue, TIssue } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
// hooks
import { useMember } from "@/hooks/store/use-member";
// local imports
import { CustomPropertyEditor } from "./issue-custom-properties";
import { useCustomProperties, useCustomPropertyValues } from "./use-custom-properties";

const MAX_CHIPS = 2;
const CHIP_CLASS =
  "flex h-5 max-w-40 flex-shrink-0 items-center gap-1 overflow-hidden rounded-sm border-[0.5px] border-strong px-2 text-caption-sm-regular";

/** Readable text for a raw value, or null when it is empty or no longer resolves. */
export function useFormatCustomPropertyValue() {
  const { getUserDetails } = useMember();
  return (property: TCustomProperty, value: TCustomPropertyValue): string | null => {
    if (value === null || value === undefined || value === "") return null;
    switch (property.property_type) {
      case "date":
        return renderFormattedDate(String(value)) ?? String(value);
      case "select":
        return property.options.find((option) => option.id === value)?.label ?? null;
      case "user":
        return getUserDetails(String(value))?.display_name ?? null;
      default:
        return String(value);
    }
  };
}

/** Compact "Name: value" chips for list and kanban rows; only properties with a value appear. */
export const IssueCustomPropertyChips = observer(function IssueCustomPropertyChips(props: { issue: TIssue }) {
  const { issue } = props;
  const { workspaceSlug } = useParams();
  const slug = workspaceSlug?.toString();
  const { data: properties } = useCustomProperties(slug, issue.project_id ?? undefined);
  const { data: values } = useCustomPropertyValues(slug, issue.project_id ?? undefined);
  const format = useFormatCustomPropertyValue();

  if (!properties?.length) return null;
  const issueValues = values?.[issue.id] ?? {};
  const filled = properties
    .map((property) => ({ property, text: format(property, issueValues[property.id] ?? null) }))
    .filter((item): item is { property: TCustomProperty; text: string } => item.text !== null);
  const shown = filled.slice(0, MAX_CHIPS);
  const hidden = filled.slice(MAX_CHIPS);

  return (
    <>
      {shown.map(({ property, text }) => (
        <div key={property.id} title={`${property.name}: ${text}`} className={CHIP_CLASS}>
          <span className="flex-shrink-0 text-tertiary">{property.name}</span>
          <span className="truncate">{text}</span>
        </div>
      ))}
      {hidden.length > 0 && (
        <div title={hidden.map(({ property, text }) => `${property.name}: ${text}`).join("\n")} className={CHIP_CLASS}>
          +{hidden.length}
        </div>
      )}
    </>
  );
});

/**
 * Spreadsheet header cells, one per custom property. Only project-scoped spreadsheets show them,
 * because workspace views mix projects with different properties.
 */
export const CustomPropertyHeaderCells = observer(function CustomPropertyHeaderCells() {
  const { workspaceSlug, projectId } = useParams();
  const { data: properties } = useCustomProperties(workspaceSlug?.toString(), projectId?.toString());
  if (!projectId || !properties?.length) return null;
  return (
    <>
      {properties.map((property) => (
        <th
          key={property.id}
          className="h-11 min-w-36 border-r-[0.5px] border-subtle bg-layer-1 px-4 text-start text-13 font-medium"
        >
          <span className="truncate">{property.name}</span>
        </th>
      ))}
    </>
  );
});

export const CustomPropertyCells = observer(function CustomPropertyCells(props: { issue: TIssue; disabled: boolean }) {
  const { issue, disabled } = props;
  const { t } = useTranslation();
  const { workspaceSlug, projectId } = useParams();
  const slug = workspaceSlug?.toString();
  const { data: properties } = useCustomProperties(slug, projectId?.toString());
  const { data: values, setIssueValues } = useCustomPropertyValues(slug, projectId?.toString());
  if (!projectId || !properties?.length || !issue.project_id) return null;
  const issueValues = values?.[issue.id] ?? {};

  const save = async (property: TCustomProperty, value: TCustomPropertyValue) => {
    try {
      await setIssueValues(issue.id, { [property.id]: value });
    } catch (error) {
      setToast({
        type: "error",
        title: t("common.something_went_wrong"),
        message: (error as { error?: string } | undefined)?.error,
      });
    }
  };

  return (
    <>
      {properties.map((property) => (
        <td
          key={property.id}
          className="h-11 min-w-36 border-r-[1px] border-subtle px-1 text-13 after:absolute after:bottom-[-1px] after:w-full after:border after:border-subtle"
        >
          <CustomPropertyEditor
            property={property}
            projectId={issue.project_id!}
            value={issueValues[property.id] ?? null}
            disabled={disabled}
            onSave={(value) => void save(property, value)}
          />
        </td>
      ))}
    </>
  );
});

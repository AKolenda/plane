/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Input } from "@makeplane/propel/components/input";
import { Select, SelectContent, SelectItem, SelectList, SelectTrigger } from "@makeplane/propel/components/select";
import { PropertiesOutline } from "@makeplane/propel/icons";
import { DateSelect } from "@plane/blocks/property-select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TCustomProperty, TCustomPropertyValue } from "@plane/types";
import { getDate, renderFormattedPayloadDate } from "@plane/utils";
// components
import { SidebarPropertyListItem } from "@/components/common/layout/sidebar/property-list-item";
import { MemberSelect } from "@/components/dropdowns/member/member-select";
// local imports
import { useCustomProperties, useCustomPropertyValues } from "./use-custom-properties";

const NONE = "__none__";

function errorMessage(error: unknown) {
  return (error as { error?: string } | undefined)?.error;
}

function TextValueInput(props: {
  type: "text" | "number";
  value: TCustomPropertyValue;
  placeholder: string;
  ariaLabel: string;
  disabled: boolean;
  onSave: (value: TCustomPropertyValue) => void;
}) {
  const { type, value, placeholder, ariaLabel, disabled, onSave } = props;
  const current = value === null || value === undefined ? "" : String(value);
  const [draft, setDraft] = useState(current);
  useEffect(() => setDraft(current), [current]);

  const commit = () => {
    const next = draft.trim();
    if (next === current) return;
    onSave(next === "" ? null : type === "number" ? Number(next) : next);
  };

  return (
    <div className="w-full min-w-0 *:w-full">
      <Input
        size="md"
        type={type}
        value={draft}
        placeholder={placeholder}
        aria-label={ariaLabel}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setDraft(current);
        }}
      />
    </div>
  );
}

export const CustomPropertyEditor = observer(function CustomPropertyEditor(props: {
  property: TCustomProperty;
  projectId: string;
  value: TCustomPropertyValue;
  disabled: boolean;
  onSave: (value: TCustomPropertyValue) => void;
}) {
  const { property, projectId, value, disabled, onSave } = props;
  const { t } = useTranslation();
  const placeholder = t("custom_properties.empty");

  switch (property.property_type) {
    case "text":
    case "number":
      return (
        <TextValueInput
          type={property.property_type}
          value={value}
          placeholder={placeholder}
          ariaLabel={property.name}
          disabled={disabled}
          onSave={onSave}
        />
      );
    case "date":
      return (
        <DateSelect
          placeholder={placeholder}
          value={typeof value === "string" ? (getDate(value) ?? null) : null}
          onChange={(date) => onSave(date ? (renderFormattedPayloadDate(date) ?? null) : null)}
          disabled={disabled}
          clearable
          variant="select-ghost-md"
        />
      );
    case "select": {
      const options = [
        { value: NONE, label: placeholder },
        ...property.options.map((o) => ({ value: o.id, label: o.label })),
      ];
      return (
        <div className="w-full min-w-0 *:w-full *:min-w-0!">
          <Select<string>
            items={options}
            value={typeof value === "string" ? value : NONE}
            onValueChange={(next) => onSave(!next || next === NONE ? null : next)}
            disabled={disabled}
          >
            <SelectTrigger size="md" variant="ghost" aria-label={property.name} />
            <SelectContent side="bottom" align="start">
              <SelectList>
                {options.map((option) => (
                  <SelectItem key={option.value} value={option.value} size="md" label={option.label} />
                ))}
              </SelectList>
            </SelectContent>
          </Select>
        </div>
      );
    }
    case "user":
      return (
        <MemberSelect
          value={typeof value === "string" ? value : null}
          onChange={(id) => onSave(id || null)}
          projectId={projectId}
          placeholder={placeholder}
          variant="select-ghost-md"
          clearable
          disabled={disabled}
        />
      );
    default:
      return null;
  }
});

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled: boolean;
};

/** One sidebar row per project custom property; renders nothing for projects without any. */
export const IssueCustomPropertiesSidebar = observer(function IssueCustomPropertiesSidebar(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled } = props;
  const { t } = useTranslation();
  const { data: properties } = useCustomProperties(workspaceSlug, projectId);
  const { data: values, setIssueValues } = useCustomPropertyValues(workspaceSlug, projectId);

  if (!properties?.length) return null;
  const issueValues = values?.[issueId] ?? {};

  const save = async (property: TCustomProperty, value: TCustomPropertyValue) => {
    try {
      await setIssueValues(issueId, { [property.id]: value });
    } catch (error) {
      setToast({ type: "error", title: t("common.something_went_wrong"), message: errorMessage(error) });
    }
  };

  return (
    <>
      {properties.map((property) => (
        <SidebarPropertyListItem key={property.id} icon={PropertiesOutline} label={property.name}>
          <CustomPropertyEditor
            property={property}
            projectId={projectId}
            value={issueValues[property.id] ?? null}
            disabled={disabled}
            onSave={(value) => void save(property, value)}
          />
        </SidebarPropertyListItem>
      ))}
    </>
  );
});

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { mutate } from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TCustomProperty } from "@plane/types";
// components
import { ResizableTable, TABLE_CELL_CLASS } from "@/components/common/resizable-table";
import { SettingsHeading } from "@/components/settings/heading";
// local imports
import { CustomPropertyFormDialog } from "./property-form-dialog";
import type { TCustomPropertyDraft } from "./property-form-dialog";
import {
  customPropertiesKey,
  customPropertyService,
  customPropertyValuesKey,
  useCustomProperties,
} from "./use-custom-properties";

function errorMessage(error: unknown) {
  const details = error as Record<string, unknown> | undefined;
  if (!details) return undefined;
  return Object.values(details)
    .flat()
    .filter((value): value is string => typeof value === "string")
    .join(" ");
}

type Props = {
  workspaceSlug: string;
  projectId: string;
};

export const CustomPropertiesSettings = observer(function CustomPropertiesSettings(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { t } = useTranslation();
  const { data: properties, mutate: mutateProperties } = useCustomProperties(workspaceSlug, projectId);
  const [editing, setEditing] = useState<TCustomProperty | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [toDelete, setToDelete] = useState<TCustomProperty | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const openForm = (property: TCustomProperty | null) => {
    setEditing(property);
    setIsFormOpen(true);
  };

  const handleSubmit = async (draft: TCustomPropertyDraft) => {
    try {
      if (editing) await customPropertyService.update(workspaceSlug, projectId, editing.id, draft);
      else await customPropertyService.create(workspaceSlug, projectId, draft);
      await Promise.all([mutateProperties(), mutate(customPropertyValuesKey(projectId))]);
    } catch (error) {
      setToast({ type: "error", title: t("common.something_went_wrong"), message: errorMessage(error) });
      throw error;
    }
  };

  const handleDelete = async () => {
    if (!toDelete) return;
    setIsDeleting(true);
    try {
      await customPropertyService.remove(workspaceSlug, projectId, toDelete.id);
      await Promise.all([mutate(customPropertiesKey(projectId)), mutate(customPropertyValuesKey(projectId))]);
      setToDelete(null);
    } catch (error) {
      setToast({ type: "error", title: t("common.something_went_wrong"), message: errorMessage(error) });
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="flex w-full flex-col gap-6">
      <SettingsHeading
        title={t("custom_properties.title")}
        control={
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label={t("custom_properties.add")}
            onClick={() => openForm(null)}
          />
        }
      />
      {properties && properties.length === 0 && (
        <p className="text-body-xs-regular text-tertiary">{t("custom_properties.none")}</p>
      )}
      {properties && properties.length > 0 && (
        <ResizableTable
          resizeLabel={t("github_integration.resize_column")}
          columns={[
            { key: "name", label: t("common.name"), width: 200 },
            { key: "key", label: t("custom_properties.key"), width: 160 },
            { key: "type", label: t("custom_properties.type"), width: 110 },
            { key: "options", label: t("custom_properties.options"), width: 260 },
            { key: "actions", label: t("common.actions.edit"), width: 150, hideLabel: true },
          ]}
        >
          {properties.map((property) => (
            <tr key={property.id}>
              <td className={TABLE_CELL_CLASS}>{property.name}</td>
              <td className={`${TABLE_CELL_CLASS} font-mono text-tertiary`}>{property.key}</td>
              <td className={TABLE_CELL_CLASS}>{t(`custom_properties.types.${property.property_type}`)}</td>
              <td className={`${TABLE_CELL_CLASS} text-tertiary`}>
                {property.options.map((option) => option.label).join(", ")}
              </td>
              <td className={`${TABLE_CELL_CLASS} text-end`}>
                <span className="inline-flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("common.actions.edit")}
                    onClick={() => openForm(property)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("common.actions.delete")}
                    onClick={() => setToDelete(property)}
                  />
                </span>
              </td>
            </tr>
          ))}
        </ResizableTable>
      )}

      <CustomPropertyFormDialog
        isOpen={isFormOpen}
        property={editing}
        onClose={() => setIsFormOpen(false)}
        onSubmit={handleSubmit}
      />
      <ConfirmDialog
        isOpen={!!toDelete}
        isSubmitting={isDeleting}
        handleClose={() => setToDelete(null)}
        handleSubmit={handleDelete}
        title={t("common.actions.delete")}
        content={t("custom_properties.delete_confirmation", { name: toDelete?.name ?? "" })}
        primaryButtonText={{ loading: t("common.actions.delete"), default: t("common.actions.delete") }}
      />
    </div>
  );
});

/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { Input, InputGroup } from "@makeplane/propel/components/input";
import { Select, SelectContent, SelectItem, SelectList, SelectTrigger } from "@makeplane/propel/components/select";
import { useTranslation } from "@plane/i18n";
import type { TCustomProperty, TCustomPropertyOption, TCustomPropertyType } from "@plane/types";

export const CUSTOM_PROPERTY_TYPES: TCustomPropertyType[] = ["text", "number", "date", "select", "user"];

export type TCustomPropertyDraft = {
  name: string;
  property_type: TCustomPropertyType;
  options: TCustomPropertyOption[];
};

// Rows added in the dialog get a temporary id so React can key them; the server assigns the real one
let nextNewOptionId = 0;
const newOption = (): TCustomPropertyOption => ({ id: `new-${nextNewOptionId++}`, label: "" });
const isNewOption = (option: TCustomPropertyOption) => !option.id || option.id.startsWith("new-");

type Props = {
  isOpen: boolean;
  property: TCustomProperty | null;
  onClose: () => void;
  onSubmit: (draft: TCustomPropertyDraft) => Promise<void>;
};

export function CustomPropertyFormDialog(props: Props) {
  const { isOpen, property, onClose, onSubmit } = props;
  const { t } = useTranslation();
  const [draft, setDraft] = useState<TCustomPropertyDraft>({ name: "", property_type: "text", options: [] });
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setDraft(
      property
        ? { name: property.name, property_type: property.property_type, options: property.options }
        : { name: "", property_type: "text", options: [] }
    );
  }, [isOpen, property]);

  const isSelect = draft.property_type === "select";
  const options = draft.options;
  const isValid = draft.name.trim() !== "" && (!isSelect || options.some((option) => option.label.trim()));
  const typeOptions = CUSTOM_PROPERTY_TYPES.map((type) => ({
    value: type,
    label: t(`custom_properties.types.${type}`),
  }));

  const setOption = (index: number, label: string) =>
    setDraft((current) => ({
      ...current,
      options: options.map((option, i) => (i === index ? { ...option, label } : option)),
    }));

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await onSubmit({
        ...draft,
        name: draft.name.trim(),
        options: isSelect
          ? options
              .filter((option) => option.label.trim())
              .map((option) => (isNewOption(option) ? { label: option.label } : option))
          : [],
      });
      onClose();
    } catch {
      // The caller reports the error; keep the dialog open for corrections
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="xs">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (isValid) void handleSubmit();
          }}
        >
          <DialogMain>
            <DialogHeader>
              <DialogHeading>
                <DialogTitle>{property ? t("custom_properties.edit") : t("custom_properties.add")}</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody>
              <div className="flex flex-col gap-3">
                <label className="flex flex-col gap-1 text-body-xs-medium text-secondary">
                  {t("common.name")}
                  <InputGroup size="lg">
                    <Input
                      size="lg"
                      value={draft.name}
                      onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                    />
                  </InputGroup>
                </label>
                <div className="flex flex-col gap-1 text-body-xs-medium text-secondary">
                  {t("custom_properties.type")}
                  <div className="*:w-full *:min-w-0!">
                    <Select<TCustomPropertyType>
                      items={typeOptions}
                      value={draft.property_type}
                      disabled={!!property}
                      onValueChange={(type) =>
                        type &&
                        setDraft((current) => ({
                          ...current,
                          property_type: type,
                          options: type === "select" && current.options.length === 0 ? [newOption()] : current.options,
                        }))
                      }
                    >
                      <SelectTrigger size="lg" aria-label={t("custom_properties.type")} />
                      <SelectContent side="bottom" align="start">
                        <SelectList>
                          {typeOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value} size="md" label={option.label} />
                          ))}
                        </SelectList>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                {isSelect && (
                  <div className="flex flex-col gap-1 text-body-xs-medium text-secondary">
                    {t("custom_properties.options")}
                    {options.map((option, index) => (
                      <div key={option.id} className="flex items-center gap-2">
                        <div className="min-w-0 flex-1">
                          <InputGroup size="md">
                            <Input
                              size="md"
                              value={option.label}
                              aria-label={`${t("custom_properties.options")} ${index + 1}`}
                              onChange={(event) => setOption(index, event.target.value)}
                            />
                          </InputGroup>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          stretch="auto"
                          label={t("common.remove")}
                          disabled={options.length === 1}
                          onClick={() =>
                            setDraft((current) => ({ ...current, options: options.filter((_, i) => i !== index) }))
                          }
                        />
                      </div>
                    ))}
                    <div>
                      <Button
                        variant="ghost"
                        size="sm"
                        stretch="auto"
                        label={t("custom_properties.add_option")}
                        onClick={() => setDraft((current) => ({ ...current, options: [...options, newOption()] }))}
                      />
                    </div>
                  </div>
                )}
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            <Button variant="secondary" size="sm" stretch="auto" label={t("common.cancel")} onClick={onClose} />
            <Button
              variant="primary"
              type="submit"
              size="sm"
              stretch="auto"
              label={t("save")}
              loading={isSubmitting}
              disabled={!isValid}
            />
          </DialogActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}

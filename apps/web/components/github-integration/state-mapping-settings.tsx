/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { Input } from "@makeplane/propel/components/input";
import { Select, SelectContent, SelectItem, SelectList, SelectTrigger } from "@makeplane/propel/components/select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TGithubPullRequestEvent, TGithubStateMapping } from "@plane/types";
// components
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
// services
import { GithubIntegrationService } from "@/services/integrations";
// local imports
import { formatApiError, githubStateMappingsKey } from "./keys";
import { CELL_CONTROL_CLASS, ResizableTable, TABLE_CELL_CLASS } from "./resizable-table";

const githubService = new GithubIntegrationService();

export const GITHUB_PULL_REQUEST_EVENTS: TGithubPullRequestEvent[] = [
  "drafted",
  "opened",
  "review_requested",
  "ready_for_review",
  "approved",
  "merged",
  "closed",
];

type TDraftMapping = TGithubStateMapping & { key: string };

let draftKey = 0;
const toDraft = (mapping: TGithubStateMapping): TDraftMapping => ({ ...mapping, key: `mapping-${draftKey++}` });

function TableSelect<T extends string>(props: {
  value: T | null;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  ariaLabel: string;
  placeholder?: string;
}) {
  const { value, options, onChange, ariaLabel, placeholder } = props;
  return (
    <div className={CELL_CONTROL_CLASS}>
      <Select<T> items={options} value={value} onValueChange={(next) => next && onChange(next)}>
        <SelectTrigger size="md" variant="ghost" aria-label={ariaLabel} placeholder={placeholder} />
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

type Props = {
  workspaceSlug: string;
  projectId: string;
};

export const GithubStateMappingSettings = observer(function GithubStateMappingSettings(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { t } = useTranslation();
  const { getProjectById } = useProject();
  const { fetchProjectStates, getProjectStates } = useProjectState();
  const [drafts, setDrafts] = useState<TDraftMapping[] | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useSWR(`PROJECT_STATES_${projectId}`, () => fetchProjectStates(workspaceSlug, projectId));
  const { data: mappings, mutate } = useSWR(githubStateMappingsKey(projectId), () =>
    githubService.getStateMappings(workspaceSlug, projectId)
  );
  useEffect(() => {
    if (mappings) setDrafts(mappings.map(toDraft));
  }, [mappings]);

  const project = getProjectById(projectId);
  const eventOptions = GITHUB_PULL_REQUEST_EVENTS.map((event) => ({
    value: event,
    label: t(`github_integration.events.${event}`),
  }));
  const stateOptions = (getProjectStates(projectId) ?? []).map((state) => ({ value: state.id, label: state.name }));

  const update = (key: string, data: Partial<TGithubStateMapping>) =>
    setDrafts((current) => current?.map((item) => (item.key === key ? { ...item, ...data } : item)) ?? current);
  const remove = (key: string) => setDrafts((current) => current?.filter((item) => item.key !== key) ?? current);
  const add = () => {
    const used = new Set(drafts?.map((item) => item.event));
    const event = GITHUB_PULL_REQUEST_EVENTS.find((item) => !used.has(item)) ?? "merged";
    setDrafts((current) => [...(current ?? []), toDraft({ event, base_branch: "", state_id: "" })]);
  };

  const isComplete = !!drafts && drafts.every((item) => item.state_id);
  const isDirty =
    !!drafts &&
    !!mappings &&
    JSON.stringify(drafts.map(({ event, base_branch, state_id }) => [event, base_branch.trim(), state_id])) !==
      JSON.stringify(mappings.map(({ event, base_branch, state_id }) => [event, base_branch, state_id]));

  const handleSave = async () => {
    if (!drafts) return;
    setIsSaving(true);
    try {
      const saved = await githubService.saveStateMappings(
        workspaceSlug,
        projectId,
        drafts.map(({ event, base_branch, state_id }) => ({ event, base_branch: base_branch.trim(), state_id }))
      );
      await mutate(saved, false);
      setToast({ type: "success", title: t("github_integration.mappings_saved") });
    } catch (error) {
      setToast({ type: "error", title: t("common.something_went_wrong"), message: formatApiError(error) });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex w-full flex-col gap-6">
      <SettingsHeading
        title={t("github_integration.pull_request_automation")}
        description={t("github_integration.link_syntax", { identifier: project?.identifier ?? "ENG" })}
        control={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="md"
              stretch="auto"
              label={t("github_integration.add_mapping")}
              onClick={add}
            />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={t("github_integration.save")}
              loading={isSaving}
              disabled={!isDirty || !isComplete}
              onClick={() => void handleSave()}
            />
          </div>
        }
      />
      {drafts && drafts.length === 0 ? (
        <p className="text-body-xs-regular text-tertiary">{t("github_integration.no_mappings")}</p>
      ) : (
        drafts && (
          <ResizableTable
            resizeLabel={t("github_integration.resize_column")}
            columns={[
              { key: "event", label: t("github_integration.event"), width: 220 },
              { key: "branch", label: t("github_integration.target_branch"), width: 220 },
              { key: "state", label: t("common.state"), width: 200 },
              { key: "actions", label: t("common.remove"), width: 110, hideLabel: true },
            ]}
          >
            {drafts.map((mapping) => (
              <tr key={mapping.key}>
                <td className={TABLE_CELL_CLASS}>
                  <TableSelect
                    value={mapping.event}
                    options={eventOptions}
                    ariaLabel={t("github_integration.event")}
                    onChange={(event) => update(mapping.key, { event })}
                  />
                </td>
                <td className={TABLE_CELL_CLASS}>
                  <div className={CELL_CONTROL_CLASS}>
                    <Input
                      size="md"
                      value={mapping.base_branch}
                      placeholder={t("github_integration.any_branch")}
                      aria-label={t("github_integration.target_branch")}
                      onChange={(event) => update(mapping.key, { base_branch: event.target.value })}
                    />
                  </div>
                </td>
                <td className={TABLE_CELL_CLASS}>
                  <TableSelect
                    value={mapping.state_id || null}
                    options={stateOptions}
                    ariaLabel={t("common.state")}
                    placeholder={t("integrations.select_state")}
                    onChange={(state_id) => update(mapping.key, { state_id })}
                  />
                </td>
                <td className={`${TABLE_CELL_CLASS} text-end`}>
                  <Button
                    variant="ghost"
                    size="sm"
                    stretch="auto"
                    label={t("common.remove")}
                    onClick={() => remove(mapping.key)}
                  />
                </td>
              </tr>
            ))}
          </ResizableTable>
        )
      )}
    </div>
  );
});

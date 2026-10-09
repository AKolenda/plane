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
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TGithubIssueSyncMode, TGithubWatchedRepository, TGithubWatchedRepositoryUpdate } from "@plane/types";
// hooks
import { useProject } from "@/hooks/store/use-project";
import { useProjectState } from "@/hooks/store/use-project-state";
// services
import { GithubIntegrationService } from "@/services/integrations";
// local imports
import { formatApiError, githubRepositoriesKey } from "./keys";
import { CELL_CONTROL_CLASS, ResizableTable, TABLE_CELL_CLASS } from "./resizable-table";

const githubService = new GithubIntegrationService();
// Base UI selects need a concrete value for "nothing selected"
const NONE = "__none__";

type TOption = { value: string; label: string };

function InlineSelect(props: {
  value: string | null;
  options: TOption[];
  onChange: (value: string | null) => void;
  ariaLabel: string;
  disabled?: boolean;
}) {
  const { value, options, onChange, ariaLabel, disabled } = props;
  return (
    <div className={CELL_CONTROL_CLASS}>
      <Select<string>
        items={options}
        value={value ?? NONE}
        onValueChange={(next) => onChange(!next || next === NONE ? null : next)}
        disabled={disabled}
      >
        <SelectTrigger size="md" variant="ghost" aria-label={ariaLabel} />
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

function LabelInput(props: { value: string; onSave: (value: string) => void; ariaLabel: string; disabled?: boolean }) {
  const { value, onSave, ariaLabel, disabled } = props;
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    const next = draft.trim();
    if (!next) setDraft(value);
    else if (next !== value) onSave(next);
  };
  return (
    <div className={CELL_CONTROL_CLASS}>
      <Input
        size="md"
        value={draft}
        aria-label={ariaLabel}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setDraft(value);
        }}
      />
    </div>
  );
}

const RepositoryRow = observer(function RepositoryRow(props: {
  workspaceSlug: string;
  repository: TGithubWatchedRepository;
  onUpdate: (repository: TGithubWatchedRepository, data: TGithubWatchedRepositoryUpdate) => void;
  onRemove: (repository: TGithubWatchedRepository) => void;
}) {
  const { workspaceSlug, repository, onUpdate, onRemove } = props;
  const { t } = useTranslation();
  const { workspaceProjectIds, getProjectById } = useProject();
  const { fetchProjectStates, getProjectStates } = useProjectState();

  useSWR(repository.project ? `PROJECT_STATES_${repository.project}` : null, () =>
    repository.project ? fetchProjectStates(workspaceSlug, repository.project) : null
  );

  const none: TOption = { value: NONE, label: t("common.none") };
  const projectOptions: TOption[] = [
    none,
    ...(workspaceProjectIds ?? []).map((id) => ({ value: id, label: getProjectById(id)?.name ?? id })),
  ];
  const stateOptions: TOption[] = [
    none,
    ...(getProjectStates(repository.project) ?? []).map((state) => ({ value: state.id, label: state.name })),
  ];
  const syncOptions: { value: TGithubIssueSyncMode; label: string }[] = [
    { value: "disabled", label: t("github_integration.sync_off") },
    { value: "github_to_plane", label: t("github_integration.sync_github_to_plane") },
    { value: "bidirectional", label: t("github_integration.sync_bidirectional") },
  ];
  const isSyncing = repository.issue_sync_mode !== "disabled";

  return (
    <tr>
      <td className={TABLE_CELL_CLASS}>
        <a href={repository.html_url} target="_blank" rel="noopener noreferrer" className="hover:underline">
          {repository.full_name}
        </a>
      </td>
      <td className={TABLE_CELL_CLASS}>
        <InlineSelect
          value={repository.project}
          options={projectOptions}
          ariaLabel={t("common.project")}
          onChange={(project) =>
            onUpdate(repository, project ? { project } : { project: null, issue_sync_mode: "disabled" })
          }
        />
      </td>
      <td className={TABLE_CELL_CLASS}>
        <InlineSelect
          value={repository.issue_sync_mode}
          options={syncOptions}
          ariaLabel={t("github_integration.issue_sync")}
          disabled={!repository.project}
          onChange={(mode) => onUpdate(repository, { issue_sync_mode: (mode ?? "disabled") as TGithubIssueSyncMode })}
        />
      </td>
      <td className={TABLE_CELL_CLASS}>
        <LabelInput
          value={repository.github_label}
          ariaLabel={t("github_integration.github_label")}
          disabled={!isSyncing}
          onSave={(github_label) => onUpdate(repository, { github_label })}
        />
      </td>
      <td className={TABLE_CELL_CLASS}>
        <LabelInput
          value={repository.plane_label}
          ariaLabel={t("github_integration.plane_label")}
          disabled={repository.issue_sync_mode !== "bidirectional"}
          onSave={(plane_label) => onUpdate(repository, { plane_label })}
        />
      </td>
      <td className={TABLE_CELL_CLASS}>
        <InlineSelect
          value={repository.open_state}
          options={stateOptions}
          ariaLabel={t("github_integration.open_state")}
          disabled={!isSyncing}
          onChange={(open_state) => onUpdate(repository, { open_state })}
        />
      </td>
      <td className={TABLE_CELL_CLASS}>
        <InlineSelect
          value={repository.closed_state}
          options={stateOptions}
          ariaLabel={t("github_integration.closed_state")}
          disabled={!isSyncing}
          onChange={(closed_state) => onUpdate(repository, { closed_state })}
        />
      </td>
      <td className={`${TABLE_CELL_CLASS} text-end`}>
        <Button
          variant="ghost"
          size="sm"
          stretch="auto"
          label={t("github_integration.stop_watching")}
          onClick={() => onRemove(repository)}
        />
      </td>
    </tr>
  );
});

export const GithubRepositoriesTable = observer(function GithubRepositoriesTable(props: { workspaceSlug: string }) {
  const { workspaceSlug } = props;
  const { t } = useTranslation();
  const [repositoryToRemove, setRepositoryToRemove] = useState<TGithubWatchedRepository | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);
  const { data: repositories, mutate } = useSWR(githubRepositoriesKey(workspaceSlug), () =>
    githubService.getRepositories(workspaceSlug)
  );

  const showError = (error: unknown) =>
    setToast({ type: "error", title: t("common.something_went_wrong"), message: formatApiError(error) });

  const handleUpdate = async (repository: TGithubWatchedRepository, data: TGithubWatchedRepositoryUpdate) => {
    try {
      const updated = await githubService.updateRepository(workspaceSlug, repository.id, data);
      await mutate((current) => current?.map((item) => (item.id === updated.id ? updated : item)), false);
    } catch (error) {
      showError(error);
    }
  };

  const handleRemove = async () => {
    if (!repositoryToRemove) return;
    setIsRemoving(true);
    try {
      await githubService.unwatchRepository(workspaceSlug, repositoryToRemove.id);
      await mutate((current) => current?.filter((item) => item.id !== repositoryToRemove.id), false);
      setRepositoryToRemove(null);
    } catch (error) {
      showError(error);
    } finally {
      setIsRemoving(false);
    }
  };

  if (!repositories) return null;
  if (repositories.length === 0)
    return <p className="text-body-xs-regular text-tertiary">{t("github_integration.no_repositories")}</p>;

  return (
    <>
      <ResizableTable
        resizeLabel={t("github_integration.resize_column")}
        columns={[
          { key: "repository", label: t("github_integration.repository"), width: 220 },
          { key: "project", label: t("common.project"), width: 180 },
          { key: "sync", label: t("github_integration.issue_sync"), width: 160 },
          { key: "github_label", label: t("github_integration.github_label"), width: 140 },
          { key: "plane_label", label: t("github_integration.plane_label"), width: 140 },
          { key: "open_state", label: t("github_integration.open_state"), width: 150 },
          { key: "closed_state", label: t("github_integration.closed_state"), width: 150 },
          { key: "actions", label: t("github_integration.stop_watching"), width: 140, hideLabel: true },
        ]}
      >
        {repositories.map((repository) => (
          <RepositoryRow
            key={repository.id}
            workspaceSlug={workspaceSlug}
            repository={repository}
            onUpdate={(item, data) => void handleUpdate(item, data)}
            onRemove={setRepositoryToRemove}
          />
        ))}
      </ResizableTable>
      <ConfirmDialog
        isOpen={!!repositoryToRemove}
        isSubmitting={isRemoving}
        handleClose={() => setRepositoryToRemove(null)}
        handleSubmit={handleRemove}
        title={t("github_integration.stop_watching")}
        content={t("github_integration.stop_watching_confirmation", {
          repository: repositoryToRemove?.full_name ?? "",
        })}
        primaryButtonText={{
          loading: t("github_integration.stop_watching"),
          default: t("github_integration.stop_watching"),
        }}
      />
    </>
  );
});

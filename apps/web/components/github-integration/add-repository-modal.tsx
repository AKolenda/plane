/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { Input } from "@makeplane/propel/components/input";
import { Select, SelectContent, SelectItem, SelectList, SelectTrigger } from "@makeplane/propel/components/select";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TGithubConnection } from "@plane/types";
// services
import { GithubIntegrationService } from "@/services/integrations";
// local imports
import { formatApiError, githubAvailableRepositoriesKey } from "./keys";

const githubService = new GithubIntegrationService();

type Props = {
  workspaceSlug: string;
  connections: TGithubConnection[];
  isOpen: boolean;
  onClose: () => void;
  onAdded: () => void;
};

export function AddRepositoryModal(props: Props) {
  const { workspaceSlug, connections, isOpen, onClose, onAdded } = props;
  const { t } = useTranslation();
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [addingId, setAddingId] = useState<number | null>(null);

  const connectionId = selectedConnectionId ?? connections[0]?.id ?? null;
  const {
    data: repositories,
    error,
    mutate,
  } = useSWR(isOpen && connectionId ? githubAvailableRepositoriesKey(workspaceSlug, connectionId) : null, () =>
    connectionId ? githubService.getAvailableRepositories(workspaceSlug, connectionId) : null
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (repositories ?? []).filter((repository) => repository.full_name.toLowerCase().includes(needle));
  }, [repositories, query]);

  const handleAdd = async (repositoryId: number) => {
    if (!connectionId) return;
    setAddingId(repositoryId);
    try {
      const watched = await githubService.watchRepository(workspaceSlug, connectionId, repositoryId);
      await mutate(
        (current) => current?.map((item) => (item.id === repositoryId ? { ...item, watched_id: watched.id } : item)),
        false
      );
      onAdded();
    } catch (err) {
      setToast({
        type: "error",
        title: t("common.something_went_wrong"),
        message: formatApiError(err),
      });
    } finally {
      setAddingId(null);
    }
  };

  const connectionOptions = connections.map((connection) => ({
    value: connection.id,
    label: connection.account_login,
  }));

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent size="sm">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>{t("github_integration.add_repository")}</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody>
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                {connections.length > 1 && (
                  <div className="w-44 flex-shrink-0">
                    <Select<string>
                      items={connectionOptions}
                      value={connectionId}
                      onValueChange={(value) => value && setSelectedConnectionId(value)}
                    >
                      <SelectTrigger size="md" aria-label={t("github_integration.account")} />
                      <SelectContent side="bottom" align="start">
                        <SelectList>
                          {connectionOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value} size="md" label={option.label} />
                          ))}
                        </SelectList>
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <Input
                  size="md"
                  type="search"
                  value={query}
                  placeholder={t("github_integration.search_repositories")}
                  aria-label={t("github_integration.search_repositories")}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
              <ul className="max-h-96 overflow-y-auto rounded-lg border border-subtle">
                {error ? (
                  <li className="px-3 py-2.5 text-body-xs-regular text-danger-primary">
                    {formatApiError(error) ?? t("common.something_went_wrong")}
                  </li>
                ) : !repositories ? (
                  <li className="px-3 py-2.5 text-body-xs-regular text-tertiary">{t("common.loading")}</li>
                ) : filtered.length === 0 ? (
                  <li className="px-3 py-2.5 text-body-xs-regular text-tertiary">
                    {t("github_integration.no_available_repositories")}
                  </li>
                ) : (
                  filtered.map((repository) => (
                    <li
                      key={repository.id}
                      className="flex h-11 items-center justify-between gap-3 border-b border-subtle px-3 last:border-b-0"
                    >
                      <span className="truncate text-body-xs-regular">{repository.full_name}</span>
                      {repository.watched_id ? (
                        <span className="flex-shrink-0 text-caption-md-medium text-tertiary">
                          {t("github_integration.watching")}
                        </span>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          stretch="auto"
                          label={t("common.add")}
                          loading={addingId === repository.id}
                          disabled={addingId !== null}
                          onClick={() => void handleAdd(repository.id)}
                        />
                      )}
                    </li>
                  ))
                )}
              </ul>
            </div>
          </DialogBody>
        </DialogMain>
      </DialogContent>
    </Dialog>
  );
}

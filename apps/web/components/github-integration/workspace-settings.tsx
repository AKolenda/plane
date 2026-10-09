/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import { useTranslation } from "@plane/i18n";
import type { TGithubAuthType, TGithubConnection, TGithubIntegration } from "@plane/types";
// components
import { SettingsHeading } from "@/components/settings/heading";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// services
import { GithubIntegrationService } from "@/services/integrations";
// local imports
import { AddRepositoryModal } from "./add-repository-modal";
import { formatApiError, githubIntegrationKey, githubRepositoriesKey } from "./keys";
import { GithubRepositoriesTable } from "./repositories-table";
import { ResizableTable, TABLE_CELL_CLASS } from "@/components/common/resizable-table";

const githubService = new GithubIntegrationService();

type Props = {
  workspaceSlug: string;
};

export const GithubWorkspaceSettings = observer(function GithubWorkspaceSettings(props: Props) {
  const { workspaceSlug } = props;
  const { t } = useTranslation();
  const router = useAppRouter();
  const searchParams = useSearchParams();
  // states
  const [connectingType, setConnectingType] = useState<TGithubAuthType | null>(null);
  const [connectionToRemove, setConnectionToRemove] = useState<TGithubConnection | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);
  const [isAddRepositoryOpen, setIsAddRepositoryOpen] = useState(false);
  // data
  const { data: integration, mutate: mutateIntegration } = useSWR<TGithubIntegration>(
    githubIntegrationKey(workspaceSlug),
    () => githubService.getIntegration(workspaceSlug)
  );
  const { mutate: mutateRepositories } = useSWR(githubRepositoriesKey(workspaceSlug), () =>
    githubService.getRepositories(workspaceSlug)
  );

  // Report the outcome of the GitHub redirect once, then drop it from the URL
  const connectResult = searchParams.get("github");
  const connectMessage = searchParams.get("message");
  useEffect(() => {
    if (!connectResult) return;
    setToast(
      connectResult === "connected"
        ? { type: "success", title: t("github_integration.connected") }
        : {
            type: "error",
            title: t("github_integration.connection_failed"),
            message: connectMessage ?? undefined,
          }
    );
    router.replace(`/${workspaceSlug}/settings/github`);
  }, [connectResult, connectMessage, router, t, workspaceSlug]);

  const handleConnect = async (authType: TGithubAuthType) => {
    setConnectingType(authType);
    try {
      const { url } = await githubService.getConnectUrl(workspaceSlug, authType);
      window.location.assign(url);
    } catch (error) {
      setConnectingType(null);
      setToast({
        type: "error",
        title: t("github_integration.connection_failed"),
        message: formatApiError(error),
      });
    }
  };

  const handleDisconnect = async () => {
    if (!connectionToRemove) return;
    setIsRemoving(true);
    try {
      await githubService.disconnect(workspaceSlug, connectionToRemove.id);
      await Promise.all([mutateIntegration(), mutateRepositories()]);
      setConnectionToRemove(null);
    } catch (error) {
      setToast({
        type: "error",
        title: t("common.something_went_wrong"),
        message: formatApiError(error),
      });
    } finally {
      setIsRemoving(false);
    }
  };

  if (!integration) return null;

  const isConfigured = integration.is_app_configured || integration.is_oauth_configured;
  const connections = integration.connections;

  return (
    <div className="flex w-full flex-col gap-8">
      <SettingsHeading title={t("github_integration.name")} description={t("github_integration.description")} />

      {!isConfigured ? (
        <p className="text-body-xs-regular text-tertiary">
          {t("integrations.not_configured_message_admin", { name: "GitHub" })}
        </p>
      ) : (
        <>
          <section className="flex flex-col gap-3">
            <SettingsHeading
              variant="h6"
              title={t("github_integration.connections")}
              control={
                <div className="flex items-center gap-2">
                  {integration.is_oauth_configured && (
                    <Button
                      variant="secondary"
                      size="md"
                      stretch="auto"
                      label={t("github_integration.connect_personal_account")}
                      loading={connectingType === "oauth"}
                      disabled={connectingType !== null}
                      onClick={() => void handleConnect("oauth")}
                    />
                  )}
                  {integration.is_app_configured && (
                    <Button
                      variant="primary"
                      size="md"
                      stretch="auto"
                      label={t("github_integration.connect_org")}
                      loading={connectingType === "app"}
                      disabled={connectingType !== null}
                      onClick={() => void handleConnect("app")}
                    />
                  )}
                </div>
              }
            />
            {connections.length === 0 ? (
              <p className="text-body-xs-regular text-tertiary">{t("github_integration.no_connections")}</p>
            ) : (
              <ResizableTable
                resizeLabel={t("github_integration.resize_column")}
                columns={[
                  { key: "account", label: t("github_integration.account"), width: 260 },
                  { key: "type", label: t("github_integration.connection_type"), width: 140 },
                  { key: "host", label: t("github_integration.host"), width: 240 },
                  { key: "actions", label: t("common.disconnect"), width: 130, hideLabel: true, align: "end" },
                ]}
              >
                {connections.map((connection) => (
                  <tr key={connection.id}>
                    <td className={TABLE_CELL_CLASS}>
                      <span className="flex items-center gap-2">
                        {connection.account_avatar_url && (
                          <img
                            src={connection.account_avatar_url}
                            alt=""
                            className="size-5 flex-shrink-0 rounded-full"
                          />
                        )}
                        <span className="truncate">{connection.account_login}</span>
                      </span>
                    </td>
                    <td className={TABLE_CELL_CLASS}>
                      {connection.auth_type === "app"
                        ? t("github_integration.github_app")
                        : t("github_integration.oauth_app")}
                    </td>
                    <td className={TABLE_CELL_CLASS}>{new URL(connection.host_url).host}</td>
                    <td className={`${TABLE_CELL_CLASS} text-end`}>
                      <Button
                        variant="ghost"
                        size="sm"
                        stretch="auto"
                        label={t("common.disconnect")}
                        onClick={() => setConnectionToRemove(connection)}
                      />
                    </td>
                  </tr>
                ))}
              </ResizableTable>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <SettingsHeading
              variant="h6"
              title={t("github_integration.repo_mapping")}
              control={
                <Button
                  variant="secondary"
                  size="md"
                  stretch="auto"
                  label={t("github_integration.add_repository")}
                  disabled={connections.length === 0}
                  onClick={() => setIsAddRepositoryOpen(true)}
                />
              }
            />
            <GithubRepositoriesTable workspaceSlug={workspaceSlug} />
          </section>
        </>
      )}

      <AddRepositoryModal
        workspaceSlug={workspaceSlug}
        connections={connections}
        isOpen={isAddRepositoryOpen}
        onClose={() => setIsAddRepositoryOpen(false)}
        onAdded={() => void mutateRepositories()}
      />
      <ConfirmDialog
        isOpen={!!connectionToRemove}
        isSubmitting={isRemoving}
        handleClose={() => setConnectionToRemove(null)}
        handleSubmit={handleDisconnect}
        title={t("common.disconnect")}
        content={t("github_integration.disconnect_confirmation", { account: connectionToRemove?.account_login ?? "" })}
        primaryButtonText={{ loading: t("common.disconnect"), default: t("common.disconnect") }}
      />
    </div>
  );
});

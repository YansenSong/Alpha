import React, { useCallback, useContext, useEffect, useState } from "react";
import { toast } from "react-toastify";

import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import { useRoleAccess } from "../shared/auth/roleAccess";
import {
  DashboardCard,
  EmptyState,
  SectionHeader,
} from "../shared/ui/Dashboard";
import { useT } from "../shared/i18n/i18n";

const PAGE_SIZE = 50;

const LogsPage = () => {
  const { t } = useT();
  const { robotId } = useContext(AuthContext);
  const readAccess = useRoleAccess("Viewer");
  const downloadAccess = useRoleAccess("Operator");
  const [logs, setLogs] = useState([]);
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!robotId || !readAccess.allowed) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/logs?${params.toString()}`,
        { cache: "no-store" },
      );
      const payload = await response.json();
      setLogs(payload.logs || []);
      setNextOffset(payload.next_offset ?? null);
      setError("");
    } catch (requestError) {
      setError(requestError.message || "Unable to load robot logs.");
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }, [offset, readAccess.allowed, robotId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const download = async (log) => {
    if (!downloadAccess.allowed) return;
    try {
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/logs/${encodeURIComponent(log.log_id)}/download`,
      );
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = log.download_name || log.name;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (downloadError) {
      toast.error(downloadError.message || t("Log download failed"));
    }
  };

  return (
    <div className="sectionHeight space-y-5 py-4 sm:py-6">
      <SectionHeader
        eyebrow={t("Operations")}
        title={t("Logs")}
        description={t(
          "Robot runtime logs are collected into one file per node and local day.",
        )}
      />

      {!readAccess.allowed && (
        <p className="rounded-lg border border-statusYellow/40 p-3 text-xs text-statusYellow">
          {t(readAccess.reason)}
        </p>
      )}
      {!downloadAccess.allowed && (
        <p className="text-xs text-themeTextGray">
          {t("Log downloads require Operator permission.")}
        </p>
      )}

      {error && (
        <p role="alert" className="text-xs text-statusRed">
          {error}
        </p>
      )}
      {logs.length === 0 ? (
        <EmptyState
          title={loading ? t("Loading logs…") : t("No logs yet")}
        />
      ) : (
        <DashboardCard className="overflow-x-auto p-0">
          <table className="w-full min-w-[680px] text-left text-xs">
            <thead className="border-b border-borderSubtle text-themeTextGray">
              <tr>
                <th className="p-3">{t("Log")}</th>
                <th className="p-3">{t("Modified")}</th>
                <th className="p-3">{t("Size")}</th>
                <th className="p-3">{t("Action")}</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr
                  key={log.log_id}
                  className="border-b border-borderSubtle/50"
                >
                  <td className="p-3 font-medium text-textWhiteHover">
                    {log.display_name || log.module || log.name}
                  </td>
                  <td className="p-3 text-themeTextGray">
                    {new Date(log.modified_at).toLocaleString()}
                  </td>
                  <td className="p-3 text-themeTextGray">
                    {(log.size / 1024).toFixed(1)} KB
                  </td>
                  <td className="p-3">
                    <button
                      onClick={() => download(log)}
                      disabled={!downloadAccess.allowed}
                      className="text-themeBlue underline disabled:opacity-40"
                    >
                      {t("Download")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </DashboardCard>
      )}

      {(offset > 0 || nextOffset !== null) && (
        <div className="flex items-center justify-between text-xs text-themeTextGray">
          <span>
            {t("Page offset")}: {offset}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0 || loading}
              className="rounded border border-borderSubtle px-3 py-1 disabled:opacity-40"
            >
              {t("Previous")}
            </button>
            <button
              onClick={() => nextOffset !== null && setOffset(nextOffset)}
              disabled={nextOffset === null || loading}
              className="rounded border border-borderSubtle px-3 py-1 disabled:opacity-40"
            >
              {t("Next")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default LogsPage;

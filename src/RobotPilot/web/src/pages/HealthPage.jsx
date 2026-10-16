import React, { useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import { AuthContext } from "../app/App";
import { useRosStatus } from "../app/App";
import SystemHealth from "../components/SystemHealth";
import SupportPackageButton from "../components/SupportPackageButton";
import { apiFetch } from "../shared/api/apiFetch";
import useSystemDiagnostics from "../shared/hooks/useSystemDiagnostics";
import { useT, T } from "../shared/i18n/i18n";
import {
  DashboardCard,
  EmptyState,
  SectionHeader,
  StatusBadge,
} from "../shared/ui/Dashboard";

const OVERALL_STYLE = {
  0: {
    border: "border-statusGreen/30",
    bg: "bg-statusGreen/10",
    text: "text-statusGreen",
    dot: "bg-statusGreen",
    pulse: true,
  },
  1: {
    border: "border-statusYellow/30",
    bg: "bg-statusYellow/10",
    text: "text-statusYellow",
    dot: "bg-statusYellow",
    pulse: false,
  },
  2: {
    border: "border-statusRed/30",
    bg: "bg-statusRed/5",
    text: "text-statusRed",
    dot: "bg-statusRed",
    pulse: false,
  },
  3: {
    border: "border-statusRed/50",
    bg: "bg-statusRed/15",
    text: "text-statusRed",
    dot: "bg-statusRed",
    pulse: true,
  },
};

const formatBytes = (bytes) => {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
};

const HealthPage = () => {
  const { t } = useT();
  const { robotId } = useContext(AuthContext);
  const rosbridgeStatus = useRosStatus();
  const [storage, setStorage] = useState(null);
  const [storageError, setStorageError] = useState("");
  const {
    reportHealth,
    battery,
    diagnosticsMsgs,
    missingTopics,
    devices,
    deviceStatuses,
    issues,
    overall,
    overallLabel,
  } = useSystemDiagnostics();

  const storageLevel = storage?.some((item) => item.level === "critical")
    ? "critical"
    : storage?.some((item) => item.level === "warning")
    ? "warning"
    : null;
  const storageSeverity = storageError
    ? 2
    : !storage || storageLevel === "warning"
    ? 1
    : storageLevel === "critical"
    ? 2
    : 0;
  const effectiveOverall = Math.max(overall, storageSeverity);
  const effectiveOverallLabel =
    effectiveOverall === 2
      ? "Needs attention"
      : effectiveOverall === 1
      ? "Ready with warnings"
      : overallLabel;
  const effectiveIssues = [
    ...issues,
    ...(storageError || !storage
      ? [
          {
            id: "storage-unknown",
            message: storage
              ? "Storage health unavailable"
              : "Loading storage health…",
          },
        ]
      : storageLevel
      ? [
          {
            id: `storage-${storageLevel}`,
            message:
              storageLevel === "critical"
                ? "Storage usage is above the critical threshold."
                : "Storage usage is above the warning threshold.",
          },
        ]
      : []),
  ];
  const style = OVERALL_STYLE[effectiveOverall];
  useEffect(() => {
    let active = true;
    const loadStorage = async () => {
      try {
        const response = await apiFetch(
          `/api/v1/robots/${encodeURIComponent(robotId || "")}/health`,
          { cache: "no-store" },
        );
        const data = await response.json();
        if (!active) return;
        setStorage(data.storage || []);
        setStorageError(data.storage_error || "");
      } catch (error) {
        if (!active) return;
        setStorage(null);
        setStorageError(error.message || "Storage health unavailable.");
      }
    };
    if (robotId) {
      loadStorage();
      const timer = window.setInterval(loadStorage, 30000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }
    return () => {
      active = false;
    };
  }, [robotId]);

  return (
    <div className="sectionHeight space-y-5 py-4 sm:space-y-6 sm:py-6">
      <SectionHeader
        eyebrow="System overview"
        title="Health Centre"
        description="Combines connection status, sensor data, navigation health, hardware, and battery into one ready/not-ready check."
        action={
          <SupportPackageButton
            health={{
              overall: effectiveOverall,
              overallLabel: effectiveOverallLabel,
              issues: effectiveIssues,
            }}
          />
        }
      />

      <DashboardCard className={`border p-5 ${style.border} ${style.bg}`}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex h-3 w-3 shrink-0">
            {style.pulse && (
              <span
                className={`absolute inline-flex h-full w-full animate-ping rounded-full ${style.dot} opacity-50`}
              />
            )}
            <span
              className={`relative inline-flex h-3 w-3 rounded-full ${style.dot}`}
            />
          </div>
          <p className={`font-[RobotoMono] text-lg font-bold ${style.text}`}>
            {t(effectiveOverallLabel)}
          </p>
        </div>

        {effectiveIssues.length === 0 ? (
          <p className="mt-2 text-sm text-themeTextGray">
            {t("Every checked signal is nominal.")}
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {effectiveIssues.map((issue) =>
              issue.linkTo ? (
                <Link
                  key={issue.id}
                  to={issue.linkTo}
                  className="rounded-lg border border-borderSubtle bg-bgSurface px-2.5 py-1.5 text-xs text-textWhiteHover hover:border-themeBlue hover:text-themeBlue"
                >
                  {t(issue.message)}
                </Link>
              ) : (
                <span
                  key={issue.id}
                  className="rounded-lg border border-borderSubtle bg-bgSurface px-2.5 py-1.5 text-xs text-themeTextGray"
                >
                  {t(issue.message)}
                </span>
              ),
            )}
          </div>
        )}
      </DashboardCard>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <SystemHealth onHealthChange={reportHealth} />

        <DashboardCard className="p-4">
          <p className="mb-2 font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray">
            {t("Devices")}
          </p>
          {devices.length === 0 ? (
            <EmptyState
              className="px-0 pb-0"
              title="No devices registered"
              description="Register hardware on the Devices page to see it here."
            />
          ) : (
            <div className="space-y-1.5">
              {devices.map((device) => {
                const state = deviceStatuses[device.id] || "unmonitored";
                return (
                  <div
                    key={device.id}
                    className="flex items-center justify-between gap-2 rounded-lg bg-bgSurface px-2.5 py-1.5 text-xs"
                  >
                    <span className="truncate text-textWhiteHover">
                      {device.name}
                    </span>
                    <StatusBadge
                      status={
                        state === "online"
                          ? "connected"
                          : state === "offline"
                          ? "disconnected"
                          : "unknown"
                      }
                      label={
                        state === "online"
                          ? "Online"
                          : state === "offline"
                          ? "Offline"
                          : "No status topic"
                      }
                      pulse={state === "online"}
                    />
                  </div>
                );
              })}
            </div>
          )}
          <Link
            to="/devices"
            className="mt-3 inline-block text-xs text-themeBlue hover:underline"
          >
            <T>{"Manage devices →"}</T>{" "}
          </Link>
        </DashboardCard>

        <DashboardCard className="p-4">
          <p className="mb-3 font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray">
            <T>{"Storage"}</T>
          </p>
          {!storage && !storageError ? (
            <p className="text-xs text-themeTextGray opacity-70">
              <T>{"Loading storage health…"}</T>
            </p>
          ) : storageError || !storage ? (
            <p className="text-xs text-statusYellow">
              {t("Storage health unavailable")}
            </p>
          ) : storage.length === 0 ? (
            <p className="text-xs text-themeTextGray opacity-70">
              <T>{"No storage paths configured."}</T>
            </p>
          ) : (
            <div className="space-y-3">
              {storage.map((item) => {
                const tone =
                  item.level === "critical"
                    ? "text-statusRed"
                    : item.level === "warning"
                    ? "text-statusYellow"
                    : "text-statusGreen";
                return (
                  <div key={`${item.label}:${item.path}`}>
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="truncate text-textWhiteHover">
                        {t(item.label)}
                      </span>
                      <span className={`shrink-0 font-semibold ${tone}`}>
                        {item.used_percent}% · {t(item.level)}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-themeTextGray">
                      {formatBytes(item.available_bytes)} {t("available of")}{" "}
                      {formatBytes(item.total_bytes)}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </DashboardCard>

        <DashboardCard className="p-4">
          <p className="mb-2 font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray">
            <T>{"Battery"}</T>{" "}
          </p>
          {battery.pct === null ? (
            <p className="text-xs text-themeTextGray opacity-70">
              <T>{"No battery telemetry."}</T>{" "}
            </p>
          ) : (
            <div className="flex items-center justify-between">
              <p className="font-[RobotoMono] text-2xl font-bold text-textWhiteHover">
                {Number(battery.pct).toFixed(1)}%
              </p>
              <StatusBadge
                status={battery.charging ? "connected" : "idle"}
                label={battery.charging ? "Charging" : "On battery"}
                pulse={battery.charging}
              />
            </div>
          )}
          <Link
            to="/info"
            className="mt-3 inline-block text-xs text-themeBlue hover:underline"
          >
            <T>{"Full telemetry →"}</T>{" "}
          </Link>
        </DashboardCard>

        <DashboardCard className="p-4">
          <p
            className="mb-2 font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray"
            title="/diagnostics"
          >
            <T>{"Diagnostics"}</T>{" "}
          </p>
          {diagnosticsMsgs.length === 0 ? (
            <p className="text-xs text-themeTextGray opacity-70">
              <T>{"No warning/error-level diagnostics reported."}</T>{" "}
            </p>
          ) : (
            <div className="space-y-1.5">
              {diagnosticsMsgs.map((entry, index) => (
                <div
                  key={index}
                  className={`rounded-lg px-2.5 py-1.5 text-xs ${
                    entry.level >= 2
                      ? "bg-statusRed/10 text-statusRed"
                      : "bg-statusYellow/10 text-statusYellow"
                  }`}
                >
                  <span className="font-semibold">{entry.name}</span>:{" "}
                  {entry.message}
                </div>
              ))}
            </div>
          )}
        </DashboardCard>

        <DashboardCard className="p-4">
          <p className="mb-2 font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray">
            <T>{"Expected topics"}</T>{" "}
          </p>
          {missingTopics.length === 0 ? (
            <p className="text-xs text-themeTextGray opacity-70">
              {rosbridgeStatus === "connected"
                ? t("All expected topics are present in the ROS graph.")
                : t("Checked once the robot connection is established.")}
            </p>
          ) : (
            <div className="space-y-1.5">
              {missingTopics.map(({ topic, label }) => (
                <div
                  key={topic}
                  className="rounded-lg bg-statusYellow/10 px-2.5 py-1.5 text-xs text-statusYellow"
                >
                  {t(label)}{" "}
                  <span className="text-themeTextGray">({topic})</span>
                </div>
              ))}
            </div>
          )}
        </DashboardCard>

      </div>

      <ToastContainer theme="dark" position="bottom-right" />
    </div>
  );
};

export default HealthPage;

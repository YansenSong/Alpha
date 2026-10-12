import React, { useState, useEffect } from "react";

import Camera from "../components/Camera";
import RobotState from "../components/RobotState";
import SystemHealth from "../components/SystemHealth";
import { T, useT } from "../shared/i18n/i18n";
import useBatteryState from "../shared/hooks/useBatteryState";
import useRobotStatus from "../shared/hooks/useRobotStatus";
import { INSPECTION_PROFILE } from "../shared/robot/robotContract";
import {
  ChartCard,
  DashboardCard,
  EmptyState,
  SectionHeader,
  StatusBadge,
} from "../shared/ui/Dashboard";

const BATTERY_HISTORY_LENGTH = 40;

// 简易内联迷你趋势图：仓库没有图表库，且只有此处需要趋势线，因此使用小型本地 SVG 即可。
const Sparkline = ({ values, className = "" }) => {
  if (values.length < 2) return null;
  const width = 100;
  const height = 28;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - (Math.max(0, Math.min(100, v)) / 100) * height;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};

const InfoPage = () => {
  const { t } = useT();
  const [batteryHistory, setBatteryHistory] = useState([]);
  const batteryTelemetry = useBatteryState();
  const robotStatus = useRobotStatus();
  const platform = robotStatus.snapshot;
  const readiness = robotStatus.stale
    ? "unknown"
    : platform?.autonomy_ready
    ? "ready"
    : "blocked";
  const robotConnection = robotStatus.stale || platform?.robot_connection?.stale
    ? { label: "Stale data", status: "warning" }
    : platform?.robot_connection?.online
    ? { label: "Online", status: "success" }
    : { label: "Unknown", status: "unknown" };
  const currentMap = robotStatus.stale
    ? t("Stale data")
    : platform?.current_map?.map ||
      platform?.current_map?.map_id ||
      t("Unavailable");
  const localization = robotStatus.stale
    ? { label: "Unknown", status: "unknown" }
    : platform?.localization?.stale
    ? { label: "Stale data", status: "warning" }
    : platform?.localization?.online
    ? { label: "Online", status: "success" }
    : { label: "Unavailable", status: "unknown" };
  const softwareStop = robotStatus.stale || platform?.software_stop?.stale
    ? { label: "Unknown", status: "unknown" }
    : platform?.software_stop?.active
    ? { label: "Active", status: "warning" }
    : { label: "Inactive", status: "neutral" };
  const battery = batteryTelemetry.state;
  const rawBatteryPct = battery?.percent == null ? null : Number(battery.percent);
  const batteryPct = Number.isFinite(rawBatteryPct) ? rawBatteryPct : null;
  const charging = batteryTelemetry.usable ? battery.charging : null;

  useEffect(() => {
    if (!battery?.available || battery.percent == null) return;
    setBatteryHistory((prev) => [
      ...prev.slice(-(BATTERY_HISTORY_LENGTH - 1)),
      battery.percent,
    ]);
  }, [battery?.receivedAt]);

  const batteryStatus =
    batteryPct === null || batteryTelemetry.stale || !battery?.available
      ? {
          status: "unknown",
          label: batteryTelemetry.stale ? "Stale data" : "Unavailable",
        }
      : batteryPct > 60
      ? { status: "success", label: "Good" }
      : batteryPct > 25
      ? { status: "warning", label: "Low" }
      : { status: "error", label: "Critical" };

  return (
    <div className="sectionHeight space-y-5 py-4 sm:space-y-6 sm:py-6">
      <SectionHeader
        eyebrow="System overview"
        title="Robot status"
        description="Live camera, telemetry, power, and ROS health in one operational view."
      />

      <DashboardCard className="space-y-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray">
            <T>{"Robot readiness"}</T>
          </p>
          <StatusBadge
            status={
              readiness === "ready"
                ? "success"
                : readiness === "blocked"
                ? "warning"
                : "unknown"
            }
            label={
              readiness === "ready"
                ? t("Ready")
                : readiness === "blocked"
                ? t("Not ready")
                : t("Unknown")
            }
          />
        </div>
        <dl className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <div className="min-w-0 rounded-xl border border-borderSubtle bg-bgCard/40 px-3 py-3">
            <dt className="mb-2 text-[10px] font-medium uppercase tracking-wider text-themeTextGray">
              <T>{"Robot connection"}</T>
            </dt>
            <dd>
              <StatusBadge
                status={robotConnection.status}
                label={robotConnection.label}
              />
            </dd>
          </div>
          <div className="min-w-0 rounded-xl border border-borderSubtle bg-bgCard/40 px-3 py-3">
            <dt className="mb-2 text-[10px] font-medium uppercase tracking-wider text-themeTextGray">
              <T>{"Current map"}</T>
            </dt>
            <dd
              className="truncate font-[RobotoMono] text-sm font-semibold text-textWhiteHover"
              title={currentMap}
            >
              {currentMap}
            </dd>
          </div>
          <div className="min-w-0 rounded-xl border border-borderSubtle bg-bgCard/40 px-3 py-3">
            <dt className="mb-2 text-[10px] font-medium uppercase tracking-wider text-themeTextGray">
              <T>{"Localization"}</T>
            </dt>
            <dd>
              <StatusBadge
                status={localization.status}
                label={localization.label}
              />
            </dd>
          </div>
          <div className="min-w-0 rounded-xl border border-borderSubtle bg-bgCard/40 px-3 py-3">
            <dt className="mb-2 text-[10px] font-medium uppercase tracking-wider text-themeTextGray">
              <T>{"Software Stop"}</T>
            </dt>
            <dd>
              <StatusBadge
                status={softwareStop.status}
                label={softwareStop.label}
              />
            </dd>
          </div>
        </dl>
        {INSPECTION_PROFILE ? (
          <p className="rounded-xl border border-statusYellow/40 bg-statusYellow/5 p-3 text-sm text-statusYellow">
            {t(
              "Project localization interface is unconfigured. Status: UNKNOWN.",
            )}
          </p>
        ) : (
          <RobotState
            compact
            splitVelocityCards
            separateHeading
            gridClassName="xl:grid-cols-4"
          />
        )}
        {platform?.readiness_blockers?.length > 0 && (
          <p className="text-xs text-statusYellow">
            <T>{"Autonomy blocked"}</T>:{" "}
            {platform.readiness_blockers.join(" · ")}
          </p>
        )}
        {!platform && robotStatus.error && (
          <p className="text-xs text-themeTextGray">{robotStatus.error}</p>
        )}
      </DashboardCard>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.8fr)] xl:gap-5">
        <section className="grid min-w-0 gap-4">
          <div className="h-[320px] min-w-0 sm:h-[420px] xl:h-[500px]">
            <Camera />
          </div>
        </section>

        <section className="grid min-w-0 content-start gap-4">
          <ChartCard
            title="Battery level"
            value={batteryPct !== null ? `${batteryPct.toFixed(1)}%` : "—"}
            status={
              <div className="flex flex-wrap items-center gap-1.5">
                <StatusBadge
                  status={batteryStatus.status}
                  label={batteryStatus.label}
                />
                <StatusBadge
                  status={
                    battery?.source === "simulated"
                      ? "warning"
                      : battery?.source === "hardware"
                      ? "success"
                      : "unknown"
                  }
                  label={battery?.source || "unavailable"}
                />
              </div>
            }
          >
            {batteryPct !== null ? (
              <div className="mt-4 space-y-2">
                <div
                  className="premium-progress"
                  role="progressbar"
                  aria-label={t("Battery charge")}
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-valuenow={batteryPct}
                >
                  <div
                    className="premium-progress__value"
                    style={{
                      width: `${Math.max(0, Math.min(100, batteryPct))}%`,
                    }}
                  />
                </div>
                <div className="flex justify-between font-[RobotoMono] text-[10px] text-themeTextGray">
                  <span>0%</span>
                  <span>100%</span>
                </div>

                {batteryHistory.length > 1 && (
                  <div>
                    <p className="mb-1 text-[10px] uppercase tracking-wider text-themeTextGray">
                      {t("Recent trend")}{" "}
                      <span className="normal-case tracking-normal text-themeTextGray/60">
                        {t("(last ~10 min)")}
                      </span>
                    </p>
                    <Sparkline
                      values={batteryHistory}
                      className={`h-7 w-full ${
                        batteryStatus.status === "success"
                          ? "text-statusGreen"
                          : batteryStatus.status === "warning"
                          ? "text-statusYellow"
                          : "text-statusRed"
                      }`}
                    />
                  </div>
                )}
              </div>
            ) : (
              <EmptyState
                className="min-h-[92px] px-0 pb-0"
                title="No battery telemetry"
                description={
                  battery?.reason ||
                  "Waiting for an available, identified battery source."
                }
              />
            )}
          </ChartCard>

          <DashboardCard className="flex items-center justify-between gap-4 p-4">
            <div>
              <p className="font-[RobotoMono] text-[11px] font-bold uppercase tracking-[0.14em] text-themeBlue">
                {t("Charging station")}
              </p>
              <p className="mt-1 text-sm text-themeTextGray">
                {battery?.simulated
                  ? t(
                      charging === true
                        ? "Simulated battery is charging."
                        : charging === false
                        ? "Simulated battery is not charging."
                        : "Simulated charging state unavailable.",
                    )
                  : t(
                      charging === true
                        ? "Battery reports charging."
                        : charging === false
                        ? "Battery reports not charging."
                        : "Charging state unavailable; dock status is not power confirmation.",
                    )}
              </p>
            </div>
            <StatusBadge
              status={
                charging === null ? "unknown" : charging ? "connected" : "idle"
              }
              label={
                charging === null
                  ? "Unavailable"
                  : battery?.simulated
                  ? charging
                    ? "Simulated charging"
                    : "Simulated not charging"
                  : charging
                  ? "Charging"
                  : "Not charging"
              }
              pulse={charging === true}
            />
          </DashboardCard>

          <div className="min-w-0">
            <SystemHealth />
          </div>
        </section>
      </div>
    </div>
  );
};

export default InfoPage;

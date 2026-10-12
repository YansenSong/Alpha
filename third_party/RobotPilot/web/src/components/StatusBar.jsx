import React, { useCallback, useContext } from "react";

import { AuthContext, useRosStatus } from "../app/App";
import { addEvent } from "../shared/events/eventLog";
import { useT } from "../shared/i18n/i18n";
import { INSPECTION_PROFILE } from "../shared/robot/robotContract";
import SoftwareStopActionButton from "./SoftwareStopActionButton";
import useSoftwareStop from "../shared/hooks/useSoftwareStop";
import useBatteryState from "../shared/hooks/useBatteryState";

const CONN = {
  connected: {
    label: "Connected",
    color: "text-statusGreen",
    dot: "bg-statusGreen",
  },
  disconnected: {
    label: "Offline",
    color: "text-statusRed",
    dot: "bg-statusRed",
  },
  error: { label: "Error", color: "text-statusRed", dot: "bg-statusRed" },
};

const batteryColor = (pct, stale) =>
  pct == null || stale
    ? "text-themeTextGray"
    : pct <= 20
    ? "text-statusRed"
    : pct <= 40
    ? "text-statusYellow"
    : "text-statusGreen";

/** Shared status bar with robot-confirmed software stop state. */
const StatusBar = () => {
  const rosStatus = useRosStatus();
  const { robotMode } = useContext(AuthContext);
  const { t } = useT();
  const batteryTelemetry = useBatteryState();
  const softwareStop = useSoftwareStop();

  const requestSoftwareStop = useCallback(() => {
    if (INSPECTION_PROFILE || !softwareStop.canRequestStop) return;
    softwareStop.requestStop();
    addEvent({
      type: "operator",
      severity: "warning",
      message: "Software stop requested from status bar",
    });
  }, [softwareStop]);

  const conn = CONN[rosStatus] || CONN.disconnected;
  const battery = batteryTelemetry.state;
  const pct =
    battery?.available && battery.percent != null
      ? Number(battery.percent)
      : null;
  const stopActive = softwareStop.robotState?.active === true;
  const showResumeNavigation =
    stopActive || softwareStop.canResumePausedTask;
  const stopStatus = softwareStop.requestState?.status;
  const stopLabel = stopActive
    ? !softwareStop.stateFresh
      ? t("Software stop active; state is stale")
      : softwareStop.robotState.result === "rejected"
      ? t("Software stop remains active")
      : softwareStop.robotState.durable &&
      softwareStop.robotState.result === "confirmed"
      ? t("Software stop confirmed")
      : t("Software stop active but persistence is unavailable")
    : stopStatus === "pending"
    ? t("Software stop request pending")
    : stopStatus === "unknown" || !softwareStop.stateFresh
    ? t("Software stop state unknown")
    : t("Software Stop (not physical E-STOP)");

  return (
    <div className="sticky top-0 z-40 flex items-center gap-4 border-b border-borderSubtle bg-bgCard/90 px-3 py-1.5 font-[RobotoMono] backdrop-blur sm:px-4">
      <div className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${conn.dot} ${
            rosStatus === "connected" ? "" : "animate-pulse"
          }`}
        />
        <span className={`text-xs ${conn.color}`}>{t(conn.label)}</span>
      </div>

      {robotMode === "simulation" && (
        <span className="rounded border border-statusYellow/50 bg-statusYellow/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-statusYellow">
          SIMULATION
        </span>
      )}
      {robotMode === "hardware" && (
        <span className="rounded border border-statusGreen/50 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-statusGreen">
          HARDWARE
        </span>
      )}

      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-themeTextGray">
          {t("Batt")}
        </span>
        <span
          className={`text-xs font-semibold ${batteryColor(
            pct,
            batteryTelemetry.stale,
          )}`}
        >
          {pct == null ? "—" : `${pct.toFixed(1)}%`}
        </span>
        <span
          title={
            battery?.reason ||
            battery?.source ||
            "Battery telemetry unavailable"
          }
          className={`rounded border px-1 py-0.5 text-[8px] font-bold uppercase tracking-wide ${
            battery?.simulated
              ? "border-statusYellow/50 text-statusYellow"
              : battery?.source === "hardware" && batteryTelemetry.usable
              ? "border-statusGreen/50 text-statusGreen"
              : "border-borderSubtle text-themeTextGray"
          }`}
        >
          {battery?.simulated
            ? batteryTelemetry.stale
              ? "SIM · STALE"
              : "SIMULATION"
            : battery?.source === "hardware"
            ? batteryTelemetry.stale
              ? "HW · STALE"
              : "HARDWARE"
            : batteryTelemetry.stale
            ? "STALE"
            : "UNAVAILABLE"}
        </span>
        <div className="hidden h-2 w-16 overflow-hidden rounded-full bg-bgSurface sm:block">
          <div
            className={`h-full ${
              pct == null
                ? "bg-themeTextGray"
                : pct <= 20
                ? "bg-statusRed"
                : pct <= 40
                ? "bg-statusYellow"
                : "bg-statusGreen"
            }`}
            style={{
              width: `${pct == null ? 0 : Math.max(0, Math.min(100, pct))}%`,
            }}
          />
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2" aria-live="polite">
        <span
          className={`text-[10px] ${
            stopActive ? "font-bold text-statusRed" : "text-themeTextGray"
          }`}
        >
          {stopLabel}
          {softwareStop.requestState?.status === "rejected"
            ? `: ${softwareStop.requestState.reason}`
            : stopActive && softwareStop.robotState.result === "rejected"
            ? `: ${softwareStop.robotState.reason}`
            : ""}
        </span>
        <SoftwareStopActionButton
          active={false}
          onClick={requestSoftwareStop}
          disabled={
            INSPECTION_PROFILE || !softwareStop.canRequestStop || stopActive
          }
          title={
            INSPECTION_PROFILE
              ? "Software Stop unavailable: robot interface not configured. Not the physical E-STOP."
              : "Software stop requires Operator. It is not the physical E-STOP."
          }
        >
          {t("Software Stop")}
        </SoftwareStopActionButton>
        {showResumeNavigation && (
          <SoftwareStopActionButton
            active
            onClick={softwareStop.requestRelease}
            disabled={
              !softwareStop.canReleaseStop || stopStatus === "pending"
            }
            title={t("Resume navigation and continue the current task")}
          >
            {t("Resume navigation")}
          </SoftwareStopActionButton>
        )}
      </div>
    </div>
  );
};

export default StatusBar;

import React, { useContext, useEffect, useState } from "react";

import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import useBatteryState from "../shared/hooks/useBatteryState";
import { useRoleAccess } from "../shared/auth/roleAccess";
import { useT } from "../shared/i18n/i18n";
import {
  DashboardCard,
  SectionHeader,
  StatusBadge,
} from "../shared/ui/Dashboard";

const SCENARIOS = [
  ["normal_discharge", "Normal discharge"],
  ["low_battery", "Low battery"],
  ["simulated_charging", "Simulated charging"],
  ["full", "Full charge"],
  ["communication_lost", "Communication lost"],
  ["charging_fault", "Charging fault"],
  ["reset", "Reset scenario"],
];

const BmsPage = () => {
  const { t, lang } = useT();
  const { robotId, robotMode } = useContext(AuthContext);
  const { state, stale } = useBatteryState();
  const { allowed } = useRoleAccess("Engineer");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [platformConfig, setPlatformConfig] = useState(null);
  const simulation =
    robotMode === "simulation" && state?.source === "simulated";

  useEffect(() => {
    let current = true;
    apiFetch(`/api/v1/robots/${encodeURIComponent(robotId)}/config`, {
      cache: "no-store",
    })
      .then((response) => response.json())
      .then((payload) => {
        if (current) setPlatformConfig(payload);
      })
      .catch(() => {
        if (current) setPlatformConfig(null);
      });
    return () => {
      current = false;
    };
  }, [robotId]);

  const selectScenario = async (scenario) => {
    setPending(scenario);
    setError("");
    try {
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(robotId)}/battery/scenario`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario }),
        },
      );
      if (!response.ok) throw new Error("Scenario was not accepted.");
    } catch (requestError) {
      setError(
        requestError.message === "Scenario was not accepted."
          ? "Scenario was not accepted."
          : "Scenario request failed.",
      );
    } finally {
      setPending("");
    }
  };

  const value = (number, suffix) =>
    number == null ? "—" : `${Number(number).toFixed(1)} ${suffix}`;
  const displaySource = (source) => {
    const labels = {
      simulated: "Simulation",
      hardware: "Hardware",
      unavailable: "Unavailable",
    };
    return t(labels[source] || "Unavailable");
  };
  const displayChargingState = (chargingState) => {
    const labels = {
      charging: "Charging",
      discharging: "Discharging",
      unknown: "Unknown",
      unavailable: "Unavailable",
    };
    return t(labels[chargingState] || "Unknown");
  };
  const displayTelemetryMessage = (message) => {
    if (message === "Battery telemetry is disabled")
      return t("Battery telemetry is disabled");
    if (message === "Battery reading unavailable")
      return t("Battery reading unavailable");
    if (message === "Simulated battery communication is unavailable")
      return t("Simulated battery communication is unavailable");
    if (message.startsWith("Unable to open battery serial port"))
      return t("Battery serial port unavailable");
    if (message === "simulated_charging_failed")
      return t("Simulated charging failed");
    return t("Battery status abnormal");
  };
  const returnToCharge = state?.return_to_charge_state;
  const returnToChargeLabels = {
    not_available: "Not available",
    unavailable: "Unavailable",
  };
  const returnToChargeLabel =
    !returnToCharge || returnToCharge === "not_available"
      ? t("Not available")
      : t(returnToChargeLabels[returnToCharge] || "Unknown");
  const observedAt = state?.observed_at
    ? new Date(state.observed_at).toLocaleString(lang)
    : "—";

  return (
    <div className="sectionHeight space-y-5 py-4 sm:space-y-6 sm:py-6">
      <SectionHeader
        eyebrow="Battery"
        title="Battery management"
        description="Battery telemetry with explicit source, freshness, and simulation controls."
      />
      {simulation && (
        <div
          role="status"
          className="rounded-xl border border-statusYellow/40 bg-statusYellow/10 px-4 py-3 text-sm font-bold tracking-wider text-statusYellow"
        >
          {t("Simulation mode · simulated battery data")}
        </div>
      )}
      <DashboardCard className="space-y-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-themeTextGray">
              {t("State of charge")}
            </p>
            <p className="mt-1 text-4xl font-bold">
              {state?.percent == null ? "—" : `${state.percent.toFixed(1)}%`}
            </p>
          </div>
          <StatusBadge
            status={
              stale || !state?.available
                ? "unknown"
                : state.low_battery
                ? "warning"
                : "success"
            }
            label={
              stale
                ? t("Stale / unavailable")
                : state?.available
                ? displayChargingState(state.charging_state)
                : t("Unavailable")
            }
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Source", displaySource(state?.source)],
            ["Voltage", value(state?.voltage_v, "V")],
            ["Current", value(state?.current_a, "A")],
            ["Low battery threshold", value(state?.low_battery_threshold, "%")],
            [
              "Platform threshold",
              value(platformConfig?.config?.low_battery_threshold, "%"),
            ],
            [
              "Threshold runtime sync",
              platformConfig &&
              state?.threshold_config_version === platformConfig.version
                ? `${t("Applied")} · v${platformConfig.version}`
                : t("Waiting for battery node"),
            ],
            [
              "Low battery",
              state?.low_battery == null
                ? t("Not available")
                : state.low_battery
                ? t("Yes")
                : t("No"),
            ],
            ["Return to charge", returnToChargeLabel],
            ["Observed at", observedAt],
            ["Data freshness", stale ? t("Stale") : t("Up to date")],
          ].map(([label, content]) => (
            <div
              key={label}
              className="rounded-xl border border-borderSubtle bg-bgBase/40 p-3"
            >
              <p className="text-[11px] uppercase tracking-wider text-themeTextGray">
                {t(label)}
              </p>
              <p className="mt-1 break-words text-sm font-medium">{content}</p>
            </div>
          ))}
        </div>
        {state?.reason && (
          <p className="text-sm text-statusYellow">
            {displayTelemetryMessage(state.reason)}
          </p>
        )}
        {state?.fault && (
          <p role="alert" className="text-sm text-statusRed">
            {displayTelemetryMessage(state.fault)}
          </p>
        )}
        {!state && (
          <p className="text-sm text-themeTextGray">
            {t("Waiting for battery status data.")}
          </p>
        )}
      </DashboardCard>
      <DashboardCard className="space-y-3 p-4 sm:p-5">
        <div>
          <h2 className="font-semibold">{t("Simulation scenarios")}</h2>
          <p className="mt-1 text-xs text-themeTextGray">
            {t(
              "Scenario controls are available only when the robot and battery source both report simulation. No physical charging or docking is performed.",
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {SCENARIOS.map(([scenario, label]) => (
            <button
              key={scenario}
              type="button"
              disabled={!simulation || !allowed || Boolean(pending)}
              onClick={() => selectScenario(scenario)}
              className="min-h-10 rounded-lg border border-borderSubtle px-3 py-2 text-sm transition hover:border-themeBlue disabled:cursor-not-allowed disabled:opacity-40"
            >
              {pending === scenario ? t("Sending…") : t(label)}
            </button>
          ))}
        </div>
        {!allowed && (
          <p className="text-xs text-themeTextGray">
            {t("Engineer permission is required to change simulation scenarios.")}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-statusRed">
            {t(error)}
          </p>
        )}
      </DashboardCard>
    </div>
  );
};

export default BmsPage;

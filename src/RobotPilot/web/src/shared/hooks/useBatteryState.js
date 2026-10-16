import { useEffect, useState } from "react";

import { useRos, useRosStatus } from "../../app/App";
import { AppConfig } from "../constants";

export const parseBatteryState = (message) => {
  try {
    const state = typeof message === "string" ? JSON.parse(message) : message;
    if (!state || typeof state.available !== "boolean") return null;
    if (!["simulated", "hardware", "unavailable"].includes(state.source))
      return null;
    if (
      typeof state.observed_at !== "string" ||
      !Number.isFinite(Date.parse(state.observed_at))
    )
      return null;
    if (
      state.percent !== null &&
      (!Number.isFinite(Number(state.percent)) ||
        Number(state.percent) < 0 ||
        Number(state.percent) > 100)
    )
      return null;
    return {
      percent: state.percent === null ? null : Number(state.percent),
      source: state.source,
      simulated: state.source === "simulated",
      available: state.available,
      charging: typeof state.charging === "boolean" ? state.charging : null,
      charging_state:
        typeof state.charging_state === "string"
          ? state.charging_state
          : "unknown",
      voltage_v:
        state.voltage_v != null && Number.isFinite(Number(state.voltage_v))
          ? Number(state.voltage_v)
          : null,
      current_a:
        state.current_a != null && Number.isFinite(Number(state.current_a))
          ? Number(state.current_a)
          : null,
      low_battery: state.low_battery === true,
      return_to_charge_state:
        typeof state.return_to_charge_state === "string"
          ? state.return_to_charge_state
          : "not_available",
      fault: typeof state.fault === "string" ? state.fault : "",
      low_battery_threshold:
        state.low_battery_threshold != null &&
        Number.isFinite(Number(state.low_battery_threshold))
          ? Number(state.low_battery_threshold)
          : null,
      threshold_config_version:
        Number.isInteger(state.threshold_config_version) &&
        state.threshold_config_version >= 0
          ? state.threshold_config_version
          : 0,
      observed_at: state.observed_at,
      reason: typeof state.reason === "string" ? state.reason : "",
      receivedAt: Date.now(),
    };
  } catch {
    return null;
  }
};

const STALE_AFTER_MS = 10000;

const useBatteryState = () => {
  const ros = useRos();
  const rosStatus = useRosStatus();
  const [state, setState] = useState(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!ros || rosStatus !== "connected" || !window.ROSLIB) return undefined;
    const topic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.BATTERY_STATE_TOPIC,
      messageType: "std_msgs/String",
    });
    topic.subscribe(({ data }) => {
      const next = parseBatteryState(data);
      if (next) setState(next);
    });
    return () => topic.unsubscribe();
  }, [ros, rosStatus]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const stale = !state || now - state.receivedAt > STALE_AFTER_MS;
  return { state, stale, usable: Boolean(state?.available && !stale) };
};

export default useBatteryState;

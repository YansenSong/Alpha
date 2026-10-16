import { useEffect, useRef } from "react";

import { useRos } from "../app/App";
import { AppConfig } from "../shared/constants";
import { addEvent } from "../shared/events/eventLog";

const NAV_TERMINAL = {
  4: { severity: "success", message: "Navigation goal succeeded" },
  5: { severity: "warning", message: "Navigation goal canceled" },
  6: { severity: "error", message: "Navigation goal failed" },
};

const LOW_BATTERY = 20; // percent; matches NotificationsWatcher's default band

/**
 * 无界面、始终挂载于 AppLayout 的记录器，会将关键机器人事件写成可持久保存和回顾的时间线（见 shared/events/eventLog.js）。
 * NotificationsWatcher 需要用户启用，且只显示临时桌面通知；本组件始终记录事件，便于操作员事后查看。
 * 事件写入共用日志，由 Events 页面读取。
 */
const EventRecorder = () => {
  const ros = useRos();
  const lowBatteryArmedRef = useRef(true);

  useEffect(() => {
    if (!ros || !window.ROSLIB) return undefined;

    const subs = [];
    const sub = (name, messageType, handler) => {
      const topic = new window.ROSLIB.Topic({ ros, name, messageType });
      topic.subscribe(handler);
      subs.push(topic);
    };

    sub(AppConfig.NAV_STATUS_TOPIC, "action_msgs/GoalStatusArray", (msg) => {
      if (!msg.status_list?.length) return;
      const latest = msg.status_list[msg.status_list.length - 1];
      const info = NAV_TERMINAL[latest.status];
      if (!info) return;
      const key = latest.goal_info?.goal_id?.uuid?.join?.("-") || latest.status;
      addEvent({
        type: "navigation",
        severity: info.severity,
        message: info.message,
        dedupeKey: `nav-${key}-${latest.status}`,
      });
    });

    sub(AppConfig.DOCK_TRIGGER_STATUS_TOPIC, "std_msgs/String", (msg) => {
      if (msg.data === "docked") {
        addEvent({
          type: "docking",
          severity: "success",
          message: "Docking complete",
          dedupeKey: "dock-docked",
        });
      } else if (msg.data === "failed") {
        addEvent({
          type: "docking",
          severity: "error",
          message: "Docking failed",
          dedupeKey: "dock-failed",
        });
      } else if (msg.data === "undocked") {
        addEvent({
          type: "docking",
          severity: "info",
          message: "Undocked",
          dedupeKey: "dock-undocked",
        });
      }
    });

    sub(AppConfig.BATTERY_STATE_TOPIC, "std_msgs/String", ({ data }) => {
      let state;
      try {
        state = JSON.parse(data);
      } catch {
        return;
      }
      if (
        !state?.available ||
        state.stale ||
        !Number.isFinite(Number(state.percent))
      )
        return;
      const percent = Number(state.percent);
      if (percent <= LOW_BATTERY && lowBatteryArmedRef.current) {
        lowBatteryArmedRef.current = false;
        addEvent({
          type: "battery",
          severity: "warning",
          message: `${
            state.simulated ? "Simulated battery low" : "Battery low"
          }: ${Math.round(percent)}%`,
        });
      } else if (percent > LOW_BATTERY + 5) {
        lowBatteryArmedRef.current = true;
      }
    });

    return () => subs.forEach((t) => t.unsubscribe());
  }, [ros]);

  return null;
};

export default EventRecorder;

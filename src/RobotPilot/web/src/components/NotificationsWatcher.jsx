import { useEffect, useRef } from "react";

import { useRos, useRuntimeConfig } from "../app/App";
import { AppConfig } from "../shared/constants";
import useBatteryState from "../shared/hooks/useBatteryState";

const NAV_TERMINAL_LABELS = {
  4: "Navigation succeeded",
  5: "Navigation canceled",
  6: "Navigation failed",
};

const notify = (title, body) => {
  if (
    typeof Notification === "undefined" ||
    Notification.permission !== "granted"
  )
    return;
  try {
    // 即发即弃；无需保留此实例的引用。
    const notification = new Notification(title, { body });
    return notification;
  } catch {
    // 部分平台（例如 Android Chrome）只允许通过 service worker 显示通知，直接构造时会抛出异常。
    // 这不是致命错误，跳过通知即可。
  }
};

/**
 * 无界面、始终挂载于 AppLayout 的监听器，在导航目标完成、对接结束/失败或电量低于阈值等关键事件发生时，
 * 通过浏览器 Notification API 提醒操作员，使其无需一直将此标签页停留在特定页面。由 Config 页的
 * config.notificationsEnabled 控制，默认关闭。
 */
const NotificationsWatcher = () => {
  const ros = useRos();
  const { config } = useRuntimeConfig();
  const batteryTelemetry = useBatteryState();
  const lastNavTerminalRef = useRef(null);
  const lowBatteryNotifiedRef = useRef(false);

  useEffect(() => {
    if (!config.notificationsEnabled || !ros || !window.ROSLIB) return;

    const navStatusTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.NAV_STATUS_TOPIC,
      messageType: "action_msgs/GoalStatusArray",
    });
    navStatusTopic.subscribe((msg) => {
      if (!msg.status_list?.length) return;
      const latest = msg.status_list[msg.status_list.length - 1];
      if (![4, 5, 6].includes(latest.status)) return;
      const key = latest.goal_info?.goal_id?.uuid?.join?.("-") || latest.status;
      if (lastNavTerminalRef.current === key) return;
      lastNavTerminalRef.current = key;
      notify("RobotPilot", NAV_TERMINAL_LABELS[latest.status]);
    });

    const dockStatusTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.DOCK_TRIGGER_STATUS_TOPIC,
      messageType: "std_msgs/String",
    });
    dockStatusTopic.subscribe((msg) => {
      if (msg.data === "docked") notify("RobotPilot", "Docking complete");
      else if (msg.data === "failed")
        notify("RobotPilot", "Docking failed — check the dock tag and logs");
    });

    return () => {
      navStatusTopic.unsubscribe();
      dockStatusTopic.unsubscribe();
    };
  }, [ros, config.notificationsEnabled, config.lowBatteryThreshold]);

  useEffect(() => {
    if (!config.notificationsEnabled || !batteryTelemetry.usable) return;
    const percent = batteryTelemetry.state.percent;
    const threshold = config.lowBatteryThreshold;
    if (percent <= threshold) {
      if (!lowBatteryNotifiedRef.current) {
        lowBatteryNotifiedRef.current = true;
        const sourceTag = batteryTelemetry.state.simulated
          ? " [SIMULATION]"
          : "";
        notify(
          "RobotPilot",
          `Battery at ${Math.round(
            percent,
          )}% — below ${threshold}%${sourceTag}`,
        );
      }
    } else if (percent > threshold + 5) {
      lowBatteryNotifiedRef.current = false;
    }
  }, [
    config.notificationsEnabled,
    config.lowBatteryThreshold,
    batteryTelemetry,
  ]);

  return null;
};

export default NotificationsWatcher;

import { T, useT } from "../shared/i18n/i18n";
import React, { useEffect, useRef, useState } from "react";
import { useRos } from "../app/App";
import { useRoleAccess } from "../shared/auth/roleAccess";
import { LIFECYCLE_NODES as NODES } from "../shared/constants";

const TRANSITIONS = {
  configure: 1,
  cleanup: 2,
  activate: 3,
  deactivate: 4,
};

const COLORS = {
  active: "text-statusGreen",
  inactive: "text-statusYellow",
  unconfigured: "text-statusRed",
  unknown: "text-themeTextGray",
};

const DOTS = {
  active: "bg-statusGreen",
  inactive: "bg-statusYellow",
  unconfigured: "bg-statusRed",
  unknown: "bg-themeTextGray",
};

const EXPLANATIONS = {
  active: "Configured and running normally.",
  inactive: "Configured but idle — call Activate to bring it online.",
  unconfigured:
    "Not configured yet — call Configure, or it's a fresh restart. Normal right after Nav2 launches, before activation.",
  unknown:
    "We couldn't check this system's status — it may be off, or the robot's connection may be down.",
};

// 每行对应的 ROS 内部节点的通俗名称。
// 导出此映射，让其他引用相同节点名称的位置（如 Health 页面的问题列表）可以显示统一的易读名称。
export const FRIENDLY_NAMES = {
  map_server: "Map data",
  planner: "Path planning",
};

// These controls affect the map and planner lifecycle nodes used by this stack.
const ACTION_LABELS = {
  configure: {
    full: "Prepare",
    compact: "Prep",
    title: "Load configuration for the map and path planner.",
  },
  activate: {
    full: "Start",
    compact: "Start",
    title: "Activate the map and path planner.",
  },
  deactivate: {
    full: "Pause",
    compact: "Pause",
    title: "Pause the map and path planner.",
  },
  cleanup: {
    full: "Reset",
    compact: "Reset",
    title: "Reset the map and path planner to unconfigured.",
  },
};
const CONFIRM_BEFORE = {
  deactivate: "Pause the map and path planner?",
  cleanup: "Reset the map and path planner to unconfigured?",
};

const normalizeState = (label) => (label || "unknown").toLowerCase();

const LifecycleStatus = ({ compact = false, onStatesChange }) => {
  const { t } = useT();
  const ros = useRos();
  const lifecycleAccess = useRoleAccess("Engineer");
  const clientsRef = useRef({});
  const changeClientsRef = useRef({});
  const [states, setStates] = useState(() =>
    Object.fromEntries(NODES.map(({ name }) => [name, "unknown"])),
  );
  const [showLegend, setShowLegend] = useState(false);
  const onStatesChangeRef = useRef(onStatesChange);
  onStatesChangeRef.current = onStatesChange;

  useEffect(() => {
    if (!ros || !window.ROSLIB) return;

    clientsRef.current = Object.fromEntries(
      NODES.map(({ name, base }) => [
        name,
        new window.ROSLIB.Service({
          ros,
          name: `${base}/get_state`,
          serviceType: "lifecycle_msgs/srv/GetState",
        }),
      ]),
    );
    changeClientsRef.current = Object.fromEntries(
      NODES.map(({ name, base }) => [
        name,
        new window.ROSLIB.Service({
          ros,
          name: `${base}/change_state`,
          serviceType: "lifecycle_msgs/srv/ChangeState",
        }),
      ]),
    );

    const poll = () => {
      NODES.forEach(({ name }) => {
        const client = clientsRef.current[name];
        if (!client) return;
        client.callService(
          new window.ROSLIB.ServiceRequest({}),
          (response) => {
            const nextState = normalizeState(response?.current_state?.label);
            setStates((prev) => {
              const next = { ...prev, [name]: nextState };
              onStatesChangeRef.current?.(next);
              return next;
            });
          },
          () =>
            setStates((prev) => {
              const next = { ...prev, [name]: "unknown" };
              onStatesChangeRef.current?.(next);
              return next;
            }),
        );
      });
    };

    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, [ros]);

  const changeAll = (transitionName) => {
    if (!lifecycleAccess.allowed) return;
    const id = TRANSITIONS[transitionName];
    if (!id || !window.ROSLIB) return;
    const confirmMessage = CONFIRM_BEFORE[transitionName];
    if (confirmMessage && !window.confirm(t(confirmMessage))) return;
    NODES.forEach(({ name }) => {
      const client = changeClientsRef.current[name];
      if (!client) return;
      client.callService(
        new window.ROSLIB.ServiceRequest({
          transition: { id, label: transitionName },
        }),
        () => {},
        () => {},
      );
    });
  };

  if (compact) {
    return (
      <div className="flex min-h-0 flex-col font-[RobotoMono]">
        <div className="mb-2 flex items-center justify-between gap-3">
          <p className="text-xs uppercase tracking-wider text-themeTextGray">
            <T>{"Lifecycle"}</T>{" "}
          </p>
          <button
            onClick={() => setShowLegend((v) => !v)}
            aria-label={t("What do these states mean?")}
            title={t("What do these states mean?")}
            className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-borderSubtle text-[10px] text-themeTextGray hover:border-themeBlue hover:text-themeBlue"
          >
            ?
          </button>
        </div>

        {showLegend && (
          <div className="mb-2 space-y-1 rounded-lg bg-bgSurface p-2 text-[10px] leading-snug text-themeTextGray">
            {Object.entries(EXPLANATIONS).map(([state, text]) => (
              <p key={state}>
                <span className={`font-semibold ${COLORS[state]}`}>
                  {t(state)}
                </span>
                : {t(text)}
              </p>
            ))}
          </div>
        )}

        <div className="mb-2 grid grid-cols-2 gap-1.5">
          <button
            onClick={() => changeAll("configure")}
            title={
              lifecycleAccess.allowed
                ? t(ACTION_LABELS.configure.title)
                : t(lifecycleAccess.reason)
            }
            disabled={!lifecycleAccess.allowed}
            className="rounded-md border border-borderSubtle px-2 py-1 text-[11px] text-themeBlue hover:border-themeBlue"
          >
            {t(ACTION_LABELS.configure.compact)}
          </button>
          <button
            onClick={() => changeAll("activate")}
            title={
              lifecycleAccess.allowed
                ? t(ACTION_LABELS.activate.title)
                : t(lifecycleAccess.reason)
            }
            disabled={!lifecycleAccess.allowed}
            className="rounded-md border border-borderSubtle px-2 py-1 text-[11px] text-statusGreen hover:border-statusGreen"
          >
            {t(ACTION_LABELS.activate.compact)}
          </button>
          <button
            onClick={() => changeAll("deactivate")}
            title={
              lifecycleAccess.allowed
                ? t(ACTION_LABELS.deactivate.title)
                : t(lifecycleAccess.reason)
            }
            disabled={!lifecycleAccess.allowed}
            className="rounded-md border border-borderSubtle px-2 py-1 text-[11px] text-statusYellow hover:border-statusYellow"
          >
            {t(ACTION_LABELS.deactivate.compact)}
          </button>
          <button
            onClick={() => changeAll("cleanup")}
            title={
              lifecycleAccess.allowed
                ? t(ACTION_LABELS.cleanup.title)
                : t(lifecycleAccess.reason)
            }
            disabled={!lifecycleAccess.allowed}
            className="rounded-md border border-borderSubtle px-2 py-1 text-[11px] text-statusRed hover:border-statusRed"
          >
            {t(ACTION_LABELS.cleanup.compact)}
          </button>
        </div>

        <div className="grid grid-cols-1 gap-1.5">
          {NODES.map(({ name }) => {
            const state = states[name] || "unknown";
            return (
              <div
                key={name}
                className="flex items-center justify-between gap-2 rounded-md bg-bgSurface px-2 py-1 text-[11px]"
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      DOTS[state] || DOTS.unknown
                    }`}
                  />
                  <span className="truncate text-textWhiteHover" title={name}>
                    {t(FRIENDLY_NAMES[name] || name)}
                  </span>
                </span>
                <span className={`shrink-0 ${COLORS[state] || COLORS.unknown}`}>
                  {t(state)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`dashboard-card font-[RobotoMono] ${compact ? "p-3" : "p-4"}`}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-xs uppercase tracking-wider text-themeTextGray">
          <T>{"Lifecycle"}</T>{" "}
        </p>
        <button
          onClick={() => setShowLegend((v) => !v)}
          aria-label={t("What do these states mean?")}
          title={t("What do these states mean?")}
          className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-borderSubtle text-[10px] text-themeTextGray hover:border-themeBlue hover:text-themeBlue"
        >
          ?
        </button>
      </div>

      {showLegend && (
        <div className="mb-2 space-y-1 rounded-lg bg-bgSurface p-2 text-[11px] leading-snug text-themeTextGray">
          {Object.entries(EXPLANATIONS).map(([state, text]) => (
            <p key={state}>
              <span className={`font-semibold ${COLORS[state]}`}>
                {t(state)}
              </span>
              : {t(text)}
            </p>
          ))}
        </div>
      )}

      <div className="mb-2 grid grid-cols-2 gap-1.5">
        <button
          onClick={() => changeAll("configure")}
          title={
            lifecycleAccess.allowed
              ? t(ACTION_LABELS.configure.title)
              : t(lifecycleAccess.reason)
          }
          disabled={!lifecycleAccess.allowed}
          className="rounded-lg border border-borderSubtle px-2 py-1 text-xs text-themeBlue hover:border-themeBlue"
        >
          {t(ACTION_LABELS.configure.full)}
        </button>
        <button
          onClick={() => changeAll("activate")}
          title={
            lifecycleAccess.allowed
              ? t(ACTION_LABELS.activate.title)
              : t(lifecycleAccess.reason)
          }
          disabled={!lifecycleAccess.allowed}
          className="rounded-lg border border-borderSubtle px-2 py-1 text-xs text-statusGreen hover:border-statusGreen"
        >
          {t(ACTION_LABELS.activate.full)}
        </button>
        <button
          onClick={() => changeAll("deactivate")}
          title={
            lifecycleAccess.allowed
              ? t(ACTION_LABELS.deactivate.title)
              : t(lifecycleAccess.reason)
          }
          disabled={!lifecycleAccess.allowed}
          className="rounded-lg border border-borderSubtle px-2 py-1 text-xs text-statusYellow hover:border-statusYellow"
        >
          {t(ACTION_LABELS.deactivate.full)}
        </button>
        <button
          onClick={() => changeAll("cleanup")}
          title={
            lifecycleAccess.allowed
              ? t(ACTION_LABELS.cleanup.title)
              : t(lifecycleAccess.reason)
          }
          disabled={!lifecycleAccess.allowed}
          className="rounded-lg border border-borderSubtle px-2 py-1 text-xs text-statusRed hover:border-statusRed"
        >
          {t(ACTION_LABELS.cleanup.full)}
        </button>
      </div>
      <div
        className={`grid gap-1.5 ${
          compact ? "grid-cols-1" : "grid-cols-1 sm:grid-cols-2"
        }`}
      >
        {NODES.map(({ name }) => {
          const state = states[name] || "unknown";
          return (
            <div key={name} className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    DOTS[state] || DOTS.unknown
                  }`}
                />
                <span className="text-xs text-textWhiteHover" title={name}>
                  {t(FRIENDLY_NAMES[name] || name)}
                </span>
              </div>
              <span className={`text-xs ${COLORS[state] || COLORS.unknown}`}>
                {t(state)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default LifecycleStatus;

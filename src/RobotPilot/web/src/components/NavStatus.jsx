import { T, useT } from "../shared/i18n/i18n";
import React, { useEffect, useState } from "react";

import { useRos } from "../app/App";
import { AppConfig } from "../shared/constants";

const STALE_AFTER_MS = 3000;

const STATUS = {
  0: {
    label: "Waiting for goal",
    color: "text-themeTextGray",
    dot: "bg-themeTextGray",
  },
  1: {
    label: "Planning",
    color: "text-statusBlue",
    dot: "bg-statusBlue",
  },
  2: {
    label: "Moving",
    color: "text-statusGreen",
    dot: "bg-statusGreen",
  },
  3: {
    label: "Arrived",
    color: "text-statusGreen",
    dot: "bg-statusGreen",
  },
  4: {
    label: "Failed",
    color: "text-statusRed",
    dot: "bg-statusRed",
  },
};

const UNKNOWN = {
  label: "No status data",
  color: "text-themeTextGray",
  dot: "bg-themeTextGray",
};

const NavStatus = () => {
  const { t } = useT();
  const ros = useRos();
  const [message, setMessage] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!ros || !window.ROSLIB) return undefined;

    const topic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.NAVIGATION_STATE_TOPIC,
      messageType: AppConfig.NAVIGATION_STATE_TYPE,
    });
    const handler = (next) => {
      setMessage(next);
      setLastUpdate(Date.now());
    };
    topic.subscribe(handler);
    return () => topic.unsubscribe(handler);
  }, [ros]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const stale = lastUpdate == null || now - lastUpdate > STALE_AFTER_MS;
  const info = stale ? UNKNOWN : STATUS[message?.state] || UNKNOWN;
  const active = !stale && (message?.state === 1 || message?.state === 2);

  return (
    <div className="dashboard-card px-4 py-1.5 font-[RobotoMono]">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <div className="relative flex h-2.5 w-2.5 shrink-0">
            {active && (
              <span
                className={`absolute inline-flex h-full w-full animate-ping rounded-full ${info.dot} opacity-60`}
              />
            )}
            <span
              className={`relative inline-flex h-2.5 w-2.5 rounded-full ${info.dot}`}
            />
          </div>
          <div className="min-w-0">
            <span className="text-xs uppercase tracking-wider text-themeTextGray">
              <T>{"Navigation status"}</T>{" "}
            </span>
            <span className={`text-sm font-semibold ${info.color}`}>
              {t(info.label)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default NavStatus;

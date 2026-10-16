import { T, useT } from "../shared/i18n/i18n";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useRos } from "../app/App";

// rcl_interfaces/msg/Log 的严重程度级别（ROS 2）。低于所选最低级别的消息会在客户端过滤。
const LEVELS = {
  10: {
    label: "DEBUG",
    color: "text-themeTextGray",
    chip: "border-borderSubtle text-themeTextGray",
  },
  20: {
    label: "INFO",
    color: "text-statusGreen",
    chip: "border-statusGreen/40 text-statusGreen",
  },
  30: {
    label: "WARN",
    color: "text-statusYellow",
    chip: "border-statusYellow/40 text-statusYellow",
  },
  40: {
    label: "ERROR",
    color: "text-statusRed",
    chip: "border-statusRed/40 text-statusRed",
  },
  50: {
    label: "FATAL",
    color: "text-statusRed",
    chip: "border-statusRed/60 text-statusRed",
  },
};

const LEVEL_OPTIONS = [
  [10, "Debug+"],
  [20, "Info+"],
  [30, "Warn+"],
  [40, "Error+"],
  [50, "Fatal"],
];

const MAX_LOGS = 1000;

const fmtTime = (stamp) => {
  if (!stamp) return "";
  const ms = stamp.sec * 1000 + Math.round((stamp.nanosec || 0) / 1e6);
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  return (
    d.toLocaleTimeString(undefined, { hour12: false }) +
    "." +
    String(d.getMilliseconds()).padStart(3, "0")
  );
};

/**
 * 实时 /rosout 控制台。订阅 rcl_interfaces/msg/Log，并提供可筛选、可暂停的消息流，操作员无需在加载 ROS 环境的终端中操作，
 * 即可从浏览器调试。收到的消息先缓存在 ref 中，再以每秒数次的频率刷新到 React state；启动或故障期间，
 * /rosout 的消息突发速率可能远高于合理的重新渲染频率。
 */
const RosoutConsole = () => {
  const { t } = useT();
  const ros = useRos();
  const [logs, setLogs] = useState([]);
  const [minLevel, setMinLevel] = useState(20);
  const [nodeFilter, setNodeFilter] = useState("");
  const [textFilter, setTextFilter] = useState("");
  const [paused, setPaused] = useState(false);
  const [autoscroll, setAutoscroll] = useState(true);

  const bufferRef = useRef([]);
  const pausedRef = useRef(paused);
  const seqRef = useRef(0);
  const listRef = useRef(null);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    if (!ros || !window.ROSLIB) return undefined;

    const topic = new window.ROSLIB.Topic({
      ros,
      name: "/rosout",
      messageType: "rcl_interfaces/msg/Log",
    });

    const handler = (msg) => {
      if (pausedRef.current) return;
      bufferRef.current.push({
        id: seqRef.current++,
        level: msg.level,
        name: msg.name || "",
        msg: msg.msg || "",
        stamp: msg.stamp,
      });
    };

    topic.subscribe(handler);
    return () => topic.unsubscribe(handler);
  }, [ros]);

  // 以约 5 Hz 的频率将缓冲区刷新到 state，并限制为最新的 MAX_LOGS 条消息。
  useEffect(() => {
    const id = setInterval(() => {
      if (!bufferRef.current.length) return;
      const incoming = bufferRef.current;
      bufferRef.current = [];
      setLogs((prev) => {
        const next = prev.concat(incoming);
        return next.length > MAX_LOGS
          ? next.slice(next.length - MAX_LOGS)
          : next;
      });
    }, 200);
    return () => clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    const node = nodeFilter.trim().toLowerCase();
    const text = textFilter.trim().toLowerCase();
    return logs.filter((l) => {
      if (l.level < minLevel) return false;
      if (node && !l.name.toLowerCase().includes(node)) return false;
      if (text && !l.msg.toLowerCase().includes(text)) return false;
      return true;
    });
  }, [logs, minLevel, nodeFilter, textFilter]);

  // 启用自动滚动时，保持视图定位在最新一行。
  useEffect(() => {
    if (!autoscroll || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [filtered, autoscroll]);

  return (
    <article className="dashboard-card flex h-full min-h-0 w-full flex-col overflow-hidden font-[RobotoMono]">
      <header className="flex flex-wrap items-center gap-2 border-b border-borderSubtle bg-bgSurface px-3 py-2">
        <h2
          className="mr-1 text-sm font-semibold uppercase tracking-wider text-themeBlue"
          title="/rosout"
        >
          <T>{"System Log"}</T>{" "}
        </h2>

        <select
          value={minLevel}
          onChange={(e) => setMinLevel(Number(e.target.value))}
          className="rounded-lg border border-borderSubtle bg-bgCard px-2 py-1 text-xs text-textWhiteHover"
        >
          {LEVEL_OPTIONS.map(([v, l]) => (
            <option key={v} value={v}>
              {t(l)}
            </option>
          ))}
        </select>

        <input
          value={nodeFilter}
          onChange={(e) => setNodeFilter(e.target.value)}
          placeholder={t("node…")}
          className="w-24 rounded-lg border border-borderSubtle bg-bgCard px-2 py-1 text-xs text-textWhiteHover placeholder:text-themeTextGray"
        />
        <input
          value={textFilter}
          onChange={(e) => setTextFilter(e.target.value)}
          placeholder={t("search text…")}
          className="min-w-[100px] flex-1 rounded-lg border border-borderSubtle bg-bgCard px-2 py-1 text-xs text-textWhiteHover placeholder:text-themeTextGray"
        />

        <label className="flex items-center gap-1 text-[10px] uppercase text-themeTextGray">
          <input
            type="checkbox"
            checked={autoscroll}
            onChange={(e) => setAutoscroll(e.target.checked)}
            className="accent-themeBlue"
          />
          <T>{"Follow"}</T>{" "}
        </label>

        <button
          onClick={() => setPaused((p) => !p)}
          className={`rounded-lg border px-3 py-1 text-xs transition-colors ${
            paused
              ? "border-statusYellow text-statusYellow"
              : "border-borderSubtle text-themeTextGray hover:border-themeBlue hover:text-themeBlue"
          }`}
        >
          {t(paused ? "Resume" : "Pause")}
        </button>
        <button
          onClick={() => {
            bufferRef.current = [];
            setLogs([]);
          }}
          className="rounded-lg border border-borderSubtle px-3 py-1 text-xs text-themeTextGray transition-colors hover:border-themeBlue hover:text-themeBlue"
        >
          <T>{"Clear"}</T>{" "}
        </button>
      </header>

      <div
        ref={listRef}
        className="flex-1 overflow-y-auto px-2 py-1 text-xs leading-relaxed"
      >
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-themeTextGray opacity-50">
            {t(
              logs.length === 0
                ? "Waiting for /rosout…"
                : "No messages match the filters",
            )}
          </div>
        ) : (
          filtered.map((l) => {
            const info = LEVELS[l.level] || LEVELS[20];
            return (
              <div
                key={l.id}
                className="flex gap-2 border-b border-borderSubtle/20 py-0.5 last:border-0"
              >
                <span className="shrink-0 text-themeTextGray opacity-70">
                  {fmtTime(l.stamp)}
                </span>
                <span className={`w-11 shrink-0 font-semibold ${info.color}`}>
                  {info.label}
                </span>
                <span className="shrink-0 text-themeBlue/80">[{l.name}]</span>
                <span className="min-w-0 break-words text-textWhiteHover">
                  {l.msg}
                </span>
              </div>
            );
          })
        )}
      </div>

      <footer className="border-t border-borderSubtle bg-bgSurface px-3 py-1 text-[10px] uppercase tracking-wider text-themeTextGray">
        {filtered.length} <T>{"shown ·"}</T> {logs.length}/{MAX_LOGS}{" "}
        <T>{"buffered"}</T> {paused && " · paused"}
      </footer>
    </article>
  );
};

export default RosoutConsole;

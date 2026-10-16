import { T, useT } from "../shared/i18n/i18n";
import React, { useEffect, useRef, useState } from "react";
import { useRos, useRosStatus } from "../app/App";

const MAX_MESSAGES = 50;

/**
 * Browse the current ROS graph and stream raw JSON messages from a selected
 * topic, similar to `ros2 topic echo`.
 */
const TopicEcho = () => {
  const { t } = useT();
  const ros = useRos();
  const rosStatus = useRosStatus();
  const [topicName, setTopicName] = useState("");
  const [topics, setTopics] = useState([]);
  const [topicsStatus, setTopicsStatus] = useState("loading");
  const [topicsRefresh, setTopicsRefresh] = useState(0);
  const [active, setActive] = useState(null); // { name, type }
  const [messages, setMessages] = useState([]);
  const [count, setCount] = useState(0);

  const topicRef = useRef(null);
  const seqRef = useRef(0);
  const selectedTopic = topics.find((topic) => topic.name === topicName);

  const stop = () => {
    if (topicRef.current) {
      try {
        topicRef.current.unsubscribe();
      } catch (e) {
        // ignore
      }
      topicRef.current = null;
    }
    setActive(null);
  };

  useEffect(() => stop, []); // unsubscribe on unmount

  useEffect(() => {
    if (!ros || rosStatus !== "connected") {
      setTopics([]);
      setTopicName("");
      setTopicsStatus("offline");
      return undefined;
    }

    if (typeof ros.getTopics !== "function") {
      setTopics([]);
      setTopicsStatus("error");
      return undefined;
    }

    let cancelled = false;
    setTopicsStatus("loading");
    ros.getTopics(
      (result) => {
        if (cancelled) return;
        const names = Array.isArray(result?.topics) ? result.topics : [];
        const types = Array.isArray(result?.types) ? result.types : [];
        const byName = new Map();
        names.forEach((name, index) => {
          if (typeof name !== "string" || !name.startsWith("/")) return;
          byName.set(name, {
            name,
            type: typeof types[index] === "string" ? types[index] : "",
          });
        });
        const availableTopics = [...byName.values()].sort((a, b) =>
          a.name.localeCompare(b.name),
        );
        setTopics(availableTopics);
        setTopicName((current) =>
          availableTopics.some((topic) => topic.name === current) ? current : "",
        );
        setTopicsStatus(availableTopics.length ? "ready" : "empty");
      },
      () => {
        if (cancelled) return;
        setTopics([]);
        setTopicName("");
        setTopicsStatus("error");
      },
    );

    return () => {
      cancelled = true;
    };
  }, [ros, rosStatus, topicsRefresh]);

  const start = () => {
    if (!ros || !window.ROSLIB || !selectedTopic) return;
    stop();
    setMessages([]);
    setCount(0);
    seqRef.current = 0;

    const { name, type } = selectedTopic;
    const topic = new window.ROSLIB.Topic({
      ros,
      name,
      messageType: type || undefined,
    });

    topic.subscribe((msg) => {
      setCount((c) => c + 1);
      setMessages((prev) => {
        const entry = {
          id: seqRef.current++,
          t: new Date().toLocaleTimeString(undefined, { hour12: false }),
          body: JSON.stringify(msg, null, 2),
        };
        const next = [entry, ...prev];
        return next.length > MAX_MESSAGES ? next.slice(0, MAX_MESSAGES) : next;
      });
    });

    topicRef.current = topic;
    setActive({ name, type });
  };

  return (
    <article className="dashboard-card flex h-full min-h-0 w-full flex-col overflow-hidden font-[RobotoMono]">
      <header className="flex flex-wrap items-center gap-2 border-b border-borderSubtle bg-bgSurface px-3 py-2">
        <h2 className="mr-1 text-sm font-semibold uppercase tracking-wider text-themeBlue">
          <T>{"Topic Echo"}</T>{" "}
        </h2>
        <p className="w-full text-[11px] text-themeTextGray">
          <T>
            {
              "Select a currently active topic to inspect its messages."
            }
          </T>{" "}
        </p>
        <select
          value={topicName}
          onChange={(e) => setTopicName(e.target.value)}
          disabled={Boolean(active) || topicsStatus !== "ready"}
          aria-label={t("Topic name")}
          className="min-w-0 flex-1 rounded-lg border border-borderSubtle bg-bgCard px-2 py-1 text-xs text-textWhiteHover disabled:opacity-60"
        >
          <option value="">
            {topicsStatus === "offline"
              ? t("ROS bridge is disconnected")
              : topicsStatus === "loading"
              ? t("Loading available topics…")
              : topicsStatus === "error"
              ? t("Topic list unavailable")
              : topicsStatus === "empty"
              ? t("No active topics found")
              : t("Select a topic")}
          </option>
          {topics.map((topic) => (
            <option key={topic.name} value={topic.name}>
              {topic.name}{topic.type ? ` · ${topic.type}` : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setTopicsRefresh((current) => current + 1)}
          disabled={rosStatus !== "connected" || topicsStatus === "loading"}
          aria-label={t("Refresh topics")}
          title={t("Refresh topics")}
          className="rounded-lg border border-borderSubtle px-2 py-1 text-xs text-themeTextGray transition-colors hover:border-themeBlue hover:text-themeBlue disabled:opacity-50"
        >
          <T>{"Refresh topics"}</T>{" "}
        </button>
        {active ? (
          <button
            onClick={stop}
            className="rounded-lg border border-statusRed px-3 py-1 text-xs text-statusRed transition-colors hover:bg-statusRed hover:text-white"
          >
            <T>{"Stop"}</T>{" "}
          </button>
        ) : (
          <button
            type="button"
            onClick={start}
            disabled={!selectedTopic}
            className="rounded-lg border border-themeBlue px-3 py-1 text-xs text-themeBlue transition-colors hover:bg-themeBlue hover:text-white disabled:opacity-50"
          >
            <T>{"Echo"}</T>{" "}
          </button>
        )}
      </header>

      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-y-contain px-2 py-1 text-xs">
        {!active ? (
          <div className="flex h-full items-center justify-center px-4 text-center text-themeTextGray opacity-50">
            <T>{"Select a topic and press Echo to stream its messages."}</T>{" "}
          </div>
        ) : messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-themeTextGray opacity-50">
            <T>{"Subscribed to"}</T> {active.name}{" "}
            <T>{"— waiting for a message…"}</T>{" "}
          </div>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className="border-b border-borderSubtle/20 py-1 last:border-0"
            >
              <span className="text-[10px] uppercase text-themeTextGray opacity-70">
                {m.t}
              </span>
              <pre className="mt-0.5 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-[11px] text-textWhiteHover">
                {m.body}
              </pre>
            </div>
          ))
        )}
      </div>

      {active && (
        <footer className="border-t border-borderSubtle bg-bgSurface px-3 py-1 text-[10px] uppercase tracking-wider text-themeTextGray">
          {active.name} · {count} <T>{"msgs"}</T>{" "}
        </footer>
      )}
    </article>
  );
};

export default TopicEcho;

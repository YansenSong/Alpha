import React, { useCallback, useContext, useEffect, useState } from "react";

import { AuthContext } from "../app/App";
import { getEvents } from "../shared/events/eventLog";
import { apiFetch } from "../shared/api/apiFetch";
import {
  DashboardCard,
  EmptyState,
  SectionHeader,
} from "../shared/ui/Dashboard";

const PAGE_SIZE = 50;
const SEVERITY_STYLE = {
  INFO: "text-statusBlue",
  WARNING: "text-statusYellow",
  ERROR: "text-statusRed",
};
const TYPE_LABEL = {
  "task.event": "任务事件",
  "task.status_changed": "任务状态变化",
  "fault.raised": "故障发生",
  "fault.updated": "故障更新",
  "fault.resolved": "故障恢复",
};

const formatTime = (value) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
};

const EventsPage = () => {
  const { robotId } = useContext(AuthContext);
  const [events, setEvents] = useState([]);
  const [nextBefore, setNextBefore] = useState(null);
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [taskId, setTaskId] = useState("");
  const [requestId, setRequestId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadPage = useCallback(
    async (before = null) => {
      if (!robotId) return;
      setLoading(true);
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
        if (before) params.set("before", String(before));
        if (type) params.set("type", type);
        if (severity) params.set("severity", severity);
        if (taskId.trim()) params.set("task_id", taskId.trim());
        if (requestId.trim()) params.set("request_id", requestId.trim());
        const response = await apiFetch(
          `/api/v1/robots/${encodeURIComponent(
            robotId,
          )}/events/history?${params}`,
          { cache: "no-store" },
        );
        const payload = await response.json();
        setEvents((current) => {
          const combined = before
            ? [...current, ...(payload.events || [])]
            : payload.events || [];
          const unique = new Map(
            combined.map((event) => [event.event_id, event]),
          );
          return [...unique.values()].sort((a, b) => b.cursor - a.cursor);
        });
        setNextBefore(payload.next_before || null);
        setError("");
      } catch (cause) {
        setError(cause.message || "事件历史加载失败");
      } finally {
        setLoading(false);
      }
    },
    [robotId, type, severity, taskId, requestId],
  );

  useEffect(() => {
    setEvents([]);
    setNextBefore(null);
    loadPage();
  }, [loadPage]);

  useEffect(() => {
    if (!robotId || typeof EventSource === "undefined") return undefined;
    const stream = new EventSource(
      `/api/v1/robots/${encodeURIComponent(robotId)}/events`,
      { withCredentials: true },
    );
    const refresh = () => loadPage();
    stream.addEventListener("robot_event", refresh);
    return () => {
      stream.removeEventListener("robot_event", refresh);
      stream.close();
    };
  }, [robotId, loadPage]);

  const exportLegacy = () => {
    const blob = new Blob([JSON.stringify(getEvents(), null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `robotpilot-browser-events-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="sectionHeight space-y-5 py-4 sm:py-6">
      <SectionHeader
        eyebrow="Audit"
        title="事件记录"
        description="机器人端事件由平台持久保存；浏览器断开后仍可查询。"
        action={
          <button
            type="button"
            onClick={exportLegacy}
            className="workspace-action"
          >
            导出旧浏览器记录
          </button>
        }
      />

      <DashboardCard className="workspace-card">
        <div className="workspace-card__heading">
          <h2 className="workspace-card__title">筛选事件</h2>
          <span className="workspace-card__hint">
            按类型、等级或关联 ID 缩小范围
          </span>
        </div>
        <div className="workspace-fields">
          <label className="workspace-field">
            类型
            <select
              value={type}
              onChange={(event) => setType(event.target.value)}
            >
              <option value="">全部</option>
              <option value="task.event">任务事件</option>
              <option value="task.status_changed">任务状态变化</option>
              <option value="fault.raised">故障发生</option>
              <option value="fault.updated">故障更新</option>
              <option value="fault.resolved">故障恢复</option>
            </select>
          </label>
          <label className="workspace-field">
            等级
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option value="">全部</option>
              <option value="INFO">信息</option>
              <option value="WARNING">警告</option>
              <option value="ERROR">错误</option>
            </select>
          </label>
          <label className="workspace-field">
            任务 ID
            <input
              value={taskId}
              onChange={(event) => setTaskId(event.target.value)}
            />
          </label>
          <label className="workspace-field">
            请求 ID
            <input
              value={requestId}
              onChange={(event) => setRequestId(event.target.value)}
            />
          </label>
        </div>
      </DashboardCard>

      {error && (
        <p role="alert" className="workspace-alert">
          {error}
        </p>
      )}
      <DashboardCard className="p-0">
        <div className="workspace-card__heading border-b border-borderSubtle px-4 py-4">
          <h2 className="workspace-card__title">事件列表</h2>
          <span className="workspace-card__hint">本页 {events.length} 条</span>
        </div>
        {events.length === 0 ? (
          <EmptyState
            title={loading ? "正在加载事件…" : "暂无机器人事件"}
            description="任务状态变化会在机器人端写入并同步到这里。"
          />
        ) : (
          <div className="px-4">
            <ul className="workspace-list">
              {events.map((event) => (
                <li
                  key={event.event_id}
                  className="workspace-list__item space-y-1 text-sm"
                >
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="text-xs text-themeTextGray">
                      {formatTime(event.occurred_at)}
                    </span>
                    <span
                      className={
                        SEVERITY_STYLE[event.severity] || "text-themeTextGray"
                      }
                    >
                      {event.severity}
                    </span>
                    <span>
                      {TYPE_LABEL[event.type] || event.type}：
                      {event.payload?.reason || event.payload?.message || "—"}
                    </span>
                    {event.simulation && (
                      <span className="text-xs text-themeTextGray">仿真</span>
                    )}
                  </div>
                  <div className="break-all font-[RobotoMono] text-[11px] text-themeTextGray">
                    {event.correlation?.task_id &&
                      `任务 ${event.correlation.task_id}`}
                    {event.correlation?.request_id &&
                      ` · 请求 ${event.correlation.request_id}`}
                    {` · ${event.source} #${event.source_seq}`}
                  </div>
                  <details className="pt-1">
                    <summary className="w-fit cursor-pointer text-xs font-medium text-themeBlue hover:underline">
                      完整事件详情
                    </summary>
                    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-borderSubtle bg-bgBase/50 p-3 font-[RobotoMono] text-[11px] leading-5 text-themeTextGray">
                      {JSON.stringify(event, null, 2)}
                    </pre>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        )}
      </DashboardCard>
      {nextBefore && (
        <button
          type="button"
          onClick={() => loadPage(nextBefore)}
          disabled={loading}
          className="workspace-action"
        >
          加载更早事件
        </button>
      )}
    </div>
  );
};

export default EventsPage;

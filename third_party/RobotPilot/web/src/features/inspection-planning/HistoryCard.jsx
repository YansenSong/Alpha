import React, { useContext, useEffect, useState } from "react";
import { AuthContext } from "../../app/App";
import { apiFetch } from "../../shared/api/apiFetch";
import { DashboardCard } from "../../shared/ui/Dashboard";

export default function HistoryCard({ onOpenMission }) {
  const { robotId } = useContext(AuthContext);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [tasks, setTasks] = useState([]);
  const [results, setResults] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [limited, setLimited] = useState(false);
  const [expanded, setExpanded] = useState("");
  const [error, setError] = useState("");
  const [resultDetails, setResultDetails] = useState({});
  const [refreshKey, setRefreshKey] = useState(0);
  const [focusedAlertId] = useState(
    () => new URLSearchParams(window.location.search).get("alert_id") || "",
  );
  useEffect(() => {
    if (!robotId) return;
    let active = true;
    const base = `/api/v1/robots/${encodeURIComponent(robotId)}/inspection`;
    const params = new URLSearchParams({ limit: "50" });
    if (query.trim()) params.set("q", query.trim());
    if (status) params.set("status", status);
    if (since) params.set("since", new Date(since).toISOString());
    if (until) params.set("until", new Date(until).toISOString());
    Promise.all([
      apiFetch(`${base}/tasks?${params}`, { cache: "no-store" }).then(
        (response) => response.json(),
      ),
      apiFetch(`${base}/results?limit=50`, { cache: "no-store" }).then(
        (response) => response.json(),
      ),
      apiFetch(`${base}/alerts`, { cache: "no-store" }).then((response) =>
        response.json(),
      ),
    ])
      .then(([taskData, resultData, alertData]) => {
        if (!active) return;
        setTasks(taskData.tasks || []);
        setLimited(Boolean(taskData.history_window_limited));
        setResults(resultData.results || []);
        setAlerts(alertData.alerts || []);
        setError("");
      })
      .catch((cause) => {
        if (active) setError(cause.message || "执行记录加载失败");
      });
    return () => {
      active = false;
    };
  }, [robotId, query, status, since, until, refreshKey]);
  useEffect(() => {
    if (focusedAlertId)
      document
        .getElementById(`alert-${focusedAlertId}`)
        ?.scrollIntoView?.({ block: "center" });
  }, [focusedAlertId, alerts]);
  const loadResult = async (resultId) => {
    try {
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/inspection/results/${encodeURIComponent(resultId)}`,
      );
      const detail = await response.json();
      setResultDetails((current) => ({ ...current, [resultId]: detail }));
    } catch (cause) {
      setError(cause.message || "证据元数据加载失败");
    }
  };
  return (
    <DashboardCard className="space-y-4 p-4" data-testid="history-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">执行历史与日志</h2>
        <button
          onClick={() => setRefreshKey((key) => key + 1)}
          className="rounded border border-borderSubtle px-3 py-1.5 text-xs"
        >
          刷新
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="筛选任务"
          placeholder="任务名或实例 ID"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="min-w-0 flex-1 rounded border border-borderSubtle bg-bgCard px-2 py-1.5 text-sm"
        />
        <select
          aria-label="筛选状态"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded border border-borderSubtle bg-bgCard px-2 text-xs"
        >
          <option value="">全部状态</option>
          {["running", "paused", "succeeded", "failed", "cancelled"].map(
            (value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ),
          )}
        </select>
        <input
          aria-label="开始时间"
          type="datetime-local"
          value={since}
          onChange={(event) => setSince(event.target.value)}
          className="rounded border border-borderSubtle bg-bgCard px-2 text-xs"
        />
        <input
          aria-label="结束时间"
          type="datetime-local"
          value={until}
          onChange={(event) => setUntil(event.target.value)}
          className="rounded border border-borderSubtle bg-bgCard px-2 text-xs"
        />
      </div>
      {limited && (
        <p className="text-xs text-statusYellow">
          机器人当前只提供近期运行窗口；更早记录不在此列表中。
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-statusRed">
          {error}
        </p>
      )}
      {tasks.length === 0 && (
        <p className="text-xs text-themeTextGray">暂无匹配的运行记录。</p>
      )}
      <div className="max-h-[420px] space-y-2 overflow-y-auto">
        {tasks.map((task) => {
          const linked = results.filter(
            (item) => item.task_id === task.task_id,
          );
          const taskAlerts = alerts.filter(
            (item) => item.task_id === task.task_id,
          );
          return (
            <article
              key={task.task_id}
              className="rounded border border-borderSubtle p-3 text-xs"
            >
              <button
                onClick={() =>
                  setExpanded((current) =>
                    current === task.task_id ? "" : task.task_id,
                  )
                }
                className="flex w-full flex-wrap justify-between gap-2 text-left"
              >
                <span className="font-semibold">
                  {task.mission_name || task.mission_id} · {task.status}
                </span>
                <span>
                  {task.step_index}/{task.steps_total} ·{" "}
                  {task.started_at || "时间未知"}
                </span>
              </button>
              {expanded === task.task_id && (
                <div className="mt-2 space-y-2 border-t border-borderSubtle pt-2 text-themeTextGray">
                  <p>
                    实例 {task.task_id} · 结束 {task.ended_at || "—"} · 原因{" "}
                    {task.reason || "—"}
                  </p>
                  <button
                    onClick={() => onOpenMission(task.mission_id)}
                    className="text-themeBlue underline"
                  >
                    打开任务定义
                  </button>
                  <ol>
                    {(task.events || []).map((event, index) => (
                      <li key={index}>
                        {event.timestamp || event.occurred_at || ""} ·{" "}
                        {event.status || event.type} · {event.reason || ""}
                      </li>
                    ))}
                  </ol>
                  <p>
                    巡检结果 {linked.length} 项 · 业务告警 {taskAlerts.length}{" "}
                    项
                  </p>
                  {linked.map((item) => (
                    <div key={item.inspection_result_id}>
                      <button
                        onClick={() => loadResult(item.inspection_result_id)}
                        className="text-left text-themeBlue underline"
                      >
                        {item.outcome} · {item.source} · {item.occurred_at} ·
                        查看证据
                      </button>
                      {resultDetails[item.inspection_result_id] && (
                        <p>
                          证据{" "}
                          {resultDetails[item.inspection_result_id].evidence
                            ?.length || 0}{" "}
                          项 · 媒体未接入时仅提供元数据。
                        </p>
                      )}
                    </div>
                  ))}
                  {taskAlerts.map((item) => (
                    <p id={`alert-${item.alert_id}`} key={item.alert_id}>
                      告警 {item.category} · {item.state} · {item.last_seen}
                    </p>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
      {focusedAlertId &&
        !alerts.some((item) => item.alert_id === focusedAlertId) && (
          <p className="text-xs text-statusYellow">
            指定告警不在当前近期数据中。
          </p>
        )}
    </DashboardCard>
  );
}

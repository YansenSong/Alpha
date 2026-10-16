import React, { useContext, useEffect, useState } from "react";
import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import { DashboardCard, EmptyState, SectionHeader } from "../shared/ui/Dashboard";
import { useRoleAccess } from "../shared/auth/roleAccess";

export default function InspectionPage() {
  const { robotId } = useContext(AuthContext);
  const writeAccess = useRoleAccess("Operator");
  const [results, setResults] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState("");
  const [taskId, setTaskId] = useState("");
  const [outcome, setOutcome] = useState("");
  const [taskQuery, setTaskQuery] = useState("");
  const [taskStatus, setTaskStatus] = useState("");
  const [taskSince, setTaskSince] = useState("");
  const [taskUntil, setTaskUntil] = useState("");
  const [tasks, setTasks] = useState([]);
  const [taskHistoryLimited, setTaskHistoryLimited] = useState(false);
  const [expandedTask, setExpandedTask] = useState("");
  const [focusedAlertId] = useState(() => new URLSearchParams(window.location.search).get("alert_id") || "");
  const [details, setDetails] = useState({});
  useEffect(() => {
    if (!robotId) return;
    let active = true;
    const base = `/api/v1/robots/${encodeURIComponent(robotId)}/inspection`;
    const params = new URLSearchParams({ limit: "50" });
    if (taskId.trim()) params.set("task_id", taskId.trim());
    if (outcome) params.set("outcome", outcome);
    const taskParams = new URLSearchParams({ limit: "20" });
    if (taskQuery.trim()) taskParams.set("q", taskQuery.trim());
    if (taskStatus) taskParams.set("status", taskStatus);
    if (taskSince) taskParams.set("since", new Date(taskSince).toISOString());
    if (taskUntil) taskParams.set("until", new Date(taskUntil).toISOString());
    const focusedAlertRequest = focusedAlertId
      ? apiFetch(`${base}/alerts/${encodeURIComponent(focusedAlertId)}`).then((response) => response.json()).catch(() => null)
      : Promise.resolve(null);
    Promise.all([
      apiFetch(`${base}/results?${params}`).then((response) => response.json()),
      apiFetch(`${base}/alerts`).then((response) => response.json()),
      focusedAlertRequest,
    ]).then(([r, a, focused]) => {
      if (active) {
        setResults(r.results || []);
        const nextAlerts = a.alerts || [];
        if (focused?.alert && !nextAlerts.some((item) => item.alert_id === focused.alert.alert_id)) {
          nextAlerts.unshift({ ...focused.alert, evidence: focused.evidence || [] });
        }
        setAlerts(nextAlerts);
        setError("");
      }
    }).catch((cause) => { if (active) setError(cause.message || "巡检数据加载失败"); });
    apiFetch(`${base}/tasks?${taskParams}`).then((response) => response.json()).then((payload) => {
      if (active) {
        setTasks(payload.tasks || []);
        setTaskHistoryLimited(Boolean(payload.history_window_limited));
      }
    }).catch((cause) => { if (active) setError((current) => current || cause.message || "任务历史暂不可用"); });
    return () => { active = false; };
  }, [robotId, taskId, outcome, taskQuery, taskStatus, taskSince, taskUntil, focusedAlertId]);
  useEffect(() => {
    if (!focusedAlertId) return;
    document.getElementById(`inspection-alert-${focusedAlertId}`)?.scrollIntoView?.({ block: "center" });
  }, [focusedAlertId, alerts]);
  const loadDetail = async (resultId) => {
    try {
      const response = await apiFetch(`/api/v1/robots/${encodeURIComponent(robotId)}/inspection/results/${encodeURIComponent(resultId)}`);
      const payload = await response.json();
      setDetails((current) => ({ ...current, [resultId]: payload }));
    } catch (cause) { setError(cause.message || "证据元数据加载失败"); }
  };
  const acknowledge = async (alert) => {
    try {
      await apiFetch(`/api/v1/robots/${encodeURIComponent(robotId)}/inspection/alerts/${encodeURIComponent(alert.alert_id)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json", "If-Match": String(alert.revision) },
        body: JSON.stringify({ state: "ACKNOWLEDGED" }),
      });
      setAlerts((current) => current.map((item) => item.alert_id === alert.alert_id
        ? { ...item, state: "ACKNOWLEDGED", revision: item.revision + 1 } : item));
    } catch (cause) { setError(cause.message || "告警处理失败"); }
  };
  return <div className="sectionHeight space-y-5 py-4 sm:py-6">
    <SectionHeader eyebrow="Inspection" title="巡检结果与业务告警" description="结果来自机器人事件同步；Fixture 与 Simulation 均不代表真实检测。" />
    {error && <p role="alert" className="text-statusRed">{error}</p>}
    <DashboardCard className="p-4"><h2 className="mb-3 font-semibold">业务告警</h2>
      {alerts.length === 0 ? <EmptyState title="暂无业务告警" description="设备故障请查看事件与健康页面。" /> :
        <ul>{alerts.map((item) => <li id={`inspection-alert-${item.alert_id}`} key={item.alert_id} className={`flex flex-wrap items-center justify-between gap-2 border-t border-borderSubtle py-2 ${focusedAlertId === item.alert_id ? "rounded bg-statusRed/10 px-2" : ""}`}>
          <div><span>{item.category} · {item.state} · {item.severity} · {item.occurrence_count} 次 · {item.last_seen}</span>
            {item.position ? <p className="text-xs text-themeTextGray">地图 {item.map_id} / {item.map_version_id} · map ({item.position.x}, {item.position.y})</p> : <p className="text-xs text-themeTextGray">无可用地图位置证据</p>}
            {focusedAlertId === item.alert_id && item.evidence && <p className="text-xs text-themeTextGray">关联证据 {item.evidence.length} 项；媒体服务未接入时仅显示元数据。</p>}
          </div>
          <div className="flex items-center gap-2">
            {item.map_id && item.map_version_id && <a href="/" className="rounded border border-borderSubtle px-2 py-1 text-xs">运行地图</a>}
            {item.state === "OPEN" && writeAccess.allowed && <button type="button" onClick={() => acknowledge(item)} className="rounded border border-borderSubtle px-2 py-1">确认告警</button>}
          </div>
        </li>)}</ul>}
    </DashboardCard>
    <DashboardCard className="space-y-3 p-4">
      <h2 className="font-semibold">巡检任务历史</h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">任务/名称<input value={taskQuery} onChange={(event) => setTaskQuery(event.target.value)} className="rounded border border-borderSubtle px-2 py-1" /></label>
        <label className="flex flex-col gap-1 text-sm">状态<select value={taskStatus} onChange={(event) => setTaskStatus(event.target.value)} className="rounded border border-borderSubtle px-2 py-1">
          <option value="">全部</option><option value="running">执行中</option><option value="paused">暂停</option><option value="succeeded">成功</option><option value="failed">失败</option><option value="cancelled">已取消</option>
        </select></label>
        <label className="flex flex-col gap-1 text-sm">开始时间<input type="datetime-local" value={taskSince} onChange={(event) => setTaskSince(event.target.value)} className="rounded border border-borderSubtle px-2 py-1" /></label>
        <label className="flex flex-col gap-1 text-sm">结束时间<input type="datetime-local" value={taskUntil} onChange={(event) => setTaskUntil(event.target.value)} className="rounded border border-borderSubtle px-2 py-1" /></label>
      </div>
      {taskHistoryLimited && <p className="text-xs text-statusYellow">任务列表复用 MissionManager 当前状态携带的最近 10 条历史；更早任务不在此列表中，完整归档查询仍待扩展。</p>}
      {tasks.length === 0 ? <EmptyState title="没有匹配的巡检任务" description="筛选范围只包含 MissionManager 当前状态及最近历史。" /> :
        <ul>{tasks.map((task) => <li key={task.task_id} className="border-t border-borderSubtle py-2">
          <button type="button" onClick={() => setExpandedTask((current) => current === task.task_id ? "" : task.task_id)} className="flex w-full flex-wrap justify-between gap-2 text-left text-sm">
            <span><strong>{task.mission_name || task.mission_id}</strong> · {task.task_id}</span>
            <span>{task.status} · {task.step_index}/{task.steps_total} · {task.started_at}</span>
          </button>
          {expandedTask === task.task_id && <div className="mt-2 space-y-1 text-xs text-themeTextGray">
            <p>原因：{task.reason || "—"} · 结束：{task.ended_at || "—"}</p>
            {(task.events || []).map((event, index) => <p key={`${task.task_id}-${index}`}>{event.timestamp || event.occurred_at || ""} · {event.status || event.type} · {event.reason || ""}</p>)}
          </div>}
        </li>)}</ul>}
    </DashboardCard>
    <DashboardCard className="flex flex-wrap items-end gap-3 p-4">
      <h2 className="w-full font-semibold">最近结果</h2>
      <label className="flex flex-col gap-1 text-sm">任务 ID<input value={taskId} onChange={(event) => setTaskId(event.target.value)} className="rounded border border-borderSubtle px-2 py-1" /></label>
      <label className="flex flex-col gap-1 text-sm">结论<select value={outcome} onChange={(event) => setOutcome(event.target.value)} className="rounded border border-borderSubtle px-2 py-1">
        <option value="">全部</option><option>NORMAL</option><option>ABNORMAL</option><option>INCONCLUSIVE</option><option>NOT_APPLICABLE</option>
      </select></label>
      {results.length === 0 ? <EmptyState title="暂无巡检结果" description="外部检测接口未连接时不会生成正常结果。" /> :
        <ul>{results.map((item) => <li key={item.inspection_result_id} className="border-t border-borderSubtle py-2">
          <button type="button" onClick={() => loadDetail(item.inspection_result_id)} className="text-left">
            <strong>{item.outcome}</strong> · {item.source.toUpperCase()} · {item.occurred_at} · 任务 {item.task_id || "未知"}
          </button>
          {details[item.inspection_result_id] && <div className="mt-2 text-xs text-themeTextGray">
            结果 {item.inspection_result_id} · 证据 {details[item.inspection_result_id].evidence?.length || 0} 项
            {details[item.inspection_result_id].evidence?.map((evidence) => <span key={evidence.evidence_id} className="ml-2">{evidence.evidence_id}: {evidence.available ? "可读取" : "媒体未接入"}</span>)}
          </div>}
        </li>)}</ul>}
    </DashboardCard>
  </div>;
}

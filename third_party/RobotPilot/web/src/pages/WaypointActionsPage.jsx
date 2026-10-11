import React, { useCallback, useContext, useEffect, useState } from "react";
import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import useRobotStatus from "../shared/hooks/useRobotStatus";
import { DashboardCard, EmptyState, SectionHeader } from "../shared/ui/Dashboard";
import { useRoleAccess } from "../shared/auth/roleAccess";
import InspectionTaskComposer from "../components/InspectionTaskComposer";

export default function WaypointActionsPage({ refreshKey = 0, routeWaypoints = [] }) {
  const { robotId } = useContext(AuthContext);
  const status = useRobotStatus();
  const writeAccess = useRoleAccess("Engineer");
  const runAccess = useRoleAccess("Operator");
  const mapId = status.snapshot?.current_map?.map_id || "";
  const [waypoints, setWaypoints] = useState([]);
  const [selected, setSelected] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [templateWaypointIds, setTemplateWaypointIds] = useState([]);
  const [templateResult, setTemplateResult] = useState(null);
  const [actions, setActions] = useState([]);
  const [revision, setRevision] = useState(0);
  const [provider, setProvider] = useState(null);
  const [taskResult, setTaskResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [pointQuery, setPointQuery] = useState("");
  const [pointDraft, setPointDraft] = useState(null);
  const [pointBusy, setPointBusy] = useState(false);
  const [pointNotice, setPointNotice] = useState("");
  const base = `/api/v1/robots/${encodeURIComponent(robotId || "")}`;
  const loadWaypoints = useCallback(async () => {
    if (!robotId || !mapId) return;
    try {
      const response = await apiFetch(`${base}/waypoints?map_id=${encodeURIComponent(mapId)}`);
      const values = (await response.json()).waypoints || [];
      setWaypoints(values);
      setSelected((current) => values.some((item) => item.waypoint_id === current) ? current : values[0]?.waypoint_id || "");
      setError("");
    } catch (cause) { setError(cause.message || "巡检点加载失败"); }
  }, [base, mapId, robotId]);
  useEffect(() => { loadWaypoints(); }, [loadWaypoints, refreshKey]);
  useEffect(() => {
    const current = waypoints.find((item) => item.waypoint_id === selected);
    setPointDraft(current ? {
      name: current.name, x: current.x, y: current.y, yaw: current.yaw,
      wait_time: current.wait_time, enabled: Boolean(current.enabled),
    } : null);
  }, [selected, waypoints]);
  const savePoint = async () => {
    const current = waypoints.find((item) => item.waypoint_id === selected);
    if (!current || !pointDraft || !writeAccess.allowed || pointBusy) return;
    const name = pointDraft.name.trim();
    const x = Number(pointDraft.x), y = Number(pointDraft.y);
    const yaw = Number(pointDraft.yaw), wait_time = Number(pointDraft.wait_time);
    if (!name || ![x, y, yaw, wait_time].every(Number.isFinite) || Math.abs(yaw) > Math.PI || wait_time < 0 || wait_time > 86400) {
      setError("请检查名称、坐标、朝向（-π 至 π）和停留秒数（0 至 86400）"); return;
    }
    setPointBusy(true);
    try {
      await apiFetch(`${base}/waypoints/${encodeURIComponent(selected)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json", "If-Match": String(current.revision) },
        body: JSON.stringify({ name, x, y, yaw, wait_time, enabled: pointDraft.enabled }),
      });
      await loadWaypoints(); setError(""); setPointNotice("巡检点已保存");
    } catch (cause) { setError(cause.message || "巡检点保存失败，请刷新后重试"); }
    finally { setPointBusy(false); }
  };
  const deletePoint = async () => {
    const current = waypoints.find((item) => item.waypoint_id === selected);
    if (!current || !writeAccess.allowed || pointBusy || !window.confirm(`删除巡检点“${current.name}”？`)) return;
    setPointBusy(true);
    try {
      await apiFetch(`${base}/waypoints/${encodeURIComponent(selected)}`, {
        method: "DELETE", headers: { "If-Match": String(current.revision) },
      });
      setTemplateWaypointIds((ids) => ids.filter((id) => id !== selected));
      await loadWaypoints(); setError(""); setPointNotice("巡检点已删除");
    } catch (cause) { setError(cause.message || "删除失败；此点可能已被任务引用"); }
    finally { setPointBusy(false); }
  };
  useEffect(() => {
    if (!status.snapshot) return;
    setProvider(status.snapshot.inspection_provider || {
      online: false, stale: true, actions: [], reason: "能力状态未由机器人上报。",
    });
  }, [status.snapshot]);
  useEffect(() => {
    if (!selected) { setActions([]); setRevision(0); return; }
    let current = true;
    apiFetch(`${base}/waypoints/${encodeURIComponent(selected)}/action-plan`).then(async (response) => {
      const value = await response.json();
      if (current) { setActions(value.actions || []); setRevision(value.revision || 0); }
    }).catch((cause) => {
      if (current && cause.status === 404) { setActions([]); setRevision(0); }
      else if (current) setError(cause.message || "动作草稿加载失败");
    });
    return () => { current = false; };
  }, [base, selected]);
  const actionPresets = [
    { label: "停留 1 秒", action: { kind: "wait", timeout_ms: 1000 } },
    { label: "拍照（占位）", action: { kind: "capture", timeout_ms: 15000 } },
    { label: "消防设施识别（占位）", action: { kind: "detect", timeout_ms: 15000, detector_types: ["fire_equipment"] } },
    { label: "烟火识别（占位）", action: { kind: "detect", timeout_ms: 15000, detector_types: ["fire_smoke"] } },
    { label: "语音播报（占位）", action: { kind: "broadcast", timeout_ms: 15000 } },
  ];
  const save = async () => {
    if (!selected) return;
    try {
      const response = await apiFetch(`${base}/waypoints/${encodeURIComponent(selected)}/action-plan`, {
        method: "PUT", headers: { "Content-Type": "application/json", "If-Match": String(revision) },
        body: JSON.stringify({ actions }),
      });
      const value = await response.json(); setRevision(value.revision); setError("");
    } catch (cause) { setError(cause.message || "动作草稿保存失败"); }
  };
  const runInspection = async () => {
    if (!selected || !provider?.online || !runAccess.allowed) return;
    setRunning(true);
    try {
      const response = await apiFetch(base + "/inspection/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": window.crypto.randomUUID() },
        body: JSON.stringify({ name: "巡检点：" + (waypoints.find((item) => item.waypoint_id === selected)?.name || selected),
          waypoint_ids: [selected] }),
      });
      setTaskResult(await response.json());
      setError("");
    } catch (cause) { setError(cause.message || "巡检任务下发失败"); }
    finally { setRunning(false); }
  };
  const saveInspectionTemplate = async () => {
    if (!templateName.trim() || !templateWaypointIds.length || !runAccess.allowed) return;
    setRunning(true);
    try {
      const response = await apiFetch(base + "/inspection/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": window.crypto.randomUUID() },
        body: JSON.stringify({ name: templateName.trim(), waypoint_ids: templateWaypointIds, compile_only: true }),
      });
      setTemplateResult(await response.json());
      setError("");
    } catch (cause) { setError(cause.message || "巡检模板编译失败"); }
    finally { setRunning(false); }
  };
  const waypoint = waypoints.find((item) => item.waypoint_id === selected);
  const providerActions = new Map((provider?.actions || []).map((item) => [item.kind, item]));
  const hasProviderBlocker = actions.some((action) => {
    if (action.kind === "wait") return false;
    const capability = providerActions.get(action.kind);
    if (!provider?.online || !capability?.supported) return true;
    return (action.detector_types || []).some((detector) => !(capability.detectors || []).includes(detector));
  });
  return <div className="sectionHeight space-y-5 py-4 sm:py-6">
    <SectionHeader eyebrow="Patrol setup" title="巡检点与任务" description="巡检点使用唯一 ID；动作计划绑定巡检点，任务模板保存巡检点的执行顺序。" />
    <DashboardCard className="space-y-4 p-4">
      <p className="text-xs text-themeTextGray">当前地图：{mapId || "未知"} · {status.stale ? "状态过期" : "状态新鲜"}</p>
      <p role="status" className="text-xs text-themeTextGray">
        Provider：{provider?.online && !provider.stale ? provider.provider_id + " · " + provider.source_mode + " · 在线" : "未连接、未知或能力/心跳已过期"}
        {provider?.reason ? " · " + provider.reason : ""}
      </p>
      <InspectionTaskComposer robotId={robotId} mapId={mapId} waypoints={waypoints} routeWaypoints={routeWaypoints} />
      {waypoints.length === 0 ? <EmptyState title="当前地图没有巡检点" description="在上方地图选择位置并保存为巡检点。" /> : <>
        <fieldset className="space-y-3 rounded border border-borderSubtle p-3">
          <legend className="px-1 text-sm font-semibold">巡检点管理（{waypoints.length}）</legend>
          <input aria-label="搜索巡检点" placeholder="按名称或 ID 搜索" value={pointQuery} onChange={(event) => setPointQuery(event.target.value)} className="w-full max-w-sm rounded border border-borderSubtle bg-bgCard px-2 py-1.5 text-sm" />
          <div className="max-h-48 overflow-y-auto rounded border border-borderSubtle">
            {waypoints.filter((item) => `${item.name} ${item.waypoint_id}`.toLowerCase().includes(pointQuery.trim().toLowerCase())).map((item) =>
              <button key={item.waypoint_id} type="button" onClick={() => { setSelected(item.waypoint_id); setPointNotice(""); }} className={`flex w-full items-center justify-between gap-2 border-b border-borderSubtle px-3 py-2 text-left text-xs ${selected === item.waypoint_id ? "bg-themeBlue/10 text-themeBlue" : "hover:bg-bgSurface"}`}>
                <span><strong>{item.name}</strong> · ({Number(item.x).toFixed(2)}, {Number(item.y).toFixed(2)})</span>
                <span>{item.enabled ? "启用" : "停用"}</span>
              </button>)}
          </div>
          {pointDraft && <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="flex flex-col gap-1 text-xs">名称<input maxLength={100} disabled={!writeAccess.allowed || pointBusy} value={pointDraft.name} onChange={(event) => setPointDraft((draft) => ({ ...draft, name: event.target.value }))} className="rounded border border-borderSubtle bg-bgCard px-2 py-1.5" /></label>
            {["x", "y", "yaw", "wait_time"].map((field) => <label key={field} className="flex flex-col gap-1 text-xs">{{ x: "X (m)", y: "Y (m)", yaw: "朝向 (rad)", wait_time: "停留 (秒)" }[field]}<input type="number" step={field === "wait_time" ? "1" : "0.01"} disabled={!writeAccess.allowed || pointBusy} value={pointDraft[field]} onChange={(event) => setPointDraft((draft) => ({ ...draft, [field]: event.target.value }))} className="rounded border border-borderSubtle bg-bgCard px-2 py-1.5" /></label>)}
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={!writeAccess.allowed || pointBusy} checked={pointDraft.enabled} onChange={(event) => setPointDraft((draft) => ({ ...draft, enabled: event.target.checked }))} />启用</label>
            <div className="flex items-end gap-2"><button type="button" disabled={!writeAccess.allowed || pointBusy} onClick={savePoint} className="rounded bg-themeBlue px-3 py-1.5 text-xs text-white disabled:opacity-50">保存巡检点</button><button type="button" disabled={!writeAccess.allowed || pointBusy} onClick={deletePoint} className="rounded border border-statusRed px-3 py-1.5 text-xs text-statusRed disabled:opacity-50">删除</button></div>
          </div>}
          {pointNotice && <p role="status" className="text-xs text-statusGreen">{pointNotice}</p>}
        </fieldset>
        <fieldset className="space-y-2 rounded border border-borderSubtle p-3">
          <legend className="px-1 text-sm font-semibold">仅巡检点模板（现有下发接口）</legend>
          <label className="flex max-w-lg flex-col gap-1 text-sm">模板名称<input value={templateName} maxLength={120} onChange={(event) => setTemplateName(event.target.value)} className="rounded border border-borderSubtle bg-bgCard px-2 py-1.5" placeholder="例：一层消防设施巡检" /></label>
          <p className="text-xs text-themeTextGray">勾选顺序即执行顺序。保存会编译当前点位、资产关系和动作计划快照，可在调度页设置周期；保存时 Provider 可离线，任务开始时机器人端重新校验。</p>
          <div className="grid gap-1 sm:grid-cols-2">{waypoints.map((item) => <label key={item.waypoint_id} className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={templateWaypointIds.includes(item.waypoint_id)} onChange={(event) => setTemplateWaypointIds((current) => event.target.checked ? [...current, item.waypoint_id] : current.filter((id) => id !== item.waypoint_id))} />
            {templateWaypointIds.includes(item.waypoint_id) ? `${templateWaypointIds.indexOf(item.waypoint_id) + 1}. ` : ""}{item.name} · {item.waypoint_id}
          </label>)}</div>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" disabled={!runAccess.allowed || running || !templateName.trim() || templateWaypointIds.length === 0} title={!runAccess.allowed ? runAccess.reason : undefined} onClick={saveInspectionTemplate} className="rounded border border-themeBlue px-3 py-1.5 text-xs disabled:opacity-50">{running ? "保存中…" : "编译并保存巡检模板"}</button>
            {templateResult && <span role="status" className="text-xs">已保存 Mission {templateResult.mission_id} · <a href="/scheduler" className="underline">前往周期调度</a></span>}
          </div>
        </fieldset>
        <label className="flex flex-col gap-1 text-sm">巡检点<select value={selected} onChange={(event) => setSelected(event.target.value)} className="max-w-lg rounded border border-borderSubtle bg-bgCard p-2">{waypoints.map((wp) => <option key={wp.waypoint_id} value={wp.waypoint_id}>{wp.name} · {wp.waypoint_id}</option>)}</select></label>
        {waypoint && <p className="text-xs text-themeTextGray">地图版本 {waypoint.map_version_id || "未知"} · 修订 {revision}</p>}
        <div className="flex flex-wrap gap-2">{actionPresets.map(({ label, action }) => <button key={label} type="button" disabled={!writeAccess.allowed} title={!writeAccess.allowed ? writeAccess.reason : undefined} onClick={() => setActions((current) => [...current, action])} className="rounded border border-borderSubtle px-3 py-1.5 text-xs disabled:opacity-50">添加 {label}</button>)}</div>
        {actions.length === 0 ? <EmptyState title="无动作步骤" description="可以先保存空计划，等待外部能力接入。" /> : <ol className="space-y-2">{actions.map((action, index) => <li key={`${index}-${action.kind}`} className="flex flex-wrap items-center gap-2 rounded border border-borderSubtle p-2 text-sm">
          <span className="w-24 font-semibold">{index + 1}. {action.kind}</span>
          {action.kind === "detect" && <input aria-label="检测类别" disabled={!writeAccess.allowed} value={(action.detector_types || []).join(",")} onChange={(event) => setActions((current) => current.map((item, i) => i === index ? { ...item, detector_types: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) } : item))} className="min-w-40 rounded border border-borderSubtle bg-bgCard px-2 py-1 disabled:opacity-50" />}
          <label className="text-xs">超时 ms <input type="number" min="100" max="120000" disabled={!writeAccess.allowed} value={action.timeout_ms} onChange={(event) => setActions((current) => current.map((item, i) => i === index ? { ...item, timeout_ms: Number(event.target.value) } : item))} className="w-24 rounded border border-borderSubtle bg-bgCard px-2 py-1 disabled:opacity-50" /></label>
          <button type="button" disabled={!writeAccess.allowed} onClick={() => setActions((current) => current.filter((_, i) => i !== index))} className="ml-auto text-statusRed disabled:opacity-50">移除</button>
        </li>)}</ol>}
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" disabled={!writeAccess.allowed} title={!writeAccess.allowed ? writeAccess.reason : undefined} onClick={save} className="rounded bg-themeBlue px-4 py-2 text-white disabled:opacity-50">保存动作计划</button>
          <button type="button" disabled={!runAccess.allowed || !provider?.online || provider.stale || hasProviderBlocker || !actions.length || running} title={!runAccess.allowed ? runAccess.reason : hasProviderBlocker ? "当前 Provider 能力不支持此动作或检测类别" : undefined} onClick={runInspection} className="rounded border border-themeBlue px-4 py-2 disabled:opacity-50">{running ? "下发中…" : "创建并下发此点巡检"}</button>
          <span className="text-xs text-themeTextGray">{hasProviderBlocker ? "动作或类别能力不匹配，当前不可下发。" : !provider?.online || provider.stale ? "等待实时 Provider 能力与心跳。" : "下发前服务端会重验地图、安全状态、版本和 Provider 能力。"}</span>
        </div>
        {taskResult && <p role="status" className="text-sm">任务 {taskResult.task_id || "等待机器人确认"} · {taskResult.status || "pending"} · Mission {taskResult.mission_id}</p>}
      </>}
    </DashboardCard>
    {error && <p role="alert" className="text-statusRed">{error}</p>}
  </div>;
}

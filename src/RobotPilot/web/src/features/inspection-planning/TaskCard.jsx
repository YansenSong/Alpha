import React, { useEffect, useState } from "react";
import { DashboardCard } from "../../shared/ui/Dashboard";
import { useRoleAccess } from "../../shared/auth/roleAccess";
import {
  compileInspectionMission,
  deleteInspectionMission,
  missionStops,
  startInspectionMission,
} from "../../shared/inspection/planningApi";

const newDraft = () => ({ id: "", name: "", stops: [] });
const button =
  "rounded border border-borderSubtle px-2.5 py-1.5 text-xs hover:border-themeBlue disabled:opacity-40";

export default function TaskCard({
  robotId,
  mapId,
  mapVersionId,
  stale,
  points,
  missions,
  refreshMissions,
  onInsertFromMap,
  insertedPoint,
  onFocusPoint,
  requestedMissionId,
}) {
  const access = useRoleAccess("Operator");
  const [draft, setDraft] = useState(newDraft);
  const [dirty, setDirty] = useState(false);
  const [selectedPoint, setSelectedPoint] = useState("");
  const [selectedStep, setSelectedStep] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const change = (next) => {
    setDraft(next);
    setDirty(true);
    setMessage("");
  };
  const canLeave = () =>
    !dirty || window.confirm("当前任务有未保存修改，确定放弃吗？");
  useEffect(() => {
    const beforeUnload = (event) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);
  useEffect(() => {
    if (!insertedPoint) return;
    setDraft((current) => {
      const next = [...current.stops];
      next.splice(insertedPoint.after + 1, 0, {
        waypoint_id: insertedPoint.id,
        execute_actions: false,
        uiId: crypto.randomUUID(),
      });
      return { ...current, stops: next };
    });
    setDirty(true);
  }, [insertedPoint]);
  useEffect(() => {
    const poses = draft.stops
      .map((stop) =>
        points.find((point) => point.waypoint_id === stop.waypoint_id),
      )
      .filter(Boolean)
      .map((point) => ({
        position: { x: point.x, y: point.y, z: 0 },
        orientation: { z: Math.sin(point.yaw / 2), w: Math.cos(point.yaw / 2) },
      }));
    window.NAV2D?.setQueuedWaypoints?.(poses);
    window.NAV2D?.drawRoutePlan?.(poses);
    return () => {
      window.NAV2D?.clearQueuedWaypoints?.();
      window.NAV2D?.clearPath?.();
    };
  }, [draft.stops, points]);

  const open = (mission) => {
    if (!canLeave()) return;
    setDraft({
      id: mission.id,
      name: mission.name,
      stops: missionStops(mission),
    });
    setDirty(false);
    setSelectedStep(-1);
    setError("");
    setMessage("");
  };
  useEffect(() => {
    if (!requestedMissionId) return;
    const mission = missions.find((item) => item.id === requestedMissionId);
    if (
      mission &&
      (!dirty || window.confirm("放弃未保存修改并打开历史任务定义？"))
    ) {
      setDraft({
        id: mission.id,
        name: mission.name,
        stops: missionStops(mission),
      });
      setDirty(false);
    }
  }, [requestedMissionId]);
  const append = () => {
    if (!selectedPoint) return;
    const point = points.find((item) => item.waypoint_id === selectedPoint);
    const next = [...draft.stops];
    next.splice(selectedStep < 0 ? next.length : selectedStep + 1, 0, {
      waypoint_id: selectedPoint,
      execute_actions: Boolean(point?.actions?.length),
      uiId: crypto.randomUUID(),
    });
    change({ ...draft, stops: next });
  };
  const updateStop = (index, update) =>
    change({
      ...draft,
      stops: draft.stops.map((stop, position) =>
        position === index ? { ...stop, ...update } : stop,
      ),
    });
  const move = (index, direction) => {
    const next = [...draft.stops],
      target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    change({ ...draft, stops: next });
    setSelectedStep(target);
  };
  const issues = draft.stops.flatMap((stop, index) => {
    const point = points.find((item) => item.waypoint_id === stop.waypoint_id);
    if (!point) return [`第 ${index + 1} 点已不存在`];
    if (!point.enabled) return [`第 ${index + 1} 点已停用`];
    if (point.map_id !== mapId || point.map_version_id !== mapVersionId)
      return [`第 ${index + 1} 点地图版本不匹配`];
    if (stop.execute_actions && !point.actions?.length)
      return [`第 ${index + 1} 点没有业务动作`];
    return [];
  });
  if (!draft.name.trim()) issues.push("请填写任务名称");
  if (!draft.stops.length) issues.push("请添加至少一个巡检点");
  if (!mapId || !mapVersionId || stale)
    issues.push("当前地图状态不可用或已过期");
  const save = async () => {
    if (issues.length || !access.allowed || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const mission = await compileInspectionMission(robotId, {
        name: draft.name.trim(),
        stops: draft.stops,
        missionId: draft.id || null,
      });
      await refreshMissions();
      setDraft({
        id: mission.id,
        name: mission.name,
        stops: missionStops(mission),
      });
      setDirty(false);
      setMessage("任务已在机器人端保存并回读确认。");
    } catch (cause) {
      setError(cause.message || "保存失败");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (
      !draft.id ||
      !access.allowed ||
      busy ||
      !window.confirm(`删除任务“${draft.name}”？`)
    )
      return;
    setBusy(true);
    setError("");
    try {
      await deleteInspectionMission(robotId, draft.id);
      await refreshMissions();
      setDraft(newDraft());
      setDirty(false);
      setMessage("任务已删除。");
    } catch (cause) {
      setError(cause.message || "删除失败");
    } finally {
      setBusy(false);
    }
  };
  const execute = async () => {
    if (
      !draft.id ||
      dirty ||
      issues.length ||
      stale ||
      !access.allowed ||
      busy ||
      !window.confirm(`执行任务“${draft.name}”？`)
    )
      return;
    setBusy(true);
    setError("");
    try {
      const result = await startInspectionMission(robotId, draft.id);
      setMessage(`执行指令已接收：${result.task_id || result.command_id}`);
    } catch (cause) {
      setError(cause.message || "执行失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DashboardCard
      className="min-w-0 space-y-4 p-4"
      data-testid="planning-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">巡检任务编排与管理</h2>
        <span className="text-xs text-themeTextGray">
          {dirty ? "有未保存修改" : draft.id ? "已保存" : "新任务"}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        <select
          aria-label="选择已保存任务"
          value={draft.id}
          onChange={(event) => {
            const mission = missions.find(
              (item) => item.id === event.target.value,
            );
            if (mission) open(mission);
          }}
          className="min-w-0 flex-1 rounded border border-borderSubtle bg-bgCard px-2 py-1.5 text-sm"
        >
          <option value="">选择已保存任务</option>
          {missions.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
        <button
          className={button}
          onClick={() => {
            if (canLeave()) {
              setDraft(newDraft());
              setDirty(false);
            }
          }}
        >
          新建
        </button>
        <button
          className={button}
          disabled={!draft.id}
          onClick={() => {
            change({ ...draft, id: "", name: `${draft.name} 副本` });
          }}
        >
          复制
        </button>
        <button
          className={button}
          disabled={!draft.id || busy}
          onClick={remove}
        >
          删除
        </button>
      </div>
      <label className="flex flex-col gap-1 text-xs">
        任务名称
        <input
          value={draft.name}
          maxLength={120}
          onChange={(event) => change({ ...draft, name: event.target.value })}
          className="rounded border border-borderSubtle bg-bgCard px-2 py-2 text-sm"
        />
      </label>
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label className="min-w-0 flex-1">
          从巡检点库添加
          <select
            value={selectedPoint}
            onChange={(event) => setSelectedPoint(event.target.value)}
            className="mt-1 w-full rounded border border-borderSubtle bg-bgCard p-2"
          >
            <option value="">选择巡检点</option>
            {points
              .filter((point) => point.point_type === "inspection")
              .map((point) => (
                <option key={point.waypoint_id} value={point.waypoint_id}>
                  {point.name} · {point.actions?.length ? "业务" : "仅途经"}
                </option>
              ))}
          </select>
        </label>
        <button className={button} disabled={!selectedPoint} onClick={append}>
          加入选中步骤之后
        </button>
      </div>
      <ol className="space-y-1">
        {draft.stops.map((stop, index) => {
          const point = points.find(
            (item) => item.waypoint_id === stop.waypoint_id,
          );
          return (
            <li
              key={stop.uiId || `${stop.waypoint_id}-${index}`}
              className={`rounded border p-2 text-xs ${
                selectedStep === index
                  ? "border-themeBlue"
                  : "border-borderSubtle"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="min-w-0 flex-1 text-left"
                  onClick={() => {
                    setSelectedStep(index);
                    onFocusPoint(point);
                  }}
                >
                  {String(index + 1).padStart(2, "0")}{" "}
                  {point?.name || "点位失效"} ·{" "}
                  {stop.execute_actions
                    ? (point?.actions || [])
                        .map((action) => action.kind)
                        .join("、") || "无动作"
                    : "仅途经"}
                </button>
                <button onClick={() => move(index, -1)} disabled={index === 0}>
                  ↑
                </button>
                <button
                  onClick={() => move(index, 1)}
                  disabled={index === draft.stops.length - 1}
                >
                  ↓
                </button>
                <button
                  onClick={() =>
                    change({
                      ...draft,
                      stops: draft.stops.filter(
                        (_, position) => position !== index,
                      ),
                    })
                  }
                >
                  ×
                </button>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <label>
                  <input
                    type="checkbox"
                    checked={stop.execute_actions}
                    onChange={(event) =>
                      updateStop(index, {
                        execute_actions: event.target.checked,
                      })
                    }
                  />{" "}
                  到点执行业务
                </label>
                <button
                  className="text-themeBlue"
                  onClick={() => {
                    setSelectedStep(index);
                    onInsertFromMap(index);
                  }}
                >
                  在此步后地图选点插入
                </button>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-themeTextGray">
        共 {draft.stops.length} 点，
        {draft.stops.filter((stop) => stop.execute_actions).length}{" "}
        个执行业务。执行使用任务保存时的点位与动作快照。
      </p>
      {issues.length > 0 && (
        <p role="status" className="text-xs text-statusYellow">
          {issues.join("；")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-statusRed">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="text-xs text-statusGreen">
          {message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          className="rounded bg-themeBlue px-4 py-2 text-sm text-white disabled:opacity-40"
          disabled={!access.allowed || busy || issues.length > 0}
          onClick={save}
        >
          保存任务
        </button>
        <button
          className={button}
          disabled={
            !access.allowed || busy || !draft.id || dirty || issues.length > 0
          }
          onClick={execute}
        >
          执行任务
        </button>
      </div>
    </DashboardCard>
  );
}

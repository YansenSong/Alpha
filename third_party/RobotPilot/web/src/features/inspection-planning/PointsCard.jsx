import React, { useEffect, useState } from "react";
import { DashboardCard } from "../../shared/ui/Dashboard";
import { useRoleAccess } from "../../shared/auth/roleAccess";
import {
  deleteInspectionPoint,
  saveInspectionPoint,
} from "../../shared/inspection/planningApi";

const emptyForm = () => ({
  name: "",
  x: "",
  y: "",
  yaw: 0,
  enabled: true,
  actions: [],
});
const choices = [
  { label: "等待 1 秒", value: { kind: "wait", timeout_ms: 1000 } },
  { label: "拍照", value: { kind: "capture", timeout_ms: 15000 } },
  {
    label: "消防识别",
    value: {
      kind: "detect",
      timeout_ms: 15000,
      detector_types: ["fire_equipment"],
    },
  },
  {
    label: "烟火识别",
    value: {
      kind: "detect",
      timeout_ms: 15000,
      detector_types: ["fire_smoke"],
    },
  },
  { label: "语音播报", value: { kind: "broadcast", timeout_ms: 15000 } },
];
const field =
  "min-w-0 w-full rounded border border-borderSubtle bg-bgCard px-2 py-1.5 text-sm";

export default function PointsCard({
  robotId,
  mapId,
  mapVersionId,
  stale,
  points,
  missions,
  refreshPoints,
  selectedPose,
  mapMode,
  insertAfter,
  onSelectMap,
  onCancelMap,
  onSaved,
  focusPoint,
}) {
  const access = useRoleAccess("Engineer");
  const [selectedId, setSelectedId] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selected = points.find((point) => point.waypoint_id === selectedId);
  useEffect(() => {
    if (insertAfter !== null) {
      setSelectedId("");
      setForm(emptyForm());
    }
  }, [insertAfter]);
  useEffect(() => {
    if (!focusPoint) return;
    setSelectedId(focusPoint.waypoint_id);
    setForm({
      name: focusPoint.name,
      x: focusPoint.x,
      y: focusPoint.y,
      yaw: focusPoint.yaw,
      enabled: focusPoint.enabled,
      actions: focusPoint.actions || [],
    });
  }, [focusPoint]);
  useEffect(() => {
    if (!selectedPose) return;
    const yaw = Math.atan2(
      2 *
        (selectedPose.qw * selectedPose.qz + selectedPose.qx * selectedPose.qy),
      1 - 2 * (selectedPose.qy ** 2 + selectedPose.qz ** 2),
    );
    setForm((current) => ({
      ...current,
      x: selectedPose.x,
      y: selectedPose.y,
      yaw,
    }));
  }, [selectedPose]);
  const open = (point) => {
    setSelectedId(point.waypoint_id);
    setForm({
      name: point.name,
      x: point.x,
      y: point.y,
      yaw: point.yaw,
      enabled: point.enabled,
      actions: point.actions || [],
    });
    setError("");
    setNotice("");
  };
  const create = () => {
    setSelectedId("");
    setForm(emptyForm());
    setError("");
    setNotice("");
  };
  const usage =
    selected &&
    missions.filter((mission) =>
      (mission.steps || []).some(
        (step) =>
          (step.waypoint_id || step.waypointId) === selected.waypoint_id,
      ),
    );
  const save = async () => {
    if (!access.allowed || busy || stale || !mapId) return;
    const x = Number(form.x),
      y = Number(form.y),
      yaw = Number(form.yaw);
    if (
      !form.name.trim() ||
      form.x === "" ||
      form.y === "" ||
      ![x, y, yaw].every(Number.isFinite) ||
      Math.abs(yaw) > Math.PI
    ) {
      setError("请填写名称，并在地图选位；坐标和朝向必须有效。");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const point = await saveInspectionPoint(
        robotId,
        {
          map_id: mapId,
          map_version_id: mapVersionId,
          name: form.name.trim(),
          x,
          y,
          yaw,
          wait_time: 0,
          enabled: form.enabled,
          point_type: selected?.point_type || "inspection",
          source: selected?.source || "operator",
        },
        form.actions,
        selected,
      );
      await refreshPoints();
      setSelectedId(point.waypoint_id);
      setNotice("巡检点与动作配置已保存。");
      onSaved(point);
    } catch (cause) {
      if (cause.pointSaved) {
        await refreshPoints();
        setSelectedId(cause.pointSaved.waypoint_id);
      }
      setError(
        cause.pointSaved
          ? `点位已保存，业务动作未保存：${cause.message}。可重新打开继续编辑。`
          : cause.message || "保存失败",
      );
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (
      !selected ||
      !access.allowed ||
      busy ||
      !window.confirm(`删除巡检点“${selected.name}”？`)
    )
      return;
    setBusy(true);
    setError("");
    try {
      await deleteInspectionPoint(robotId, selected);
      await refreshPoints();
      create();
      setNotice("巡检点已删除。");
    } catch (cause) {
      setError(cause.message || "删除失败；请检查任务引用。");
    } finally {
      setBusy(false);
    }
  };
  const visible = points.filter(
    (point) =>
      point.point_type === "inspection" &&
      `${point.name} ${point.waypoint_id}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "business"
          ? point.actions?.length
          : !point.actions?.length)),
  );
  return (
    <DashboardCard className="min-w-0 space-y-4 p-4" data-testid="points-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">巡检点创建与管理</h2>
        <button
          onClick={create}
          className="rounded border border-themeBlue px-3 py-1.5 text-xs"
        >
          新建巡检点
        </button>
      </div>
      <p className="text-xs text-themeTextGray">
        当前地图：{mapId || "未加载"} · 版本：{mapVersionId || "未知"}
        {stale ? " · 状态过期" : ""}
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          disabled={!access.allowed || stale}
          onClick={() => onSelectMap(selected ? "edit" : "create")}
          className="rounded border border-themeBlue px-3 py-2 text-xs disabled:opacity-40"
        >
          {mapMode ? "地图选点中…" : "在地图上选择位置"}
        </button>
        <button
          onClick={onCancelMap}
          disabled={!mapMode}
          className="rounded border border-borderSubtle px-3 py-2 text-xs disabled:opacity-40"
        >
          取消选点
        </button>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-xs">
          名称
          <input
            value={form.name}
            maxLength={100}
            onChange={(event) =>
              setForm((current) => ({ ...current, name: event.target.value }))
            }
            className={field}
          />
        </label>
        <label className="text-xs">
          朝向 rad
          <input
            type="number"
            step="0.01"
            value={form.yaw}
            onChange={(event) =>
              setForm((current) => ({ ...current, yaw: event.target.value }))
            }
            className={field}
          />
        </label>
        <label className="text-xs">
          X (m)
          <input
            type="number"
            step="0.01"
            value={form.x}
            onChange={(event) =>
              setForm((current) => ({ ...current, x: event.target.value }))
            }
            className={field}
          />
        </label>
        <label className="text-xs">
          Y (m)
          <input
            type="number"
            step="0.01"
            value={form.y}
            onChange={(event) =>
              setForm((current) => ({ ...current, y: event.target.value }))
            }
            className={field}
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              enabled: event.target.checked,
            }))
          }
        />
        启用巡检点
      </label>
      <div className="space-y-2 border-t border-borderSubtle pt-3">
        <p className="text-xs font-semibold">
          到点业务动作 · {form.actions.length ? "业务点" : "仅途经"}
        </p>
        <div className="flex flex-wrap gap-1">
          {choices.map((choice) => (
            <button
              key={choice.label}
              onClick={() =>
                setForm((current) => ({
                  ...current,
                  actions: [...current.actions, choice.value],
                }))
              }
              className="rounded border border-borderSubtle px-2 py-1 text-xs"
            >
              + {choice.label}
            </button>
          ))}
        </div>
        <ol className="space-y-1">
          {form.actions.map((action, index) => (
            <li
              key={`${action.kind}-${index}`}
              className="flex flex-wrap items-center gap-2 text-xs"
            >
              <span>
                {index + 1}. {action.kind}
                {action.detector_types?.length
                  ? ` · ${action.detector_types.join(",")}`
                  : ""}
              </span>
              <input
                aria-label={`动作 ${index + 1} 超时毫秒`}
                type="number"
                min="100"
                max="120000"
                value={action.timeout_ms}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    actions: current.actions.map((item, position) =>
                      position === index
                        ? { ...item, timeout_ms: Number(event.target.value) }
                        : item,
                    ),
                  }))
                }
                className="w-24 rounded border border-borderSubtle bg-bgCard px-1"
              />
              <button
                onClick={() =>
                  setForm((current) => ({
                    ...current,
                    actions: current.actions.filter(
                      (_, position) => position !== index,
                    ),
                  }))
                }
                className="text-statusRed"
              >
                移除
              </button>
            </li>
          ))}
        </ol>
        <p className="text-[11px] text-themeTextGray">
          无动作时为“仅途经”；业务配置可保存，实际执行受 Provider
          能力与安全状态限制。
        </p>
      </div>
      {usage?.length > 0 && (
        <p className="text-xs text-statusYellow">
          被 {usage.length} 个任务引用：
          {usage.map((item) => item.name).join("、")}
          。修改点位不会改变已保存任务快照；删除可能被拒绝。
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-statusRed">
          {error}{" "}
          <button onClick={refreshPoints} className="underline">
            重新加载
          </button>
        </p>
      )}
      {notice && (
        <p role="status" className="text-xs text-statusGreen">
          {notice}
        </p>
      )}
      <div className="flex gap-2">
        <button
          disabled={!access.allowed || busy || stale}
          onClick={save}
          className="rounded bg-themeBlue px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          {busy ? "保存中…" : "保存巡检点"}
        </button>
        <button
          disabled={!selected || !access.allowed || busy}
          onClick={remove}
          className="rounded border border-statusRed px-3 py-2 text-xs text-statusRed disabled:opacity-40"
        >
          删除
        </button>
      </div>
      <div className="space-y-2 border-t border-borderSubtle pt-3">
        <h3 className="text-sm font-semibold">
          已保存巡检点 ({visible.length})
        </h3>
        <div className="flex gap-2">
          <input
            placeholder="搜索名称或 ID"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className={field}
          />
          <select
            aria-label="巡检点类型筛选"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            className="rounded border border-borderSubtle bg-bgCard px-2 text-xs"
          >
            <option value="all">全部</option>
            <option value="business">业务点</option>
            <option value="transit">仅途经</option>
          </select>
        </div>
        <div className="max-h-64 overflow-y-auto">
          {visible.map((point) => (
            <button
              key={point.waypoint_id}
              onClick={() => open(point)}
              className={`flex w-full items-center justify-between gap-2 border-b border-borderSubtle px-1 py-2 text-left text-xs ${
                selectedId === point.waypoint_id ? "text-themeBlue" : ""
              }`}
            >
              <span className="truncate">
                {point.name} · {point.actions?.length ? "业务" : "仅途经"}
              </span>
              <span>{point.enabled ? "启用" : "停用"}</span>
            </button>
          ))}
        </div>
      </div>
    </DashboardCard>
  );
}

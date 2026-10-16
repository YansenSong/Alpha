import React, { useContext, useEffect, useMemo, useState } from "react";
import { AuthContext } from "../../app/App";
import { useRoleAccess } from "../../shared/auth/roleAccess";
import {
  listInspectionMissions,
  startInspectionMission,
} from "../../shared/inspection/planningApi";
import { DashboardCard } from "../../shared/ui/Dashboard";

export default function SavedInspectionMissionsCard({
  mapId,
  mapVersionId,
  stale,
  active,
  onPreview,
}) {
  const { robotId } = useContext(AuthContext);
  const access = useRoleAccess("Operator");
  const [missions, setMissions] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let current = true;
    if (!robotId) {
      setMissions([]);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    listInspectionMissions(robotId)
      .then((items) => {
        if (current) {
          setMissions(items);
          setError("");
        }
      })
      .catch((cause) => {
        if (current) setError(cause.message || "巡检任务加载失败");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [robotId, refreshKey]);

  const currentMissions = useMemo(
    () =>
      missions.filter(
        (mission) =>
          mission.map_id === mapId && mission.map_version_id === mapVersionId,
      ),
    [missions, mapId, mapVersionId],
  );
  useEffect(() => {
    if (
      selectedId &&
      !currentMissions.some((mission) => mission.id === selectedId)
    )
      setSelectedId("");
  }, [currentMissions, selectedId]);
  const selected = currentMissions.find((mission) => mission.id === selectedId);
  const waypoints = (selected?.steps || []).filter(
    (step) => step.type === "waypoint" && step.pose,
  );
  const canExecute =
    selected &&
    waypoints.length > 0 &&
    !stale &&
    !active &&
    !busy &&
    access.allowed;

  const execute = async () => {
    if (!canExecute || !window.confirm(`执行巡检任务“${selected.name}”？`))
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await startInspectionMission(robotId, selected.id);
      setNotice(`执行指令已接收：${result.task_id || result.command_id}`);
    } catch (cause) {
      setError(cause.message || "巡检任务启动失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DashboardCard className="flex min-w-0 flex-col gap-3 p-3 font-[RobotoMono] sm:col-span-2 sm:p-4 lg:col-span-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-wider text-themeTextGray">
          已保存巡检任务
        </p>
        <button
          type="button"
          onClick={() => setRefreshKey((key) => key + 1)}
          disabled={loading}
          className="text-xs text-themeBlue hover:underline disabled:opacity-50"
        >
          刷新
        </button>
      </div>
      <select
        aria-label="选择已保存巡检任务"
        value={selectedId}
        onChange={(event) => {
          setSelectedId(event.target.value);
          setNotice("");
        }}
        disabled={loading || !currentMissions.length}
        className="min-h-10 w-full min-w-0 rounded-lg border border-borderSubtle bg-bgCard px-3 text-sm text-textWhiteHover outline-none focus:border-themeBlue disabled:opacity-50"
      >
        <option value="">
          {loading ? "正在加载巡检任务…" : "选择已保存巡检任务"}
        </option>
        {currentMissions.map((mission) => (
          <option key={mission.id} value={mission.id}>
            {mission.name}
          </option>
        ))}
      </select>
      {!loading && !error && (!mapId || !mapVersionId) && (
        <p className="text-xs leading-5 text-statusYellow">
          当前地图版本不可用，无法读取或执行绑定地图的巡检任务。
        </p>
      )}
      {!loading &&
        !error &&
        mapId &&
        mapVersionId &&
        !currentMissions.length && (
          <p className="text-xs leading-5 text-themeTextGray">
            当前地图版本没有已保存的巡检任务。请到
            <a href="/route" className="mx-1 text-themeBlue underline">
              巡检任务规划
            </a>
            创建并保存。
          </p>
        )}
      {selected && (
        <p className="text-xs text-themeTextGray">
          {waypoints.length} 个巡检点 · 地图版本 {selected.map_version_id}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-statusRed">
          {error}
        </p>
      )}
      {notice && <p className="text-xs text-themeBlue">{notice}</p>}
      {stale && (
        <p className="text-xs text-statusYellow">
          机器人或地图状态已过期，暂不能执行。
        </p>
      )}
      {!access.allowed && (
        <p className="text-xs text-statusYellow">{access.reason}</p>
      )}
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => selected && onPreview(selected)}
          disabled={!selected || !waypoints.length}
          className="min-h-10 rounded-lg border border-borderSubtle px-3 text-xs disabled:opacity-50"
        >
          地图预览
        </button>
        <button
          type="button"
          onClick={execute}
          disabled={!canExecute}
          className="min-h-10 rounded-lg border border-themeBlue bg-themeBlue/10 px-3 text-xs font-semibold text-themeBlue hover:bg-themeBlue hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "启动中…" : active ? "任务执行中" : "执行任务"}
        </button>
      </div>
    </DashboardCard>
  );
}

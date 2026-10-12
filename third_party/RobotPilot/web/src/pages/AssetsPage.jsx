import React, { useCallback, useContext, useEffect, useState } from "react";
import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import {
  DashboardCard,
  EmptyState,
  SectionHeader,
} from "../shared/ui/Dashboard";
import useRobotStatus from "../shared/hooks/useRobotStatus";
import { useRoleAccess } from "../shared/auth/roleAccess";

export default function AssetsPage() {
  const { robotId } = useContext(AuthContext);
  const status = useRobotStatus();
  const writeAccess = useRoleAccess("Engineer");
  const mapId = status.snapshot?.current_map?.map_id || "";
  const [assets, setAssets] = useState([]);
  const [waypoints, setWaypoints] = useState([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("equipment");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/api/v1/robots/${encodeURIComponent(robotId || "")}`;
  const load = useCallback(async () => {
    if (!robotId) return;
    try {
      const [assetResponse, waypointResponse] = await Promise.all([
        apiFetch(`${base}/assets?map_id=${encodeURIComponent(mapId)}`),
        mapId
          ? apiFetch(`${base}/waypoints?map_id=${encodeURIComponent(mapId)}`)
          : Promise.resolve(null),
      ]);
      setAssets((await assetResponse.json()).assets || []);
      setWaypoints(
        waypointResponse ? (await waypointResponse.json()).waypoints || [] : [],
      );
      setError("");
    } catch (cause) {
      setError(cause.message || "资产数据加载失败");
    }
  }, [base, mapId, robotId]);
  useEffect(() => {
    load();
  }, [load]);
  const create = async (event) => {
    event.preventDefault();
    if (!mapId) {
      setError("机器人当前地图未知，无法创建地图资产。");
      return;
    }
    setBusy(true);
    try {
      await apiFetch(`${base}/assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_id: mapId,
          name,
          metadata: { kind, active: true },
        }),
      });
      setName("");
      await load();
    } catch (cause) {
      setError(cause.message || "资产创建失败");
    } finally {
      setBusy(false);
    }
  };
  const link = async (assetId, waypointId) => {
    try {
      await apiFetch(
        `${base}/assets/${encodeURIComponent(
          assetId,
        )}/waypoints/${encodeURIComponent(waypointId)}`,
        { method: "PUT" },
      );
      await load();
    } catch (cause) {
      setError(cause.message || "关联失败");
    }
  };
  const unlink = async (assetId, waypointId) => {
    try {
      await apiFetch(
        `${base}/assets/${encodeURIComponent(
          assetId,
        )}/waypoints/${encodeURIComponent(waypointId)}`,
        { method: "DELETE" },
      );
      await load();
    } catch (cause) {
      setError(cause.message || "解除关联失败");
    }
  };
  const setActive = async (asset, active) => {
    try {
      await apiFetch(`${base}/assets/${encodeURIComponent(asset.asset_id)}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "If-Match": String(asset.revision),
        },
        body: JSON.stringify({
          name: asset.name,
          metadata: asset.metadata,
          active,
        }),
      });
      await load();
    } catch (cause) {
      setError(cause.message || "资产更新失败");
    }
  };
  return (
    <div className="sectionHeight space-y-5 py-4 sm:py-6">
      <SectionHeader
        eyebrow="Inventory"
        title="巡检资产"
        description="管理当前地图的巡检对象，并关联巡检点。"
      />
      {error && (
        <p role="alert" className="workspace-alert">
          {error}
        </p>
      )}

      <DashboardCard className="workspace-card">
        <div className="workspace-card__heading">
          <h2 className="workspace-card__title">新增资产</h2>
          <p className="workspace-card__hint">
            当前地图：{mapId || "未知"}
            {status.stale ? " · 状态过期" : ""}
          </p>
        </div>
        <form onSubmit={create} className="workspace-fields">
          <label className="workspace-field">
            资产名称
            <input
              required
              maxLength={100}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：配电柜 A"
            />
          </label>
          <label className="workspace-field">
            类型
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              <option value="equipment">设备</option>
              <option value="fire_safety">消防设施</option>
              <option value="utility">管线/仪表</option>
              <option value="other">其他</option>
            </select>
          </label>
          <button
            disabled={busy || !mapId || !writeAccess.allowed}
            title={!writeAccess.allowed ? writeAccess.reason : undefined}
            className="workspace-action workspace-action--primary"
          >
            {busy ? "创建中…" : "创建资产"}
          </button>
        </form>
      </DashboardCard>

      <DashboardCard className="workspace-card">
        <div className="workspace-card__heading">
          <h2 className="workspace-card__title">资产清单</h2>
          <span className="workspace-card__hint">共 {assets.length} 项</span>
        </div>
        {assets.length === 0 ? (
          <EmptyState
            title="当前地图暂无资产"
            description="连接当前地图后，可以在上方创建资产。"
          />
        ) : (
          <ul className="workspace-list">
            {assets.map((asset) => (
              <li
                key={asset.asset_id}
                className="workspace-list__item flex flex-wrap items-start justify-between gap-4"
              >
                <div className="min-w-0 flex-1">
                  <strong className="text-sm">{asset.name}</strong>
                  <p className="workspace-meta mt-1">
                    {asset.metadata?.kind || "未分类"} · 地图版本{" "}
                    {asset.map_version_id || "未知"} · 修订 {asset.revision} ·{" "}
                    {asset.metadata?.active === false ? "停用" : "启用"}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {(asset.waypoint_ids || []).map((waypointId) => {
                      const waypoint = waypoints.find(
                        (item) => item.waypoint_id === waypointId,
                      );
                      return (
                        <span
                          key={waypointId}
                          className="inline-flex min-h-11 items-center gap-1 rounded-lg border border-borderSubtle bg-bgSurface px-2 text-xs"
                        >
                          {waypoint?.name || waypointId}
                          <button
                            type="button"
                            disabled={!writeAccess.allowed}
                            aria-label={`解除 ${asset.name} 与 ${
                              waypoint?.name || waypointId
                            } 的关联`}
                            onClick={() => unlink(asset.asset_id, waypointId)}
                            className="min-h-11 px-2 text-statusRed disabled:opacity-50"
                          >
                            ×
                          </button>
                        </span>
                      );
                    })}
                    <select
                      aria-label={`关联 ${asset.name} 到巡检点`}
                      value=""
                      disabled={!writeAccess.allowed}
                      onChange={(event) =>
                        event.target.value &&
                        link(asset.asset_id, event.target.value)
                      }
                      className="min-h-11 rounded-lg border border-borderSubtle bg-bgSurface px-3 text-xs disabled:opacity-50"
                    >
                      <option value="">关联巡检点…</option>
                      {waypoints
                        .filter(
                          (wp) =>
                            !(asset.waypoint_ids || []).includes(
                              wp.waypoint_id,
                            ),
                        )
                        .map((wp) => (
                          <option key={wp.waypoint_id} value={wp.waypoint_id}>
                            {wp.name}
                          </option>
                        ))}
                    </select>
                  </div>
                </div>
                <button
                  type="button"
                  disabled={!writeAccess.allowed}
                  title={!writeAccess.allowed ? writeAccess.reason : undefined}
                  onClick={() =>
                    setActive(asset, asset.metadata?.active === false)
                  }
                  className="workspace-action"
                >
                  {asset.metadata?.active === false ? "启用" : "停用"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </DashboardCard>
    </div>
  );
}

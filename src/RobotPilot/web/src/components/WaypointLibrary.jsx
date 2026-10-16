import React, { useEffect, useRef, useState } from "react";
import { toast } from "react-toastify";

import { useRos } from "../app/App";
import { AppConfig } from "../shared/constants";
import { useT } from "../shared/i18n/i18n";
import { useRoleAccess } from "../shared/auth/roleAccess";

/**
 * Named, persisted goal poses ("Dock", "Loading bay") the operator can save
 * once and send to with one click — distinct from MapPage's waypoint queue,
 * which is an ephemeral, unnamed sequence built by clicking the map and
 * cleared after it runs. The list itself lives in the parent (via
 * useSavedWaypoints) so the map's saved-waypoint pins and context menu can
 * share and mutate the exact same data; this component is presentational.
 */
const WaypointLibrary = ({
  waypoints,
  onAdd,
  onGo,
  onRemove,
  onUpdate,
  mapId,
  loading,
  error,
  observedAt,
  stale = false,
  legacyWaypoints,
  onImportLegacy,
  inspectionOnly = false,
}) => {
  const { t } = useT();
  const ros = useRos();
  const waypointAccess = useRoleAccess("Engineer");
  const [name, setName] = useState("");
  const [pointType, setPointType] = useState("inspection");
  const [hasPose, setHasPose] = useState(false);

  const currentPoseRef = useRef(null);

  useEffect(() => {
    if (!ros || !window.ROSLIB) return;

    const localizationTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.LOCALIZATION_POSE_TOPIC,
      messageType: AppConfig.LOCALIZATION_POSE_TYPE,
    });
    localizationTopic.subscribe((msg) => {
      const pos = msg?.pose?.pose?.position;
      const ori = msg?.pose?.pose?.orientation;
      if (!pos || !ori) return;
      // Nested {position, orientation} shape — matches what the map's
      // right-click "Save waypoint here" passes, so onAdd (saveWaypointAt
      // in MapPage.jsx) has one consistent input shape regardless of
      // whether the pose came from here or a map click.
      currentPoseRef.current = {
        position: { x: pos.x, y: pos.y, z: 0 },
        orientation: { x: 0, y: 0, z: ori.z, w: ori.w },
      };
      setHasPose(true);
    });

    return () => localizationTopic.unsubscribe();
  }, [ros]);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      toast.warn(t("Enter a name for this waypoint"));
      return;
    }
    if (!currentPoseRef.current) {
      toast.warn(t("No localized position yet — waiting for localization"));
      return;
    }
    try {
      const saved = await onAdd(
        trimmed,
        currentPoseRef.current,
        inspectionOnly ? "inspection" : pointType,
      );
      if (saved === false) return;
      setName("");
      setPointType("inspection");
    } catch (saveError) {
      toast.error(saveError.message || t("Unable to save waypoint"));
    }
  };

  const handleTypeChange = async (waypoint, nextType) => {
    try {
      await onUpdate?.(waypoint.id, { point_type: nextType });
    } catch (updateError) {
      toast.error(updateError.message || t("Unable to update waypoint type"));
    }
  };

  const handleRemove = async (waypoint) => {
    try {
      await onRemove(waypoint.id);
    } catch (removeError) {
      toast.error(removeError.message || t("Unable to delete waypoint"));
    }
  };

  const handleImport = async () => {
    const preview = legacyWaypoints
      .slice(0, 5)
      .map(
        (item) =>
          `${item.name || "(unnamed)"} (${Number(item.x).toFixed(2)}, ${Number(
            item.y,
          ).toFixed(2)})`,
      )
      .join(", ");
    if (
      !window.confirm(
        `${t("Import legacy waypoints to the current 2D map?")} (${
          legacyWaypoints.length
        }: ${preview}${legacyWaypoints.length > 5 ? ", …" : ""})`,
      )
    )
      return;
    try {
      const result = await onImportLegacy();
      toast.success(
        `${t("Imported")} ${result.imported}; ${t("skipped")} ${
          result.skipped
        }. ${t("A local backup was kept.")}`,
      );
    } catch (importError) {
      toast.error(importError.message || t("Waypoint import did not finish"));
    }
  };

  const visibleWaypoints = inspectionOnly
    ? waypoints.filter((waypoint) => waypoint.point_type === "inspection")
    : waypoints;

  return (
    <div className="dashboard-card h-full p-3 font-[RobotoMono]">
      <p className="mb-2 text-xs uppercase tracking-wider text-themeTextGray">
        {inspectionOnly ? "已保存巡检点" : t("Saved Waypoints")}
      </p>

      <div className="mb-2 flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSave()}
          placeholder={t(
            hasPose ? "e.g. Dock, Loading bay" : "Waiting for pose…",
          )}
          disabled={!hasPose || !mapId || !waypointAccess.allowed}
          className="min-w-0 flex-1 rounded-lg border border-borderSubtle bg-bgSurface px-3 py-1.5 text-xs text-textWhiteHover placeholder:text-themeTextGray disabled:opacity-50"
        />
        <button
          onClick={handleSave}
          disabled={!hasPose || !mapId || !waypointAccess.allowed}
          className="shrink-0 rounded-lg border border-themeBlue px-3 py-1.5 text-xs font-semibold text-themeBlue transition-colors hover:bg-themeBlue hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("Save here")}
        </button>
      </div>
      {!inspectionOnly && (
        <div className="mb-2 flex items-center gap-2 text-[10px] text-themeTextGray">
          <label htmlFor="new-waypoint-type">点位类型</label>
          <select
            id="new-waypoint-type"
            value={pointType}
            onChange={(event) => setPointType(event.target.value)}
            disabled={!waypointAccess.allowed}
            className="rounded border border-borderSubtle bg-bgSurface px-2 py-1"
          >
            <option value="inspection">巡检点</option>
            <option value="charge">充电点（仅已配置点位）</option>
            <option value="shelter">避雨点（仅已配置点位）</option>
          </select>
        </div>
      )}

      <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] text-themeTextGray">
        <span>
          {mapId
            ? `${t("2D map")}: ${mapId.slice(0, 12)}`
            : t("Waiting for current map identity…")}
        </span>
        {loading && <span>{t("Loading robot waypoints…")}</span>}
        {stale && observedAt && (
          <span className="text-statusYellow">
            {t("Cached snapshot")}: {new Date(observedAt).toLocaleString()}
          </span>
        )}
        {!waypointAccess.allowed && <span>{t(waypointAccess.reason)}</span>}
      </div>
      {error && (
        <p className="mb-2 text-xs text-statusRed">
          {t("Robot waypoint API unavailable")}: {error}
        </p>
      )}

      {legacyWaypoints.length > 0 && mapId && (
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded border border-borderSubtle p-2 text-xs">
          <span>
            {t("Legacy browser points available")}: {legacyWaypoints.length}
          </span>
          <button
            onClick={handleImport}
            disabled={!waypointAccess.allowed || loading}
            className="rounded border border-themeBlue px-2 py-1 text-themeBlue disabled:opacity-40"
          >
            {t("Preview and import")}
          </button>
        </div>
      )}

      {visibleWaypoints.length === 0 ? (
        <p className="text-xs text-themeTextGray opacity-70">
          {inspectionOnly
            ? "当前地图版本还没有已保存巡检点。可在地图上选点后保存，再到巡检任务规划配置业务动作。"
            : t(
                "No saved waypoints yet — drive somewhere and save it, or right-click the map.",
              )}
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {visibleWaypoints.map((wp) => (
            <div
              key={wp.id}
              className="flex items-center gap-1.5 rounded-lg border border-borderSubtle bg-bgSurface px-2 py-1 text-xs"
            >
              <button
                onClick={() => onGo?.(wp)}
                disabled={!onGo || stale}
                className="text-themeBlue hover:underline disabled:text-themeTextGray"
                title={
                  stale
                    ? "Robot waypoint snapshot is stale; reconnect before navigation."
                    : `(${wp.x.toFixed(2)}, ${wp.y.toFixed(2)})`
                }
              >
                ▸ {wp.name}
              </button>
              <select
                aria-label={`${wp.name} 点位类型`}
                value={wp.point_type || "inspection"}
                onChange={(event) => handleTypeChange(wp, event.target.value)}
                disabled={!waypointAccess.allowed || stale}
                className="max-w-32 rounded border border-borderSubtle bg-bgCard px-1 py-0.5 text-[10px] text-themeTextGray disabled:opacity-40"
              >
                <option value="inspection">巡检点</option>
                <option value="charge">充电点 · 已配置点位</option>
                <option value="shelter">避雨点 · 已配置点位</option>
              </select>
              <span className="text-[10px] text-themeTextGray">
                {wp.source === "browser_import"
                  ? "浏览器导入"
                  : wp.source === "system"
                  ? "系统配置"
                  : "操作员配置"}
                {wp.valid_from &&
                  ` · 生效 ${new Date(wp.valid_from).toLocaleString()}`}
                {wp.valid_until
                  ? ` · 有效至 ${new Date(wp.valid_until).toLocaleString()}`
                  : !wp.valid_from && " · 长期有效"}
              </span>
              <button
                onClick={() => handleRemove(wp)}
                disabled={!waypointAccess.allowed}
                className="text-themeTextGray hover:text-statusRed"
                aria-label={`Delete ${wp.name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default WaypointLibrary;

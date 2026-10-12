import React, {
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { AuthContext } from "../app/App";
import useRobotStatus from "../shared/hooks/useRobotStatus";
import {
  listInspectionMissions,
  listInspectionPoints,
} from "../shared/inspection/planningApi";
import { SectionHeader } from "../shared/ui/Dashboard";
import Map from "../components/Map";
import MapLayers from "../components/MapLayers";
import TaskCard from "../features/inspection-planning/TaskCard";
import PointsCard from "../features/inspection-planning/PointsCard";
import HistoryCard from "../features/inspection-planning/HistoryCard";

export default function RoutePage() {
  const { robotId } = useContext(AuthContext);
  const status = useRobotStatus();
  const mapId = status.snapshot?.current_map?.map_id || "";
  const mapVersionId = status.snapshot?.current_map?.map_version_id || "";
  const stale = status.stale || status.snapshot?.current_map?.stale !== false;
  const [points, setPoints] = useState([]);
  const [missions, setMissions] = useState([]);
  const [dataError, setDataError] = useState("");
  const [mapMode, setMapMode] = useState("");
  const [selectedPose, setSelectedPose] = useState(null);
  const [insertAfter, setInsertAfter] = useState(null);
  const [insertedPoint, setInsertedPoint] = useState(null);
  const [focusPoint, setFocusPoint] = useState(null);
  const [requestedMissionId, setRequestedMissionId] = useState("");
  const requestSequence = useRef(0);
  const mapRef = useRef(null);
  const pointsRef = useRef(null);

  const refreshPoints = useCallback(async () => {
    if (!robotId || !mapId) {
      setPoints([]);
      return;
    }
    const sequence = ++requestSequence.current;
    try {
      const values = await listInspectionPoints(robotId, mapId);
      if (sequence === requestSequence.current) {
        setPoints(values);
        setDataError("");
      }
    } catch (cause) {
      if (sequence === requestSequence.current)
        setDataError(cause.message || "巡检点加载失败");
    }
  }, [robotId, mapId]);
  const refreshMissions = useCallback(async () => {
    if (!robotId) {
      setMissions([]);
      return;
    }
    try {
      setMissions(await listInspectionMissions(robotId));
    } catch (cause) {
      setDataError(cause.message || "任务列表加载失败");
    }
  }, [robotId]);
  useEffect(() => {
    refreshPoints();
    refreshMissions();
  }, [refreshPoints, refreshMissions]);
  useEffect(() => {
    setMapMode("");
    setSelectedPose(null);
    setInsertAfter(null);
    setInsertedPoint(null);
    setFocusPoint(null);
  }, [robotId, mapId, mapVersionId]);
  useEffect(() => {
    if (window.location.hash === "#inspection-records")
      document.getElementById("inspection-records")?.scrollIntoView?.();
  }, []);
  useEffect(() => {
    const nav = window.NAV2D;
    if (!nav) return;
    nav.arePointsSettable = Boolean(mapMode);
    const callback = (pose) => {
      if (!pose?.position || !pose?.orientation) return;
      setSelectedPose({
        x: Number(pose.position.x),
        y: Number(pose.position.y),
        qx: Number(pose.orientation.x) || 0,
        qy: Number(pose.orientation.y) || 0,
        qz: Number(pose.orientation.z) || 0,
        qw: Number(pose.orientation.w ?? 1),
      });
      setMapMode("");
      nav.clearGoalPose?.();
      pointsRef.current?.scrollIntoView?.({
        behavior: "smooth",
        block: "start",
      });
    };
    nav._poseCallback = mapMode ? callback : null;
    return () => {
      if (nav._poseCallback === callback) nav._poseCallback = null;
      nav.arePointsSettable = false;
    };
  }, [mapMode]);
  useEffect(() => {
    const visible = points
      .filter((point) => point.map_version_id === mapVersionId)
      .map((point) => ({
        id: point.waypoint_id,
        name: point.name,
        x: point.x,
        y: point.y,
        z: Math.sin(point.yaw / 2),
        w: Math.cos(point.yaw / 2),
      }));
    window.NAV2D?.setSavedWaypoints?.(visible);
    return () => window.NAV2D?.setSavedWaypoints?.([]);
  }, [points, mapVersionId]);
  const beginMapSelection = (mode) => {
    setSelectedPose(null);
    setMapMode(mode);
    mapRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  };
  const onPointSaved = (point) => {
    setSelectedPose(null);
    if (insertAfter !== null) {
      setInsertedPoint({
        id: point.waypoint_id,
        after: insertAfter,
        nonce: crypto.randomUUID(),
      });
      setInsertAfter(null);
    }
  };
  const onOpenMission = (id) => {
    setRequestedMissionId(`${id}:${Date.now()}`);
    mapRef.current?.scrollIntoView?.({ behavior: "smooth" });
  };
  const requestedId = requestedMissionId
    ? requestedMissionId.slice(0, requestedMissionId.lastIndexOf(":"))
    : "";
  return (
    <div className="sectionHeight space-y-4 py-4 sm:py-6">
      <SectionHeader
        eyebrow="Inspection planning"
        title="巡检任务规划"
        description="创建巡检点 → 编排任务 → 查看执行结果"
      />
      <p className="text-xs text-themeTextGray">
        机器人 {robotId || "未选择"} · 地图 {mapId || "未加载"} · 版本{" "}
        {mapVersionId || "未知"}
        {stale ? " · 状态过期" : ""}
      </p>
      {dataError && (
        <p
          role="alert"
          className="rounded border border-statusRed/40 p-2 text-xs text-statusRed"
        >
          {dataError}{" "}
          <button
            onClick={() => {
              refreshPoints();
              refreshMissions();
            }}
            className="underline"
          >
            重试
          </button>
        </p>
      )}
      <section ref={mapRef} className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-themeText text-base font-semibold">
            共享地图 · 路线预览
          </h2>
          {mapMode && (
            <span className="text-xs text-themeBlue">请在地图上选择位置</span>
          )}
        </div>
        <MapLayers />
        <div className="h-[340px] min-w-0 sm:h-[460px] lg:h-[560px]">
          <Map />
        </div>
      </section>
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <div ref={pointsRef} className="min-w-0">
          <PointsCard
            robotId={robotId}
            mapId={mapId}
            mapVersionId={mapVersionId}
            stale={stale}
            points={points}
            missions={missions}
            refreshPoints={refreshPoints}
            selectedPose={selectedPose}
            mapMode={mapMode}
            insertAfter={insertAfter}
            onSelectMap={beginMapSelection}
            onCancelMap={() => setMapMode("")}
            onSaved={onPointSaved}
            focusPoint={focusPoint}
          />
        </div>
        <div className="min-w-0">
          <TaskCard
            robotId={robotId}
            mapId={mapId}
            mapVersionId={mapVersionId}
            stale={stale}
            points={points}
            missions={missions}
            refreshMissions={refreshMissions}
            insertedPoint={insertedPoint}
            onFocusPoint={setFocusPoint}
            requestedMissionId={requestedId}
            onInsertFromMap={(index) => {
              setInsertAfter(index);
              beginMapSelection("insert");
            }}
          />
        </div>
      </div>
      <section id="inspection-records">
        <HistoryCard onOpenMission={onOpenMission} />
      </section>
    </div>
  );
}

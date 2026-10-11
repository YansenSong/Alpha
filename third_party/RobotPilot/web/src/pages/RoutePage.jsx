import React, { useEffect, useState } from "react";
import { ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import Map from "../components/Map";
import MapLayers from "../components/MapLayers";
import InspectionPointCreate from "../components/InspectionPointCreate";
import InspectionPage from "./InspectionPage";
import WaypointActionsPage from "./WaypointActionsPage";
import { DashboardCard, SectionHeader } from "../shared/ui/Dashboard";
import { useRoleAccess } from "../shared/auth/roleAccess";

export default function RoutePage() {
  const access = useRoleAccess("Engineer");
  const [mode, setMode] = useState("");
  const [selectedPose, setSelectedPose] = useState(null);
  const [transitPoints, setTransitPoints] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const nav = window.NAV2D;
    if (!nav) return;
    nav.arePointsSettable = Boolean(mode);
    nav._poseCallback = mode ? (pose) => {
      const position = pose?.position;
      const orientation = pose?.orientation;
      if (!position || !orientation) return;
      const point = { x: Number(position.x), y: Number(position.y),
        qx: Number(orientation.x) || 0, qy: Number(orientation.y) || 0,
        qz: Number(orientation.z) || 0, qw: Number(orientation.w ?? 1) };
      if (mode === "inspection") {
        setSelectedPose(point);
        setMode("");
      } else {
        setTransitPoints((current) => [...current, point]);
        nav.clearGoalPose?.();
      }
    } : null;
    return () => {
      nav._poseCallback = null;
      nav.arePointsSettable = false;
    };
  }, [mode]);

  return <div className="sectionHeight space-y-5 py-4 sm:py-6">
    <ToastContainer position="bottom-right" theme="dark" />
    <SectionHeader eyebrow="Inspection planning" title="巡检点与任务编排" description="在地图上创建业务巡检点；任务编排可在巡检点之间插入只控制路线的航点。" />
    <MapLayers />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <section className="h-[440px] min-w-0 sm:h-[560px]"><Map /></section>
      <DashboardCard className="h-fit space-y-4 p-4">
        <h2 className="font-semibold">地图选点</h2>
        <p className="text-xs text-themeTextGray">选择模式后，在地图上按住并拖动以设置位置和朝向。</p>
        <button type="button" disabled={!access.allowed} onClick={() => setMode((current) => current === "inspection" ? "" : "inspection")} className={`w-full rounded border px-3 py-2 text-sm disabled:opacity-50 ${mode === "inspection" ? "border-themeBlue bg-themeBlue/20" : "border-borderSubtle"}`}>{mode === "inspection" ? "正在选择巡检点位置…" : "选择巡检点位置"}</button>
        <button type="button" disabled={!access.allowed} onClick={() => setMode((current) => current === "transit" ? "" : "transit")} className={`w-full rounded border px-3 py-2 text-sm disabled:opacity-50 ${mode === "transit" ? "border-themeBlue bg-themeBlue/20" : "border-borderSubtle"}`}>{mode === "transit" ? "连续添加航点中…" : "添加过路航点"}</button>
        {selectedPose && <p className="text-xs">待保存巡检点位置：({selectedPose.x.toFixed(2)}, {selectedPose.y.toFixed(2)})。在下方填写名称并保存。</p>}
        {transitPoints.length > 0 && <div className="space-y-1 text-xs"><p>本次选择的航点（{transitPoints.length}）</p>{transitPoints.map((point, index) => <div key={index} className="flex justify-between gap-2"><span>{index + 1}. ({point.x.toFixed(2)}, {point.y.toFixed(2)})</span><button type="button" onClick={() => setTransitPoints((current) => current.filter((_, position) => position !== index))} className="text-statusRed">移除</button></div>)}</div>}
        <InspectionPointCreate selectedPose={selectedPose} onCreated={() => { setSelectedPose(null); setRefreshKey((value) => value + 1); }} />
      </DashboardCard>
    </div>
    <section id="inspection-setup"><WaypointActionsPage refreshKey={refreshKey} routeWaypoints={transitPoints} /></section>
    <section id="inspection-records"><InspectionPage /></section>
  </div>;
}

import React, { useEffect, useState } from "react";
import { DashboardCard } from "../shared/ui/Dashboard";

export default function InspectionTaskComposer({ robotId, mapId, waypoints, routeWaypoints }) {
  const storageKey = `robotpilot:inspection-composition:${robotId}:${mapId}`;
  const [name, setName] = useState("");
  const [steps, setSteps] = useState([]);
  const [selectedPoint, setSelectedPoint] = useState("");
  const [selectedRouteIndex, setSelectedRouteIndex] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    try {
      const draft = JSON.parse(window.localStorage.getItem(storageKey) || "null");
      setName(typeof draft?.name === "string" ? draft.name : "");
      setSteps(Array.isArray(draft?.steps) ? draft.steps : []);
    } catch {
      setName(""); setSteps([]);
    }
    setNotice("");
  }, [storageKey]);

  const addInspection = () => {
    if (!selectedPoint || steps.some((step) => step.type === "inspection" && step.waypoint_id === selectedPoint)) return;
    setSteps((current) => [...current, { type: "inspection", waypoint_id: selectedPoint }]);
    setNotice("");
  };
  const addTransit = () => {
    const point = routeWaypoints[Number(selectedRouteIndex)];
    if (!point) return;
    setSteps((current) => [...current, {
      type: "transit", id: window.crypto.randomUUID(), x: Number(point.x), y: Number(point.y),
      qx: Number(point.qx), qy: Number(point.qy), qz: Number(point.qz), qw: Number(point.qw),
    }]);
    setNotice("");
  };
  const move = (index, offset) => {
    const next = [...steps];
    const destination = index + offset;
    if (destination < 0 || destination >= next.length) return;
    [next[index], next[destination]] = [next[destination], next[index]];
    setSteps(next); setNotice("");
  };
  const save = () => {
    if (!name.trim() || !steps.length) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({ name: name.trim(), map_id: mapId, steps }));
      setNotice("编排草稿已保存在本浏览器；混合任务下发接口尚未接入。");
    } catch { setNotice("浏览器无法保存编排草稿。"); }
  };

  return <DashboardCard className="space-y-3 p-4">
    <h2 className="font-semibold">巡检任务编排</h2>
    <p className="text-xs text-themeTextGray">巡检点引用已保存的业务点；航点只控制途经位置。可用上下按钮将航点插入任意两步之间。</p>
    <label className="flex max-w-md flex-col gap-1 text-sm">任务名称<input maxLength={120} value={name} onChange={(event) => { setName(event.target.value); setNotice(""); }} className="rounded border border-borderSubtle bg-bgCard px-2 py-1.5" /></label>
    <div className="flex flex-wrap items-end gap-2 text-xs">
      <label className="flex flex-col gap-1">已保存巡检点<select value={selectedPoint} onChange={(event) => setSelectedPoint(event.target.value)} className="max-w-64 rounded border border-borderSubtle bg-bgCard p-2"><option value="">选择巡检点</option>{waypoints.filter((point) => point.enabled).map((point) => <option key={point.waypoint_id} value={point.waypoint_id}>{point.name}</option>)}</select></label>
      <button type="button" disabled={!selectedPoint || steps.some((step) => step.type === "inspection" && step.waypoint_id === selectedPoint)} onClick={addInspection} className="rounded border border-themeBlue px-3 py-2 disabled:opacity-50">加入巡检点</button>
      <label className="flex flex-col gap-1">地图临时航点<select value={selectedRouteIndex} onChange={(event) => setSelectedRouteIndex(event.target.value)} className="max-w-64 rounded border border-borderSubtle bg-bgCard p-2"><option value="">选择航点</option>{routeWaypoints.map((point, index) => <option key={index} value={index}>{index + 1}. ({Number(point.x).toFixed(2)}, {Number(point.y).toFixed(2)})</option>)}</select></label>
      <button type="button" disabled={selectedRouteIndex === ""} onClick={addTransit} className="rounded border border-themeBlue px-3 py-2 disabled:opacity-50">插入航点</button>
    </div>
    <ol className="space-y-1">{steps.map((step, index) => {
      const point = waypoints.find((item) => item.waypoint_id === step.waypoint_id);
      return <li key={step.type === "inspection" ? step.waypoint_id : step.id} className="flex flex-wrap items-center gap-2 rounded border border-borderSubtle px-2 py-1.5 text-xs">
        <span className="min-w-0 flex-1">{index + 1}. {step.type === "inspection" ? `巡检点 · ${point?.name || "已删除或不在当前地图"}` : `航点 · (${step.x.toFixed(2)}, ${step.y.toFixed(2)})`}</span>
        <button type="button" disabled={index === 0} onClick={() => move(index, -1)} className="disabled:opacity-40">上移</button>
        <button type="button" disabled={index === steps.length - 1} onClick={() => move(index, 1)} className="disabled:opacity-40">下移</button>
        <button type="button" onClick={() => { setSteps((current) => current.filter((_, position) => position !== index)); setNotice(""); }} className="text-statusRed">移除</button>
      </li>;
    })}</ol>
    <button type="button" disabled={!name.trim() || !steps.length || steps.some((step) => step.type === "inspection" && !waypoints.some((point) => point.waypoint_id === step.waypoint_id))} onClick={save} className="rounded bg-themeBlue px-3 py-2 text-xs text-white disabled:opacity-50">保存编排草稿</button>
    {notice && <p role="status" className="text-xs text-themeTextGray">{notice}</p>}
  </DashboardCard>;
}

import React, { useContext, useState } from "react";
import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import useRobotStatus from "../shared/hooks/useRobotStatus";
import { useRoleAccess } from "../shared/auth/roleAccess";

const PRESETS = [
  { label: "停留 1 秒", action: { kind: "wait", timeout_ms: 1000 } },
  { label: "拍照", action: { kind: "capture", timeout_ms: 15000 } },
  { label: "消防设施识别", action: { kind: "detect", timeout_ms: 15000, detector_types: ["fire_equipment"] } },
  { label: "烟火识别", action: { kind: "detect", timeout_ms: 15000, detector_types: ["fire_smoke"] } },
  { label: "语音播报", action: { kind: "broadcast", timeout_ms: 15000 } },
];

export default function InspectionPointCreate({ selectedPose, onCreated }) {
  const { robotId } = useContext(AuthContext);
  const mapId = useRobotStatus().snapshot?.current_map?.map_id || "";
  const access = useRoleAccess("Engineer");
  const [name, setName] = useState("");
  const [presetIds, setPresetIds] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const save = async () => {
    if (!access.allowed || !robotId || !mapId || !selectedPose || !name.trim() || busy) return;
    setBusy(true); setMessage("");
    let created = false;
    try {
      const { x, y, qx, qy, qz, qw } = selectedPose;
      const yaw = Math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy ** 2 + qz ** 2));
      const base = `/api/v1/robots/${encodeURIComponent(robotId)}`;
      const response = await apiFetch(`${base}/waypoints`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ map_id: mapId, name: name.trim(), x, y, yaw, wait_time: 0,
          source: "operator", point_type: "inspection" }),
      });
      const waypoint = await response.json();
      created = true;
      onCreated?.(waypoint.waypoint_id);
      const actions = presetIds.map((id) => PRESETS[id].action);
      if (actions.length) await apiFetch(`${base}/waypoints/${encodeURIComponent(waypoint.waypoint_id)}/action-plan`, {
        method: "PUT", headers: { "Content-Type": "application/json", "If-Match": "0" },
        body: JSON.stringify({ actions }),
      });
      setName(""); setPresetIds([]); setMessage(`巡检点已保存：${waypoint.name}`);
    } catch (error) {
      setMessage(created ? `巡检点已创建，但动作保存失败：${error.message || "请在下方管理区补充"}` : error.message || "巡检点创建失败");
    } finally { setBusy(false); }
  };

  return <div className="space-y-3 border-t border-borderSubtle pt-3">
    <h2 className="text-sm font-semibold">创建巡检点</h2>
    <p className="text-xs text-themeTextGray">{selectedPose ? `位置 (${selectedPose.x.toFixed(2)}, ${selectedPose.y.toFixed(2)}) m` : "先在左侧地图选择巡检点位置和朝向"}</p>
    <label className="flex flex-col gap-1 text-xs">名称<input maxLength={100} value={name} onChange={(event) => setName(event.target.value)} className="w-full rounded border border-borderSubtle bg-bgCard px-2 py-2" placeholder="例：一层消防柜" /></label>
    <fieldset className="grid grid-cols-1 gap-1 sm:grid-cols-2 xl:grid-cols-1"><legend className="mb-1 text-xs font-semibold">到点业务动作</legend>
      {PRESETS.map((preset, index) => <label key={preset.label} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={presetIds.includes(index)} onChange={(event) => setPresetIds((ids) => event.target.checked ? [...ids, index] : ids.filter((id) => id !== index))} />{preset.label}</label>)}
    </fieldset>
    <button type="button" disabled={!access.allowed || !mapId || !selectedPose || !name.trim() || busy} onClick={save} className="w-full rounded bg-themeBlue px-3 py-2 text-sm text-white disabled:opacity-50">{busy ? "保存中…" : "保存巡检点"}</button>
    <p className="text-[11px] text-themeTextGray">拍照、识别、播报先保存配置；实际执行取决于机器人端能力。</p>
    {message && <p role="status" className="text-xs">{message}</p>}
  </div>;
}

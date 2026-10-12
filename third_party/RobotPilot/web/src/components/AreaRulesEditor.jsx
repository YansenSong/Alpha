import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "react-toastify";

import Map from "./Map";
import { KeepoutZonesEditor } from "./KeepoutZones";
import useKeepoutZones from "../shared/hooks/useKeepoutZones";

const LABELS = {
  keepout: "禁行区",
  speed: "限速区",
  wall: "虚拟墙",
  closure: "临时封闭区",
};

const INITIAL_FORM = {
  type: "keepout",
  name: "",
  limit_mps: "0.3",
  minutes: "30",
  width: "0.1",
};

const inputClass =
  "min-h-9 rounded-lg border border-borderSubtle bg-bgCard px-2 text-xs text-textWhiteHover";

const AreaRulesEditor = () => {
  const rulesState = useKeepoutZones();
  const {
    ready,
    mapKey,
    mapId,
    mapVersionId,
    upsertRule,
    canEdit,
    permissionReason,
  } = rulesState;
  const [form, setForm] = useState(INITIAL_FORM);
  const [drawing, setDrawing] = useState(false);
  const [preview, setPreview] = useState(null);
  const formRef = useRef(form);
  const upsertRef = useRef(upsertRule);
  const mapKeyRef = useRef(mapKey);
  const mapVersionRef = useRef({ mapId, mapVersionId });
  formRef.current = form;
  upsertRef.current = upsertRule;

  const stopDrawing = useCallback(() => {
    setDrawing(false);
  }, []);

  useEffect(() => {
    if (drawing && !ready) stopDrawing();
  }, [drawing, ready, stopDrawing]);

  useEffect(() => {
    if (mapKeyRef.current && mapKeyRef.current !== mapKey) stopDrawing();
    mapKeyRef.current = mapKey;
  }, [mapKey, stopDrawing]);

  useEffect(() => {
    const previous = mapVersionRef.current;
    if (previous.mapId !== mapId || previous.mapVersionId !== mapVersionId) {
      stopDrawing();
    }
    mapVersionRef.current = { mapId, mapVersionId };
  }, [mapId, mapVersionId, stopDrawing]);

  const handleAreaDraw = useCallback(
    (geometry) => {
      if (!canEdit) return;
      if (!geometry) {
        toast.warn("请在地图上拖出足够大的区域或线段");
        return;
      }
      const current = formRef.current;
      const rule = {
        id:
          globalThis.crypto?.randomUUID?.() ||
          `area-${Date.now()}-${Math.random()}`,
        name: current.name.trim(),
        type: current.type,
        ...geometry,
      };
      if (current.type === "speed") rule.limit_mps = Number(current.limit_mps);
      if (current.type === "closure") rule.duration_seconds = Number(current.minutes) * 60;
      setPreview(rule);
      setDrawing(false);
    },
    [canEdit],
  );

  const startDrawing = () => {
    if (!ready || !canEdit) return;
    setDrawing(true);
  };

  const setField = (key) => (event) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));
  const valid =
    form.name.length <= 100 &&
    (form.type !== "speed" ||
      (Number.isFinite(Number(form.limit_mps)) &&
        Number(form.limit_mps) >= 0.01 &&
        Number(form.limit_mps) <= 5)) &&
    (form.type !== "closure" ||
      (Number.isFinite(Number(form.minutes)) &&
        Number(form.minutes) > 0 &&
        Number(form.minutes) <= 1440)) &&
    (form.type !== "wall" ||
      (Number.isFinite(Number(form.width)) &&
        Number(form.width) >= 0.01 &&
        Number(form.width) <= 5));

  return (
    <div className="space-y-3">
      <p className="text-sm text-themeTextGray">
        禁行区、虚拟墙和临时封闭区约束路径规划并触发行驶保护；限速区约束实际速度。规则按当前地图保存。
      </p>
      {!canEdit && (
        <p className="text-xs text-statusYellow">
          {permissionReason}；编辑地图规则需要 Engineer 权限。
        </p>
      )}
      <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(340px,1fr)]">
        <div className="h-[340px] min-w-0 sm:h-[440px] xl:h-[600px]">
          <Map
            drawingArea={drawing}
            areaDrawType={form.type}
            areaWallWidth={Number(form.width)}
            onAreaDraw={handleAreaDraw}
          />
        </div>
        <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center gap-2 font-[RobotoMono]">
        <select
          aria-label="地图规则类型"
          value={form.type}
          onChange={setField("type")}
          className={inputClass}
        >
          {Object.entries(LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <input
          aria-label="规则名称"
          placeholder="名称（可选）"
          value={form.name}
          onChange={setField("name")}
          className={`${inputClass} w-36`}
        />
        {form.type === "speed" && (
          <label className="text-xs text-themeTextGray">
            最高速度 m/s{" "}
            <input
              aria-label="最高速度"
              type="number"
              min="0.01"
              max="5"
              step="0.01"
              value={form.limit_mps}
              onChange={setField("limit_mps")}
              className={`${inputClass} ml-1 w-20`}
            />
          </label>
        )}
        {form.type === "closure" && (
          <label className="text-xs text-themeTextGray">
            封闭分钟{" "}
            <input
              aria-label="封闭时长"
              type="number"
              min="1"
              max="1440"
              step="1"
              value={form.minutes}
              onChange={setField("minutes")}
              className={`${inputClass} ml-1 w-20`}
            />
          </label>
        )}
        {form.type === "wall" && (
          <label className="text-xs text-themeTextGray">
            墙宽 m{" "}
            <input
              aria-label="虚拟墙宽度"
              type="number"
              min="0.01"
              max="5"
              step="0.01"
              value={form.width}
              onChange={setField("width")}
              className={`${inputClass} ml-1 w-20`}
            />
          </label>
        )}
        <button
          onClick={drawing ? stopDrawing : startDrawing}
          disabled={!canEdit || (!drawing && (!ready || !valid))}
          className={`min-h-9 rounded-lg border px-3 text-xs font-semibold disabled:opacity-40 ${
            drawing
              ? "border-statusRed text-statusRed"
              : "border-themeBlue text-themeBlue"
          }`}
        >
          {drawing ? "结束绘制" : "在地图上绘制"}
        </button>
      </div>
      <p className="text-xs text-themeTextGray">
        {drawing
          ? "按住并拖动地图绘制；矩形用于区域规则，线段用于虚拟墙。"
          : ready
          ? `当前地图有 ${rulesState.rules.length} 条规则。`
          : "等待机器人地图规则服务。"}
      </p>
      <p className="text-xs text-themeTextGray" role="status">
        地图 {mapId || "未加载"} · 版本 {mapVersionId || "未验证"} · 导航规则：
        {rulesState.application === "PENDING" ? "等待存储" :
          rulesState.application === "STORED" ? "已保存，等待导航确认" :
          rulesState.application === "APPLIED" ? "已应用" :
          rulesState.application === "FAILED" ? "应用失败" :
          rulesState.navigationApplied ? "已应用" : "尚未确认应用"}
      </p>
      {rulesState.navigationHold && (
        <p className="text-xs text-statusYellow" role="status">
          导航保持停车：{({ WAITING_RULES: "等待规则和地图校验", WAITING_COSTMAP: "等待代价地图确认",
            REPLANNING: "正在重新规划", PATH_INSTALL: "等待控制器安装新路径",
            PATH_BLOCKED: "原路径受阻", NO_VALID_PATH: "暂无可行路径",
            MAP_CHANGED: "地图已切换，等待新目标" })[
            rulesState.navigationHoldReason] || rulesState.navigationHoldReason}
        </p>
      )}
      <p className="text-xs text-themeTextGray">
        配置限速：{rulesState.configuredSpeedLimit ?? "—"} m/s · 当前约束速度：
        {rulesState.constrainedSpeedLimit ?? "—"} m/s · 实际反馈速度：
        {rulesState.actualSpeed ?? "—"} m/s
      </p>
      {preview && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-themeBlue p-2 text-xs">
          <span>预览：{LABELS[preview.type]} {preview.name || preview.id}</span>
          <button className="rounded border border-themeBlue px-2 py-1 text-themeBlue"
            onClick={() => {
              if (upsertRef.current(preview)) toast.info("规则已发送，等待机器人确认");
              setPreview(null);
            }}>确认保存并应用</button>
          <button className="rounded border border-borderSubtle px-2 py-1"
            onClick={() => setPreview(null)}>取消</button>
        </div>
      )}
      {rulesState.error && (
        <p role="alert" className="text-xs text-statusRed">
          {rulesState.error}
        </p>
      )}
      <details className="rounded-lg border border-borderSubtle p-3">
        <summary className="cursor-pointer text-xs text-themeBlue">
          规则列表与坐标录入
        </summary>
        <div className="mt-3">
          <KeepoutZonesEditor {...rulesState} />
        </div>
      </details>
        </div>
      </div>
    </div>
  );
};

export default AreaRulesEditor;

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
    if (mapKeyRef.current && mapKeyRef.current !== mapKey) {
      stopDrawing();
      setPreview(null);
    }
    mapKeyRef.current = mapKey;
  }, [mapKey, stopDrawing]);

  useEffect(() => {
    const previous = mapVersionRef.current;
    if (previous.mapId !== mapId || previous.mapVersionId !== mapVersionId) {
      stopDrawing();
      setPreview(null);
    }
    mapVersionRef.current = { mapId, mapVersionId };
  }, [mapId, mapVersionId, stopDrawing]);

  useEffect(() => {
    if (preview && rulesState.rules.some((rule) => rule.id === preview.id)) {
      setPreview(null);
    }
  }, [preview, rulesState.rules]);

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
      if (current.type === "closure")
        rule.duration_seconds = Number(current.minutes) * 60;
      setPreview(rule);
      setDrawing(false);
    },
    [canEdit],
  );

  const startDrawing = () => {
    if (!ready || !canEdit) return;
    setPreview(null);
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
            areaPreview={preview}
            onAreaDraw={handleAreaDraw}
          />
        </div>
        <aside className="min-w-0 space-y-3" aria-label="地图规则工作台">
          <section className="rounded-xl border border-borderSubtle bg-bgSurface/50 p-4">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-textWhiteHover">
                  绘制地图规则
                </h3>
                <p className="mt-1 text-xs text-themeTextGray">
                  设置规则后，在左侧地图拖动绘制。
                </p>
              </div>
              <span className="shrink-0 rounded-full border border-borderSubtle px-2 py-1 text-xs text-themeTextGray">
                {rulesState.rules.length} 条规则
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <label className="workspace-field">
                <span>规则类型</span>
                <select value={form.type} onChange={setField("type")}>
                  {Object.entries(LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="workspace-field">
                <span>
                  名称{" "}
                  <span className="font-normal text-themeTextGray">
                    （可选）
                  </span>
                </span>
                <input
                  placeholder="例如：仓库入口"
                  maxLength={100}
                  value={form.name}
                  onChange={setField("name")}
                />
              </label>
              {form.type === "speed" && (
                <label className="workspace-field">
                  <span>最高速度（m/s）</span>
                  <input
                    type="number"
                    min="0.01"
                    max="5"
                    step="0.01"
                    value={form.limit_mps}
                    onChange={setField("limit_mps")}
                  />
                </label>
              )}
              {form.type === "closure" && (
                <label className="workspace-field">
                  <span>封闭时长（分钟）</span>
                  <input
                    type="number"
                    min="1"
                    max="1440"
                    step="1"
                    value={form.minutes}
                    onChange={setField("minutes")}
                  />
                </label>
              )}
              {form.type === "wall" && (
                <label className="workspace-field">
                  <span>虚拟墙宽度（m）</span>
                  <input
                    type="number"
                    min="0.01"
                    max="5"
                    step="0.01"
                    value={form.width}
                    onChange={setField("width")}
                  />
                </label>
              )}
            </div>
            <button
              onClick={drawing ? stopDrawing : startDrawing}
              disabled={!canEdit || (!drawing && (!ready || !valid))}
              className={`workspace-action mt-4 w-full ${
                drawing
                  ? "border-statusRed text-statusRed"
                  : "workspace-action--primary"
              }`}
            >
              {drawing ? "结束绘制" : "在地图上绘制"}
            </button>
            <p
              className="mt-2 text-xs leading-5 text-themeTextGray"
              role="status"
            >
              {drawing
                ? "在地图上按住并拖动；区域规则绘制矩形，虚拟墙绘制线段。"
                : ready
                ? "绘制完成后，可先查看地图预览，再保存规则。"
                : "等待机器人地图规则服务。"}
            </p>
          </section>

          {preview && (
            <section
              className="rounded-xl border border-themeBlue bg-themeBlue/5 p-4"
              aria-label="待保存规则"
            >
              <p className="text-xs font-semibold text-themeBlue">
                待保存 · 地图预览中
              </p>
              <p className="mt-1 break-all text-sm font-medium text-textWhiteHover">
                {LABELS[preview.type]} · {preview.name || "未命名规则"}
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  className="workspace-action workspace-action--primary"
                  onClick={() => {
                    if (upsertRef.current(preview))
                      toast.info("规则已发送，等待机器人确认");
                  }}
                >
                  保存并应用
                </button>
                <button
                  className="workspace-action"
                  onClick={() => setPreview(null)}
                >
                  取消预览
                </button>
              </div>
            </section>
          )}

          {rulesState.error && (
            <p
              role="alert"
              className="rounded-lg border border-statusRed/40 p-3 text-xs text-statusRed"
            >
              {rulesState.error}
            </p>
          )}
          <details className="rounded-xl border border-borderSubtle bg-bgSurface/30 p-3">
            <summary className="cursor-pointer py-1 text-sm font-medium text-textWhiteHover">
              规则管理
              <span className="ml-2 text-xs font-normal text-themeTextGray">
                {rulesState.rules.length} 条
              </span>
            </summary>
            <div className="mt-3 border-t border-borderSubtle pt-3">
              <KeepoutZonesEditor {...rulesState} />
            </div>
          </details>
        </aside>
      </div>
    </div>
  );
};

export default AreaRulesEditor;

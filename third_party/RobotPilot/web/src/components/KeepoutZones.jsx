import { areaRuleColors } from "../shared/robot/areaRuleColors";
import React, { useState } from "react";

import useKeepoutZones from "../shared/hooks/useKeepoutZones";

const EMPTY = {
  type: "keepout",
  name: "",
  cx: "",
  cy: "",
  w: "",
  h: "",
  x1: "",
  y1: "",
  x2: "",
  y2: "",
  width: "0.1",
  limit_mps: "0.3",
  minutes: "30",
};
const LABELS = {
  keepout: "禁行区",
  speed: "限速区",
  wall: "虚拟墙",
  closure: "临时封闭区",
};
const formatMeters = (value) => {
  const number = Number(value);
  return Number.isFinite(number)
    ? number
        .toFixed(2)
        .replace(/\.0+$/, "")
        .replace(/(\.\d*?)0+$/, "$1")
    : "—";
};

const readLegacy = () => {
  try {
    const saved = JSON.parse(
      localStorage.getItem("robotpilotKeepoutZones") || "[]",
    );
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
};

export const KeepoutZonesEditor = ({
  rules,
  ready,
  mapKey,
  observedAt,
  stale = false,
  error,
  upsertRule,
  deleteRule,
  setRuleEnabled,
  application,
  canEdit = false,
  permissionReason,
  section = "all",
}) => {
  const [changingId, setChangingId] = useState(null);
  const [toggleError, setToggleError] = useState("");
  const controlsBusy = changingId !== null || application === "PENDING";
  const toggleRule = async (rule) => {
    if (controlsBusy || !ready || !canEdit || !setRuleEnabled) return;
    setChangingId(rule.id);
    setToggleError("");
    try { await setRuleEnabled(rule.id, rule.enabled === false); }
    catch (cause) { setToggleError(cause.message || "规则状态更新失败"); }
    finally { setChangingId(null); }
  };
  const [form, setForm] = useState(EMPTY);
  const [preview, setPreview] = useState(null);
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const [legacy] = useState(readLegacy);
  const set = (field) => (event) =>
    setForm((old) => ({ ...old, [field]: event.target.value }));
  const field = (key, label) => (
    <label key={key} className="workspace-field">
      <span>{label}</span>
      <input
        value={form[key]}
        onChange={set(key)}
        inputMode={key === "name" ? "text" : "decimal"}
      />
    </label>
  );

  const numbers =
    form.type === "wall"
      ? ["x1", "y1", "x2", "y2", "width"]
      : ["cx", "cy", "w", "h"];
  const valid =
    numbers.every(
      (key) => form[key] !== "" && Number.isFinite(Number(form[key])),
    ) &&
    (form.type === "wall"
      ? Number(form.width) > 0
      : Number(form.w) > 0 && Number(form.h) > 0) &&
    (form.type !== "speed" ||
      (Number.isFinite(Number(form.limit_mps)) &&
        Number(form.limit_mps) > 0)) &&
    (form.type !== "closure" ||
      (Number.isFinite(Number(form.minutes)) &&
        Number(form.minutes) > 0 &&
        Number(form.minutes) <= 1440));

  const add = () => {
    if (!valid) return;
    const rule = {
      id:
        globalThis.crypto?.randomUUID?.() ||
        `area-${Date.now()}-${Math.random()}`,
      type: form.type,
      name: form.name.trim(),
    };
    numbers.forEach((key) => {
      rule[key] = Number(form[key]);
    });
    if (form.type === "speed") rule.limit_mps = Number(form.limit_mps);
    if (form.type === "closure") {
      rule.duration_seconds = Number(form.minutes) * 60;
    }
    setPreview(rule);
  };

  const legacyMissing = legacy.filter(
    (old) => !rules.some((rule) => rule.id === `legacy-${old.id}`),
  );
  const showRules = section !== "coordinates";
  const showCoordinates = section !== "rules";
  const coordinateForm = (
    <>
      {!canEdit && (
        <p className="mt-2 text-xs text-statusYellow">
          {permissionReason || "需要 Engineer 权限"}
        </p>
      )}
      <p className="mt-1 text-xs leading-5 text-themeTextGray">
        适用于已知地图坐标的精确录入。普通绘制请使用上方地图。
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
        <label className="workspace-field">
          <span>规则类型</span>
          <select value={form.type} onChange={set("type")}>
            {Object.entries(LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {field("name", "名称（可选）")}
        {form.type === "wall" ? (
          <>
            {field("x1", "起点 X（m）")}
            {field("y1", "起点 Y（m）")}
            {field("x2", "终点 X（m）")}
            {field("y2", "终点 Y（m）")}
            {field("width", "墙宽（m）")}
          </>
        ) : (
          <>
            {field("cx", "中心 X（m）")}
            {field("cy", "中心 Y（m）")}
            {field("w", "宽（m）")}
            {field("h", "高（m）")}
          </>
        )}
        {form.type === "speed" && field("limit_mps", "最高速度（m/s）")}
        {form.type === "closure" && field("minutes", "封闭时长（分钟）")}
      </div>
      <button
        onClick={add}
        disabled={!ready || !valid || !canEdit}
        className="workspace-action workspace-action--primary mt-3 w-full"
      >
        预览规则
      </button>
      {preview && (
        <div className="mt-3 rounded-lg border border-themeBlue bg-themeBlue/5 p-3">
          <p className="text-xs font-semibold text-themeBlue">
            待保存 · 坐标预览
          </p>
          <p className="mt-1 text-sm text-textWhiteHover">
            {LABELS[preview.type]} · {preview.name || "未命名规则"}
          </p>
          <p className="mt-1 break-all text-xs text-themeTextGray">
            {preview.type === "wall"
              ? `(${formatMeters(preview.x1)}, ${formatMeters(
                  preview.y1,
                )}) → (${formatMeters(preview.x2)}, ${formatMeters(
                  preview.y2,
                )}) · 墙宽 ${formatMeters(preview.width)} m`
              : `中心 (${formatMeters(preview.cx)}, ${formatMeters(
                  preview.cy,
                )}) · ${formatMeters(preview.w)} × ${formatMeters(
                  preview.h,
                )} m`}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              className="workspace-action workspace-action--primary"
              onClick={() => {
                if (upsertRule(preview)) setPreview(null);
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
        </div>
      )}
    </>
  );

  return (
    <div className="space-y-4">
      {section !== "coordinates" && <div className="flex flex-wrap items-center gap-2 text-xs">
        <span
          className={`rounded-full px-2 py-1 ${
            ready && !stale
              ? "bg-statusGreen/10 text-statusGreen"
              : "bg-statusYellow/10 text-statusYellow"
          }`}
        >
          {ready && !stale
            ? "规则服务在线"
            : observedAt
            ? "规则快照已过期"
            : "等待规则服务"}
        </span>
        <span className="text-themeTextGray">
          地图 {mapKey?.slice(0, 8) || "未加载"}
        </span>
        {stale && observedAt && (
          <span className="text-themeTextGray">
            更新于 {new Date(observedAt).toLocaleString()}
          </span>
        )}
      </div>}
      {section !== "coordinates" && !canEdit && (
        <p className="text-xs text-statusYellow">
          {permissionReason || "需要 Engineer 权限"}
        </p>
      )}
      {section !== "coordinates" && error && (
        <p role="alert" className="text-xs text-statusRed">
          {error}
        </p>
      )}

      {showRules && <section aria-label="已保存规则">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-textWhiteHover">
            已保存规则
          </h4>
          <span className="text-xs text-themeTextGray">{rules.length} 条</span>
        </div>
        {rules.length === 0 ? (
          <p className="rounded-lg border border-dashed border-borderSubtle p-4 text-center text-xs text-themeTextGray">
            当前地图还没有规则。可在地图上绘制，或使用坐标录入卡片。
          </p>
        ) : (
          <div className="space-y-2">
            {rules.map((rule, index) => (
              <article
                key={rule.id}
                className={`rounded-lg border border-borderSubtle p-3 ${rule.enabled === false ? "bg-bgSurface/30" : "bg-bgCard/50"}`}
              >
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <div className="min-w-0">
                    <span className="mr-2 inline-flex min-h-7 min-w-7 items-center justify-center rounded-full text-xs font-bold text-white"
                      style={{ backgroundColor: areaRuleColors(rule).badge }}>
                      {index + 1}
                    </span>
                    <span className="inline-flex rounded-md px-2 py-1 text-xs font-semibold text-white"
                      style={{ backgroundColor: areaRuleColors(rule).badge }}>
                      {LABELS[rule.type] || rule.type}
                    </span>
                    <p
                      className="mt-2 truncate text-sm font-medium text-textWhiteHover"
                      title={rule.name || "未命名规则"}
                    >
                      {rule.name || "未命名规则"}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => toggleRule(rule)}
                      disabled={!ready || !canEdit || controlsBusy || !setRuleEnabled}
                      aria-label={`${rule.enabled === false ? "启用" : "禁用"} ${rule.name || "未命名规则"}`}
                      className="workspace-action min-h-11 px-3 disabled:opacity-40"
                    >
                      {changingId === rule.id ? "保存中…" : rule.enabled === false ? "启用" : "禁用"}
                    </button>
                  <button
                    onClick={() => setDeleteCandidate(rule)}
                    disabled={!ready || !canEdit || controlsBusy}
                    aria-label={`删除 ${rule.name || "未命名规则"}`}
                    className="workspace-action min-h-11 shrink-0 border-statusRed/40 px-3 text-statusRed disabled:opacity-40"
                  >
                    删除
                  </button>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-themeTextGray">
                  <span className={rule.enabled === false ? "text-themeTextGray" : "text-statusGreen"}>
                    {rule.enabled === false ? "已禁用" : "已启用"}
                  </span>
                  <span>
                    {rule.type === "speed"
                      ? `最高 ${formatMeters(rule.limit_mps)} m/s`
                      : rule.type === "wall"
                      ? `墙宽 ${formatMeters(rule.width)} m`
                      : `${formatMeters(rule.w)} × ${formatMeters(rule.h)} m`}
                  </span>
                  <span>
                    {rule.expires_at
                      ? `有效至 ${new Date(rule.expires_at).toLocaleString()}`
                      : "长期有效"}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>}

      {showRules && toggleError && <p role="alert" className="text-xs text-statusRed">{toggleError}</p>}
      {showRules && deleteCandidate && (
        <div
          role="alertdialog"
          aria-label="确认删除规则"
          className="rounded-lg border border-statusRed/50 bg-statusRed/5 p-3"
        >
          <p className="text-sm font-medium text-textWhiteHover">
            删除“
            {deleteCandidate.name || "未命名规则"}
            ”？
          </p>
          <p className="mt-1 text-xs text-themeTextGray">
            当前导航路径可能需要重新规划。
          </p>
          <div className="mt-3 flex gap-2">
            <button
              className="workspace-action border-statusRed/50 text-statusRed"
              onClick={() => {
                if (deleteRule(deleteCandidate.id)) setDeleteCandidate(null);
              }}
            >
              确认删除
            </button>
            <button
              className="workspace-action"
              onClick={() => setDeleteCandidate(null)}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {showCoordinates && (section === "coordinates" ? (
        coordinateForm
      ) : (
        <details className="border-t border-borderSubtle pt-3">
          <summary className="cursor-pointer py-2 text-sm font-medium text-themeBlue">
            通过坐标添加规则
          </summary>
          {coordinateForm}
        </details>
      ))}
      {showRules && ready && legacyMissing.length > 0 && (
        <div className="rounded-lg border border-statusYellow/40 p-2">
          <p className="mb-1 text-statusYellow">
            此浏览器有 {legacyMissing.length} 条旧禁行区，需要逐条导入机器人。
          </p>
          {legacyMissing.map((old) => (
            <button
              key={old.id}
              disabled={!canEdit}
              className="mr-2 text-themeBlue underline disabled:opacity-40"
              onClick={() =>
                upsertRule({
                  id: `legacy-${old.id}`,
                  name: old.name || "旧禁行区",
                  type: "keepout",
                  cx: Number(old.cx),
                  cy: Number(old.cy),
                  w: Number(old.w),
                  h: Number(old.h),
                })
              }
            >
              导入 {old.name || "未命名规则"}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const KeepoutZones = () => <KeepoutZonesEditor {...useKeepoutZones()} />;

export default KeepoutZones;

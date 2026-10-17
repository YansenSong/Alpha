import { areaRuleColors } from "../shared/robot/areaRuleColors";
import React, {
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { AuthContext } from "../app/App";
import { apiFetch } from "../shared/api/apiFetch";
import { KeepoutZonesEditor } from "./KeepoutZones";

const LABELS = {
  keepout: "禁行区",
  speed: "限速区",
  wall: "虚拟墙",
  closure: "临时封闭区",
};

export default function SavedMapRulesEditor({ selection }) {
  const { robotId } = useContext(AuthContext);
  const [map, setMap] = useState(null);
  const [viewport, setViewport] = useState(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [type, setType] = useState("keepout");
  const [name, setName] = useState("");
  const [parameter, setParameter] = useState("0.3");
  const [wallWidth, setWallWidth] = useState("0.1");
  const [drawing, setDrawing] = useState(false);
  const [start, setStart] = useState(null);
  const [end, setEnd] = useState(null);
  const [preview, setPreview] = useState(null);
  const svgRef = useRef(null);
  const panRef = useRef(null);
  const base = `/api/v1/robots/${encodeURIComponent(
    robotId || "",
  )}/maps/saved/${encodeURIComponent(selection.group)}/${encodeURIComponent(
    selection.map,
  )}`;
  const query = `?source=${selection.source === "project" ? "project" : "ui"}`;

  const load = useCallback(async () => {
    if (!robotId) return;
    try {
      const [mapResponse, rulesResponse] = await Promise.all([
        apiFetch(`${base}${query}`),
        apiFetch(`${base}/rules${query}`),
      ]);
      const nextMap = await mapResponse.json();
      const nextState = await rulesResponse.json();
      if (nextMap.map_key !== nextState.map_key)
        throw new Error("地图与规则版本不一致，请刷新");
      setMap(nextMap);
      setViewport({ x: 0, y: 0, width: nextMap.width, height: nextMap.height });
      setState(nextState);
      setError("");
    } catch (cause) {
      setError(cause.message || "无法加载已保存地图");
    }
  }, [base, query, robotId]);
  useEffect(() => {
    load();
  }, [load]);

  const toWorld = (point) => {
    const dx = point.x * map.resolution;
    const dy = (map.height - point.y) * map.resolution;
    const [ox, oy, yaw] = map.origin;
    return {
      x: ox + Math.cos(yaw) * dx - Math.sin(yaw) * dy,
      y: oy + Math.sin(yaw) * dx + Math.cos(yaw) * dy,
    };
  };
  const toPixel = (x, y) => {
    const [ox, oy, yaw] = map.origin;
    const dx = x - ox;
    const dy = y - oy;
    return {
      x: (Math.cos(yaw) * dx + Math.sin(yaw) * dy) / map.resolution,
      y:
        map.height -
        (-Math.sin(yaw) * dx + Math.cos(yaw) * dy) / map.resolution,
    };
  };
  const pointer = (event) => {
    const point = svgRef.current.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(
      svgRef.current.getScreenCTM().inverse(),
    );
    return {
      x: Math.max(0, Math.min(map.width, local.x)),
      y: Math.max(0, Math.min(map.height, local.y)),
    };
  };
  const limitViewport = (next) => ({
    ...next,
    x: Math.max(0, Math.min(map.width - next.width, next.x)),
    y: Math.max(0, Math.min(map.height - next.height, next.y)),
  });
  const limitPanViewport = (next) => {
    const overscroll = map.width / next.width > 1.001 ? 0.15 : 0;
    const marginX = next.width * overscroll;
    const marginY = next.height * overscroll;
    return {
      ...next,
      x: Math.max(-marginX, Math.min(map.width - next.width + marginX, next.x)),
      y: Math.max(-marginY, Math.min(map.height - next.height + marginY, next.y)),
    };
  };
  const zoomAt = (factor, anchor) => {
    if (!map) return;
    setViewport((current) => {
      if (!current) return current;
      const zoom = Math.max(
        1,
        Math.min(8, (map.width / current.width) * factor),
      );
      const width = map.width / zoom;
      const height = map.height / zoom;
      const xRatio = (anchor.x - current.x) / current.width;
      const yRatio = (anchor.y - current.y) / current.height;
      return limitViewport({
        x: anchor.x - xRatio * width,
        y: anchor.y - yRatio * height,
        width,
        height,
      });
    });
  };
  const zoomFromCenter = (factor) => {
    if (!viewport) return;
    zoomAt(factor, {
      x: viewport.x + viewport.width / 2,
      y: viewport.y + viewport.height / 2,
    });
  };
  const finish = (event) => {
    if (!start || !map) return;
    const last = pointer(event);
    setEnd(last);
    setDrawing(false);
    if (Math.hypot(last.x - start.x, last.y - start.y) < 3) {
      setError("绘制范围太小，请重新绘制");
      return;
    }
    const a = toWorld(start);
    const b = toWorld(last);
    const rule = {
      id: globalThis.crypto?.randomUUID?.() || `area-${Date.now()}`,
      name: name.trim(),
      type,
    };
    if (type === "wall") {
      Object.assign(rule, {
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        width: Number(wallWidth),
      });
    } else {
      Object.assign(rule, {
        cx: (a.x + b.x) / 2,
        cy: (a.y + b.y) / 2,
        w: Math.abs(a.x - b.x),
        h: Math.abs(a.y - b.y),
      });
    }
    if (type === "speed") rule.limit_mps = Number(parameter);
    if (type === "closure") rule.duration_seconds = Number(parameter) * 60;
    setPreview(rule);
    setError("");
  };
  const mutate = async (action, rule) => {
    if (!state || busy) return false;
    setBusy(true);
    try {
      const response = await apiFetch(`${base}/rules${query}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          map_key: map.map_key,
          expected_version: state.version,
          action,
          rule,
        }),
      });
      setState(await response.json());
      setPreview(null);
      setStart(null);
      setEnd(null);
      setError("");
      return true;
    } catch (cause) {
      setError(cause.message || "规则保存失败");
      return false;
    } finally {
      setBusy(false);
    }
  };
  const ruleShape = (rule, key, previewing = false, index = -1) => {
    if (!map) return null;
    const zoom = map.width / (viewport?.width || map.width);
    const colors = areaRuleColors(rule);
    const style = {
      fill: colors.fill,
      stroke: colors.stroke,
      strokeWidth: 2 / zoom,
    };
    const label = (x, y) => !previewing && (
      <g pointerEvents="none">
        <circle cx={x} cy={y} r={11} fill={colors.badge} stroke="white" strokeWidth={2 / zoom} />
        <text x={x} y={y} dy="0.35em" textAnchor="middle" fill="white" fontSize={11} fontWeight="700">{index + 1}</text>
      </g>
    );
    const typeName = `${LABELS[rule.type] || "区域规则"}${rule.enabled === false ? "（已禁用）" : ""}`;
    const typeLabel = (x, y, availableWidth = Infinity, availableHeight = Infinity) => (
      <text x={x} y={y} dy="0.35em" textAnchor="middle" pointerEvents="none"
        fill={colors.badge} stroke="white" strokeWidth={3 / zoom} paintOrder="stroke"
        fontSize={Math.min(13, availableWidth * .85 / typeName.length, availableHeight * .4)}
        fontWeight="700">{typeName}</text>
    );
    if (rule.type === "wall") {
      const a = toPixel(rule.x1, rule.y1);
      const b = toPixel(rule.x2, rule.y2);
      return (
        <g key={key}>
          <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={style.stroke} strokeWidth={Math.max(3 / zoom, rule.width / map.resolution)} opacity="0.7" />
          {label((a.x + b.x) / 2, (a.y + b.y) / 2)}
          {typeLabel((a.x + b.x) / 2, (a.y + b.y) / 2 + 23)}
        </g>
      );
    }
    const a = toPixel(rule.cx - rule.w / 2, rule.cy + rule.h / 2);
    const b = toPixel(rule.cx + rule.w / 2, rule.cy - rule.h / 2);
    return (
      <g key={key}>
        <rect x={Math.min(a.x, b.x)} y={Math.min(a.y, b.y)} width={Math.abs(b.x - a.x)} height={Math.abs(b.y - a.y)} {...style} />
        {label(Math.min(a.x, b.x) + Math.min(15, Math.abs(b.x - a.x) / 4),
          Math.min(a.y, b.y) + Math.min(15, Math.abs(b.y - a.y) / 4))}
        {typeLabel((a.x + b.x) / 2, (a.y + b.y) / 2, Math.abs(b.x - a.x), Math.abs(b.y - a.y))}
      </g>
    );
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
      <div className="relative flex min-h-[360px] items-center justify-center overflow-hidden rounded-xl border border-borderSubtle bg-bgSurface xl:min-h-[600px]">
        {map && (
          <p className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-lg bg-bgCard/90 px-2 py-1 text-xs text-themeTextGray">
            {drawing ? "拖动绘制规则" : "滚轮缩放 · 拖动平移"}
          </p>
        )}
        {map && viewport && (
          <div className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-xl border border-borderSubtle bg-bgCard/95 p-1 shadow-lg">
            <button
              type="button"
              className="workspace-action min-h-11 min-w-11 px-2"
              aria-label="放大地图"
              onClick={() => zoomFromCenter(1.25)}
            >
              ＋
            </button>
            <span className="min-w-12 text-center text-xs text-themeTextGray">
              {Math.round((map.width / viewport.width) * 100)}%
            </span>
            <button
              type="button"
              className="workspace-action min-h-11 min-w-11 px-2"
              aria-label="缩小地图"
              onClick={() => zoomFromCenter(0.8)}
            >
              －
            </button>
            <button
              type="button"
              className="workspace-action min-h-11 px-3"
              onClick={() =>
                setViewport({
                  x: 0,
                  y: 0,
                  width: map.width,
                  height: map.height,
                })
              }
            >
              适应
            </button>
          </div>
        )}
        {map ? (
          <svg
            ref={svgRef}
            viewBox={`${viewport?.x || 0} ${viewport?.y || 0} ${
              viewport?.width || map.width
            } ${viewport?.height || map.height}`}
            className={`max-h-[600px] w-full touch-none ${
              drawing
                ? "cursor-crosshair"
                : "cursor-grab active:cursor-grabbing"
            }`}
            onWheel={(event) => {
              event.preventDefault();
              zoomAt(Math.exp(-event.deltaY * 0.001), pointer(event));
            }}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              if (!drawing) {
                panRef.current = {
                  pointerId: event.pointerId,
                  clientX: event.clientX,
                  clientY: event.clientY,
                };
                return;
              }
              const point = pointer(event);
              setStart(point);
              setEnd(point);
            }}
            onPointerMove={(event) => {
              const pan = panRef.current;
              if (pan?.pointerId === event.pointerId) {
                const matrix = event.currentTarget.getScreenCTM();
                const scaleX = Math.hypot(matrix.a, matrix.b);
                const scaleY = Math.hypot(matrix.c, matrix.d);
                const deltaX = event.clientX - pan.clientX;
                const deltaY = event.clientY - pan.clientY;
                pan.clientX = event.clientX;
                pan.clientY = event.clientY;
                if (scaleX > 0 && scaleY > 0) {
                  setViewport((current) =>
                    current
                      ? limitPanViewport({
                          ...current,
                          x: current.x - deltaX / scaleX,
                          y: current.y - deltaY / scaleY,
                        })
                      : current,
                  );
                }
                return;
              }
              if (drawing && start) setEnd(pointer(event));
            }}
            onPointerUp={(event) => {
              if (panRef.current?.pointerId === event.pointerId) {
                panRef.current = null;
                return;
              }
              if (drawing) finish(event);
            }}
            onPointerCancel={() => {
              panRef.current = null;
              setStart(null);
              setEnd(null);
            }}
          >
            <image
              href={`${base}/image${query}`}
              width={map.width}
              height={map.height}
            />
            {(state?.rules || []).map((rule, index) => ruleShape(rule, rule.id, false, index))}
            {preview && ruleShape(preview, "preview", true)}
            {drawing &&
              start &&
              end &&
              (type === "wall" ? (
                <line
                  x1={start.x}
                  y1={start.y}
                  x2={end.x}
                  y2={end.y}
                  stroke="#3b82f6"
                  strokeWidth="3"
                />
              ) : (
                <rect
                  x={Math.min(start.x, end.x)}
                  y={Math.min(start.y, end.y)}
                  width={Math.abs(end.x - start.x)}
                  height={Math.abs(end.y - start.y)}
                  fill="#3b82f655"
                  stroke="#3b82f6"
                  strokeWidth="2"
                />
              ))}
          </svg>
        ) : (
          <p className="text-sm text-themeTextGray">正在读取已保存地图…</p>
        )}
      </div>
      <aside className="space-y-3">
        <details className="rounded-xl border border-borderSubtle bg-bgSurface/50 p-4">
          <summary className="cursor-pointer text-sm font-semibold text-textWhiteHover">
            绘制地图规则
          </summary>
          <div className="mt-3">
          <p className="mt-1 text-xs text-themeTextGray">
            保存后自动同步当前地图；其他地图的规则会在加载该地图时生效。
          </p>
          <div className="mt-4 space-y-3">
            <label className="workspace-field">
              <span>规则类型</span>
              <select
                value={type}
                onChange={(event) => {
                  setType(event.target.value);
                  setPreview(null);
                }}
              >
                {Object.entries(LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="workspace-field">
              <span>名称（可选）</span>
              <input
                value={name}
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            {type === "wall" && (
              <label className="workspace-field">
                <span>虚拟墙宽度（m）</span>
                <input
                  type="number"
                  min="0.01"
                  max="5"
                  step="0.01"
                  value={wallWidth}
                  onChange={(event) => setWallWidth(event.target.value)}
                />
              </label>
            )}
            {(type === "speed" || type === "closure") && (
              <label className="workspace-field">
                <span>
                  {type === "speed" ? "最高速度（m/s）" : "封闭时长（分钟）"}
                </span>
                <input
                  type="number"
                  min={type === "speed" ? "0.01" : "1"}
                  max={type === "speed" ? "5" : "1440"}
                  value={parameter}
                  onChange={(event) => setParameter(event.target.value)}
                />
              </label>
            )}
          </div>
          <button
            className="workspace-action workspace-action--primary mt-4 w-full"
            disabled={!map || busy}
            onClick={() => {
              setPreview(null);
              setStart(null);
              setEnd(null);
              setDrawing((value) => !value);
            }}
          >
            {drawing ? "结束绘制" : "在地图上绘制"}
          </button>
          {preview && (
            <div className="mt-3 rounded-lg border border-themeBlue p-3 text-sm">
              <p>
                待保存：{LABELS[preview.type]} · {preview.name || "未命名"}
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  className="workspace-action workspace-action--primary"
                  disabled={busy}
                  onClick={() => mutate("upsert", preview)}
                >
                  保存规则
                </button>
                <button
                  className="workspace-action"
                  onClick={() => setPreview(null)}
                >
                  取消
                </button>
              </div>
            </div>
          )}
          </div>
        </details>
        {state && (
          <details className="rounded-xl border border-borderSubtle bg-bgSurface/50 p-4">
            <summary className="cursor-pointer text-sm font-semibold text-textWhiteHover">
              通过坐标添加规则
            </summary>
            <div className="mt-3">
              <KeepoutZonesEditor
                rules={state.rules}
                section="coordinates"
                ready={!busy}
                mapKey={map.map_key}
                upsertRule={(rule) => mutate("upsert", rule)}
                deleteRule={(id) => mutate("delete", { id })}
                setRuleEnabled={(id, enabled) => mutate("set_enabled", { id, enabled })}
                canEdit={!busy}
              />
            </div>
          </details>
        )}
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-statusRed/40 p-3 text-xs text-statusRed"
          >
            {error}
          </p>
        )}
        {state && (
          <details className="rounded-xl border border-borderSubtle bg-bgSurface/50 p-4">
            <summary className="cursor-pointer text-sm font-semibold text-textWhiteHover">
              规则管理 · {state.rules.length} 条
            </summary>
            <div className="mt-3">
              <KeepoutZonesEditor
                rules={state.rules}
                section="rules"
                ready={!busy}
                mapKey={map.map_key}
                upsertRule={(rule) => mutate("upsert", rule)}
                deleteRule={(id) => mutate("delete", { id })}
                setRuleEnabled={(id, enabled) => mutate("set_enabled", { id, enabled })}
                canEdit={!busy}
              />
            </div>
          </details>
        )}
      </aside>
    </div>
  );
}

import { areaRuleColors } from "../shared/robot/areaRuleColors";
import { T, useT } from "../shared/i18n/i18n";
import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
  forwardRef,
  useImperativeHandle,
} from "react";

import { useRos } from "../app/App";
import { AppConfig } from "../shared/constants";

import { IconButton } from "../shared/ui/Dashboard";

/**
 * NAV2D 安全辅助逻辑。
 */
const getNav2D = () => (typeof window !== "undefined" ? window.NAV2D : null);

const ensureNav2D = () => {
  if (typeof window === "undefined") return null;
  window.NAV2D = window.NAV2D || {};
  return window.NAV2D;
};

const getCanvas = () => {
  const nav2d = getNav2D();
  return nav2d?.canvas || null;
};

const getScene = () => {
  const canvas = getCanvas();
  return canvas?.scene || null;
};

const Map = forwardRef(
  ({ onContextGoal, onContextSavePose, onContextSetPose,
    drawingArea = false, areaDrawType = "keepout", areaWallWidth = 0.1,
    areaPreview = null,
    onAreaDraw }, ref) => {
    const { t } = useT();
    const ros = useRos();

    const mapContainer = useRef(null);
    const mapItem = useRef(null);
    const areaPreviewOverlay = useRef(null);

    const viewerRef = useRef(null);
    const onAreaDrawRef = useRef(onAreaDraw);
    onAreaDrawRef.current = onAreaDraw;

    const [canvasWidth, setCanvasWidth] = useState(undefined);
    const [canvasHeight, setCanvasHeight] = useState(undefined);
    const [isPanning, setIsPanning] = useState(false);

    // eslint-disable-next-line no-unused-vars
    const [mapPoints, updateMapPoints] = useState(0);

    // ROS topic 引用（ROSLIB 可用后再延迟创建）。
    const mapTopicRef = useRef(null);
    const mapUpdateTopicRef = useRef(null);

    // 初始化重试定时器（会自动清理）。
    const initRetryIntervalRef = useRef(null);

    useImperativeHandle(ref, () => ({
      getMapRef: () => mapItem.current,
    }));

    /**
     * ROSLIB 可用后再延迟创建 ROSLIB topic。
     */
    useEffect(() => {
      if (typeof window === "undefined") return;
      if (!window.ROSLIB) return;
      if (!ros) return;

      if (!mapTopicRef.current) {
        mapTopicRef.current = new window.ROSLIB.Topic({
          ros,
          name: AppConfig.WP_REQ,
          messageType: "std_msgs/Empty",
        });
      }

      if (!mapUpdateTopicRef.current) {
        mapUpdateTopicRef.current = new window.ROSLIB.Topic({
          ros,
          name: AppConfig.MAP_TOPIC,
          messageType: "nav_msgs/OccupancyGrid",
        });
      }

      // ROS 连接激活后立即发布 waypoint 请求。
      if (
        mapTopicRef.current &&
        typeof mapTopicRef.current.publish === "function"
      ) {
        mapTopicRef.current.publish();
      }
    }, [ros]);

    /**
     * 仅在容器为空时创建 ROS2D.Viewer。
     */
    const createCanvasContainer = useCallback(() => {
      if (typeof window === "undefined") return;

      const nav2d = ensureNav2D();
      if (!nav2d) return;

      if (!mapItem.current || !mapContainer.current) return;

      const mapElements = mapItem.current.childNodes;

      // 若 canvas 已存在，则不执行操作。
      if (mapElements && mapElements.length >= 1) {
        if (!nav2d.canvas && viewerRef.current) {
          nav2d.canvas = viewerRef.current;
        }
        return;
      }

      const container = mapContainer.current;
      const containerWidth = container.offsetWidth;
      const containerHeight = container.offsetHeight;

      if (!containerWidth || !containerHeight) return;

      const maxCanvasHeight = containerHeight;

      let calculatedCanvasWidth = maxCanvasHeight / 0.7;
      let calculatedCanvasHeight;

      if (calculatedCanvasWidth > containerWidth) {
        calculatedCanvasWidth = containerWidth;
        calculatedCanvasHeight = calculatedCanvasWidth * 0.7;
      } else {
        calculatedCanvasHeight = maxCanvasHeight;
      }

      setCanvasWidth(calculatedCanvasWidth);
      setCanvasHeight(calculatedCanvasHeight);

      if (!window.ROS2D || !window.ROS2D.Viewer) return;

      const viewer = new window.ROS2D.Viewer({
        divID: "nav_div",
        width: calculatedCanvasWidth,
        height: calculatedCanvasHeight,
      });

      viewerRef.current = viewer;
      nav2d.canvas = viewer;

      if (window.createjs?.Touch) {
        window.createjs.Touch.enable(viewer.scene);
      }
    }, []);

    /**
     * topic 存在后再订阅中继地图的更新。
     */
    useEffect(() => {
      const topic = mapUpdateTopicRef.current;
      if (!topic) return;

      const handler = () => {
        updateMapPoints((prev) => prev + 1);
      };

      topic.subscribe(handler);

      return () => {
        topic.unsubscribe(handler);
      };
    }, [mapUpdateTopicRef.current]);

    /**
     * 挂载时创建 canvas 容器。
     */
    useEffect(() => {
      createCanvasContainer();
    }, [createCanvasContainer]);

    /**
     * 初始化 NAV2D 地图逻辑。
     * 持续重试，直到 canvas.scene 存在，然后只初始化一次。
     */
    useEffect(() => {
      if (typeof window === "undefined") return;
      if (!ros) return;

      const nav2d = ensureNav2D();
      if (!nav2d) return;

      createCanvasContainer();

      if (initRetryIntervalRef.current) {
        clearInterval(initRetryIntervalRef.current);
        initRetryIntervalRef.current = null;
      }

      const tryInit = () => {
        const scene = getScene();
        if (typeof nav2d.InitMap !== "function") return;
        if (!scene) return;

        nav2d.InitMap(ros);

        if (initRetryIntervalRef.current) {
          clearInterval(initRetryIntervalRef.current);
          initRetryIntervalRef.current = null;
        }
      };

      tryInit();
      initRetryIntervalRef.current = setInterval(tryInit, 200);

      return () => {
        if (initRetryIntervalRef.current) {
          clearInterval(initRetryIntervalRef.current);
          initRetryIntervalRef.current = null;
        }
        // Map 重新挂载（例如页面切换后）时允许再次运行 navigator()。
        if (window.NAV2D) {
          window.NAV2D.mapInited = false;
          if (window.NAV2D.scanTopic) {
            try {
              window.NAV2D.scanTopic.unsubscribe();
            } catch (e) {}
            window.NAV2D.scanTopic = null;
          }
        }
      };
    }, [ros, createCanvasContainer]);

    const zoomMap = useCallback(
      (direction) => {
        if (typeof window === "undefined") return;
        if (!window.ROS2D || !window.ROS2D.ZoomView) return;

        const scene = getScene();
        if (!scene) return;

        const zoomView = new window.ROS2D.ZoomView({
          ros,
          rootObject: scene,
        });

        // ZoomView.zoom(factor) 会将当前比例（由上一行的 startZoom() 获取）乘以 factor。因此直接传入调用方的 ±1
        // 会变成无操作（zoom(1)）或负比例反转（zoom(-1)）。方向参数仅表示步进符号；在此转换为实际乘数。
        const ZOOM_STEP = 1.15;
        const canvas = scene.canvas;
        zoomView.startZoom(canvas.width / 2, canvas.height / 2);
        zoomView.zoom(direction > 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
        // Saved and queued waypoint arrows live in map coordinates but should
        // keep a readable screen size. Refresh all scale-dependent overlays
        // after the scene zoom changes.
        window.NAV2D?.checkScale?.();
      },
      [ros],
    );

    const shiftMap = (x, y) => {
      const canvas = getCanvas();
      if (!canvas || typeof canvas.shift !== "function") return;
      canvas.shift(x, y);
    };

    /**
     * 左键拖动平移地图，滚轮和双指捏合继续缩放。
     */
    useEffect(() => {
      const container = mapContainer.current;
      if (!container) return undefined;

      const onWheel = (event) => {
        event.preventDefault();
        zoomMap(event.deltaY < 0 ? 1 : -1);
      };

      // 使用普通对象而不是 `new Map()`：本文件中的组件也名为 Map，会在模块作用域遮蔽全局 Map 构造函数，
      // 因此此处的 `new Map()` 会尝试创建该组件。
      const activePointers = {};
      let lastPinchDistance = null;
      let panGesture = null;
      const PINCH_STEP_PX = 18; // px of pinch travel per discrete zoom step

      const pinchDistance = () => {
        const pts = Object.values(activePointers);
        if (pts.length < 2) return null;
        return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      };

      const onPointerDown = (event) => {
        activePointers[event.pointerId] = {
          x: event.clientX,
          y: event.clientY,
        };

        const scene = getScene();
        if (
          event.pointerType === "mouse" &&
          event.button === 0 &&
          event.target === scene?.canvas &&
          !window.NAV2D?.arePointsSettable &&
          !drawingArea
        ) {
          panGesture = {
            pointerId: event.pointerId,
            lastX: event.clientX,
            lastY: event.clientY,
            moved: false,
          };
          try {
            event.target.setPointerCapture(event.pointerId);
          } catch (error) {
            // Pointer capture is optional; dragging still works inside the map.
          }
        }
        if (Object.keys(activePointers).length === 2)
          lastPinchDistance = pinchDistance();
      };
      const onPointerMove = (event) => {
        if (!(event.pointerId in activePointers)) return;
        activePointers[event.pointerId] = {
          x: event.clientX,
          y: event.clientY,
        };
        if (Object.keys(activePointers).length === 2) {
          if (panGesture) {
            panGesture = null;
            setIsPanning(false);
          }

          const distance = pinchDistance();
          if (lastPinchDistance == null || distance == null) {
            lastPinchDistance = distance;
            return;
          }
          const delta = distance - lastPinchDistance;
          if (Math.abs(delta) > PINCH_STEP_PX) {
            zoomMap(delta > 0 ? 1 : -1);
            lastPinchDistance = distance;
          }
          return;
        }

        if (panGesture?.pointerId === event.pointerId) {
          const dx = event.clientX - panGesture.lastX;
          const dy = event.clientY - panGesture.lastY;
          if (!panGesture.moved && Math.hypot(dx, dy) >= 3) {
            panGesture.moved = true;
            setIsPanning(true);
          }

          if (panGesture.moved) {
            const scene = getScene();
            const canvas = scene?.canvas;
            const rect = canvas?.getBoundingClientRect?.();
            if (scene && rect?.width && rect?.height) {
              const scaleX = scene.scaleX || 1;
              const scaleY = scene.scaleY || 1;
              const canvasDx = (dx * canvas.width) / rect.width;
              const canvasDy = (dy * canvas.height) / rect.height;
              shiftMap(-canvasDx / scaleX, canvasDy / scaleY);
              event.preventDefault();
            }
          }

          panGesture.lastX = event.clientX;
          panGesture.lastY = event.clientY;
        }
      };
      const onPointerEnd = (event) => {
        if (panGesture?.pointerId === event.pointerId) {
          panGesture = null;
          setIsPanning(false);
        }
        delete activePointers[event.pointerId];
        if (Object.keys(activePointers).length < 2) lastPinchDistance = null;
      };

      container.addEventListener("wheel", onWheel, { passive: false });
      container.addEventListener("pointerdown", onPointerDown);
      container.addEventListener("pointermove", onPointerMove);
      container.addEventListener("pointerup", onPointerEnd);
      container.addEventListener("pointercancel", onPointerEnd);

      return () => {
        container.removeEventListener("wheel", onWheel);
        container.removeEventListener("pointerdown", onPointerDown);
        container.removeEventListener("pointermove", onPointerMove);
        container.removeEventListener("pointerup", onPointerEnd);
        container.removeEventListener("pointercancel", onPointerEnd);
      };
    }, [zoomMap, drawingArea]);

    useEffect(() => {
      if (!drawingArea) return undefined;
      let attachedCanvas = null;
      let activePointer = null;
      let start = null;
      let preview = null;

      const clearPreview = () => {
        if (preview?.parent) preview.parent.removeChild(preview);
        preview = null;
        start = null;
        activePointer = null;
      };
      const pointOnMap = (event) => {
        const scene = viewerRef.current?.scene;
        const canvas = scene?.canvas;
        const rect = canvas?.getBoundingClientRect();
        if (!scene || !rect?.width || !rect?.height) return null;
        const stageX = ((event.clientX - rect.left) / rect.width) * canvas.width;
        const stageY = ((event.clientY - rect.top) / rect.height) * canvas.height;
        return scene.globalToRos(stageX, stageY);
      };
      const onPointerDown = (event) => {
        if (event.button !== 0 || (event.pointerType !== "mouse" && event.pointerType !== "pen")) return;
        const point = pointOnMap(event);
        const scene = viewerRef.current?.scene;
        if (!point || !scene) return;
        event.preventDefault();
        event.stopPropagation();
        clearPreview();
        activePointer = event.pointerId;
        start = point;
        preview = new window.createjs.Shape();
        preview.mouseEnabled = false;
        scene.addChild(preview);
        try {
          event.currentTarget.setPointerCapture?.(event.pointerId);
        } catch {
          // Drawing continues while the pointer remains inside the canvas.
        }
      };
      const onPointerMove = (event) => {
        if (event.pointerId !== activePointer || !start || !preview) return;
        const point = pointOnMap(event);
        if (!point) return;
        event.preventDefault();
        const graphics = preview.graphics;
        graphics.clear();
        if (areaDrawType === "wall") {
          graphics.beginStroke("#a855f7")
            .setStrokeStyle(Math.max(0.04, areaWallWidth))
            .moveTo(start.x, -start.y).lineTo(point.x, -point.y);
        } else {
          const { fill, stroke } = areaRuleColors({ type: areaDrawType });
          graphics.beginFill(fill).beginStroke(stroke).setStrokeStyle(0.04)
            .drawRect(Math.min(start.x, point.x), -Math.max(start.y, point.y),
              Math.abs(point.x - start.x), Math.abs(point.y - start.y));
        }
      };
      const onPointerUp = (event) => {
        if (event.pointerId !== activePointer || !start) return;
        event.preventDefault();
        event.stopPropagation();
        const point = pointOnMap(event);
        if (point) {
          const dx = point.x - start.x;
          const dy = point.y - start.y;
          const valid = areaDrawType === "wall"
            ? Math.hypot(dx, dy) >= 0.05
            : Math.abs(dx) >= 0.05 && Math.abs(dy) >= 0.05;
          const geometry = areaDrawType === "wall"
            ? { x1: start.x, y1: start.y, x2: point.x, y2: point.y,
                width: areaWallWidth }
            : { cx: (start.x + point.x) / 2, cy: (start.y + point.y) / 2,
                w: Math.abs(dx), h: Math.abs(dy) };
          onAreaDrawRef.current?.(valid ? geometry : null);
        }
        clearPreview();
      };
      const onPointerCancel = (event) => {
        if (event.pointerId === activePointer) clearPreview();
      };
      const attach = () => {
        const canvas = viewerRef.current?.scene?.canvas;
        if (!canvas || canvas === attachedCanvas) return;
        if (attachedCanvas) {
          attachedCanvas.removeEventListener("pointerdown", onPointerDown);
          attachedCanvas.removeEventListener("pointermove", onPointerMove);
          attachedCanvas.removeEventListener("pointerup", onPointerUp);
          attachedCanvas.removeEventListener("pointercancel", onPointerCancel);
        }
        attachedCanvas = canvas;
        canvas.addEventListener("pointerdown", onPointerDown);
        canvas.addEventListener("pointermove", onPointerMove);
        canvas.addEventListener("pointerup", onPointerUp);
        canvas.addEventListener("pointercancel", onPointerCancel);
      };
      attach();
      const pollId = window.setInterval(attach, 200);
      return () => {
        window.clearInterval(pollId);
        clearPreview();
        if (attachedCanvas) {
          attachedCanvas.removeEventListener("pointerdown", onPointerDown);
          attachedCanvas.removeEventListener("pointermove", onPointerMove);
          attachedCanvas.removeEventListener("pointerup", onPointerUp);
          attachedCanvas.removeEventListener("pointercancel", onPointerCancel);
        }
      };
    }, [drawingArea, areaDrawType, areaWallWidth]);

    // Keep the draft above the canvas. The robot map client redraws its
    // CreateJS children as live map and rule messages arrive.
    useEffect(() => {
      const overlay = areaPreviewOverlay.current;
      if (!areaPreview || !overlay) return undefined;
      const shape = overlay.firstElementChild;
      let lastGeometry = "";
      const update = () => {
        const scene = viewerRef.current?.scene;
        const canvas = scene?.canvas;
        if (!scene?.localToGlobal || !canvas || !shape) {
          overlay.style.visibility = "hidden";
          return;
        }
        const canvasRect = canvas.getBoundingClientRect();
        const overlayRect = overlay.getBoundingClientRect();
        if (!canvasRect.width || !canvasRect.height || !overlayRect.width || !overlayRect.height) {
          overlay.style.visibility = "hidden";
          return;
        }
        const toScreen = (x, y) => {
          const point = scene.localToGlobal(x, -y);
          return {
            x: canvasRect.left - overlayRect.left + point.x * canvasRect.width / canvas.width,
            y: canvasRect.top - overlayRect.top + point.y * canvasRect.height / canvas.height,
          };
        };
        const bounds = areaPreview.type === "wall"
          ? [toScreen(areaPreview.x1, areaPreview.y1), toScreen(areaPreview.x2, areaPreview.y2)]
          : [
              toScreen(areaPreview.cx - areaPreview.w / 2, areaPreview.cy + areaPreview.h / 2),
              toScreen(areaPreview.cx + areaPreview.w / 2, areaPreview.cy - areaPreview.h / 2),
            ];
        const [start, end] = bounds;
        const geometry = areaPreview.type === "wall"
          ? [start.x, start.y, end.x, end.y,
              Math.max(2, Number(areaPreview.width) * Math.abs(scene.scaleX || 1) * canvasRect.width / canvas.width)]
          : [Math.min(start.x, end.x), Math.min(start.y, end.y),
              Math.abs(end.x - start.x), Math.abs(end.y - start.y)];
        const nextGeometry = geometry.join(",");
        if (nextGeometry !== lastGeometry) {
          const names = areaPreview.type === "wall"
            ? ["x1", "y1", "x2", "y2", "stroke-width"]
            : ["x", "y", "width", "height"];
          names.forEach((name, index) => shape.setAttribute(name, geometry[index]));
          lastGeometry = nextGeometry;
        }
        overlay.style.visibility = "visible";
      };
      update();
      const interval = window.setInterval(update, 50);
      return () => {
        window.clearInterval(interval);
      };
    }, [areaPreview]);

    /**
     * 全屏模式：canvas 的像素宽高在构造时固定（ROS2D.Viewer 不会自动调整），因此进入/退出全屏时需要直接调整
     * canvas 元素和 viewer 实例字段，然后重新触发 map client 自带的 "change" 事件。此操作会复用 nav2d.js
     * 每次地图更新时已有的重绘/缩放逻辑，避免在此重复实现。
     */
    const [isFullscreen, setIsFullscreen] = useState(false);

    const resizeMapCanvas = useCallback(
      (newWidth, newHeight, notifyMapClient = true) => {
        const viewer = viewerRef.current;
        if (!viewer || !viewer.scene || !viewer.scene.canvas) return false;
        if (
          Math.abs(viewer.width - newWidth) < 1 &&
          Math.abs(viewer.height - newHeight) < 1
        ) {
          return false;
        }
        viewer.scene.canvas.width = newWidth;
        viewer.scene.canvas.height = newHeight;
        viewer.width = newWidth;
        viewer.height = newHeight;
        setCanvasWidth(newWidth);
        setCanvasHeight(newHeight);
        if (notifyMapClient) window.NAV2D?.mapClient?.emit?.("change");
        return true;
      },
      [],
    );

    const fitCanvasToMap = useCallback(
      (mapWidth, mapHeight) => {
        const container = mapContainer.current;
        if (!container || mapWidth <= 0 || mapHeight <= 0) return;

        const availableWidth = container.clientWidth - 16;
        const availableHeight = container.clientHeight - 16;
        if (availableWidth <= 0 || availableHeight <= 0) return;

        const aspectRatio = mapWidth / mapHeight;
        const width = Math.round(
          Math.min(availableWidth, availableHeight * aspectRatio),
        );
        const height = Math.round(width / aspectRatio);
        if (resizeMapCanvas(width, height, false)) {
          const viewer = viewerRef.current;
          if (viewer?.scene) {
            viewer.scene.x = 0;
            viewer.scene.y = viewer.height;
            delete viewer.scene.x_prev_shift;
            delete viewer.scene.y_prev_shift;
            // A canvas resize needs one fresh map fit; ordinary map updates
            // must keep the user's current pan and zoom.
            if (window.NAV2D) window.NAV2D.mapViewGeometry = null;
          }
        }
      },
      [resizeMapCanvas],
    );

    useEffect(() => {
      const nav2d = ensureNav2D();
      if (!nav2d) return undefined;

      nav2d.fitCanvasToMap = fitCanvasToMap;
      return () => {
        if (window.NAV2D?.fitCanvasToMap === fitCanvasToMap) {
          delete window.NAV2D.fitCanvasToMap;
        }
      };
    }, [fitCanvasToMap]);

    const toggleFullscreen = useCallback(() => {
      const container = mapContainer.current;
      if (!container) return;
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        container.requestFullscreen?.();
      }
    }, []);

    useEffect(() => {
      const onFullscreenChange = () => {
        setIsFullscreen(Boolean(document.fullscreenElement));
        requestAnimationFrame(() => {
          const container = mapContainer.current;
          if (!container) return;
          const w = container.clientWidth;
          const h = container.clientHeight;
          if (!w || !h) return;

          const grid = window.NAV2D?.mapClient?.currentGrid;
          if (grid?.width > 0 && grid?.height > 0) {
            fitCanvasToMap(grid.width, grid.height);
            window.NAV2D?.mapClient?.emit?.("change");
          } else {
            let newWidth = h / 0.7;
            let newHeight;
            if (newWidth > w) {
              newWidth = w;
              newHeight = newWidth * 0.7;
            } else {
              newHeight = h;
            }
            resizeMapCanvas(newWidth, newHeight);
          }
        });
      };
      document.addEventListener("fullscreenchange", onFullscreenChange);
      return () =>
        document.removeEventListener("fullscreenchange", onFullscreenChange);
    }, [fitCanvasToMap, resizeMapCanvas]);

    /**
     * 可选的右键菜单（发送目标 / 保存 waypoint / 在此设置位姿）。只有父页面至少传入一个 handler 时才会启用，
     * 因此未接入这些操作的页面（Control、Routes）仍保留浏览器原有的右键菜单。通过 ref 读取 handler，
     * 避免它们每次渲染时身份变化导致监听器反复移除和注册。
     */
    const onContextGoalRef = useRef(onContextGoal);
    const onContextSavePoseRef = useRef(onContextSavePose);
    const onContextSetPoseRef = useRef(onContextSetPose);
    useEffect(() => {
      onContextGoalRef.current = onContextGoal;
      onContextSavePoseRef.current = onContextSavePose;
      onContextSetPoseRef.current = onContextSetPose;
    });

    const [contextMenu, setContextMenu] = useState(null);
    const [waypointName, setWaypointName] = useState("");
    const contextMenuRef = useRef(null);

    const hasContextMenuHandler = Boolean(
      onContextGoal || onContextSavePose || onContextSetPose,
    );

    useEffect(() => {
      if (!hasContextMenuHandler) return undefined;

      let attachedCanvas = null;

      const handleContextMenu = (event) => {
        event.preventDefault();
        const scene = getScene();
        if (!scene) return;

        const rect = event.currentTarget.getBoundingClientRect();
        const stageX =
          ((event.clientX - rect.left) / rect.width) *
          event.currentTarget.width;
        const stageY =
          ((event.clientY - rect.top) / rect.height) *
          event.currentTarget.height;
        const world = scene.globalToRos(stageX, stageY);

        setWaypointName("");
        setContextMenu({
          clientX: event.clientX,
          clientY: event.clientY,
          naming: false,
          pose: {
            position: { x: world.x, y: world.y, z: 0 },
            orientation: { x: 0, y: 0, z: 0, w: 1 },
          },
        });
      };

      const tryAttach = () => {
        const scene = getScene();
        const canvasEl = scene?.canvas;
        if (!canvasEl || attachedCanvas === canvasEl) return;
        if (attachedCanvas)
          attachedCanvas.removeEventListener("contextmenu", handleContextMenu);
        attachedCanvas = canvasEl;
        attachedCanvas.addEventListener("contextmenu", handleContextMenu);
      };

      tryAttach();
      const pollId = setInterval(tryAttach, 300);

      return () => {
        clearInterval(pollId);
        if (attachedCanvas)
          attachedCanvas.removeEventListener("contextmenu", handleContextMenu);
      };
    }, [hasContextMenuHandler]);

    // 点击菜单外部时关闭菜单。
    useEffect(() => {
      if (!contextMenu) return undefined;
      const onDocClick = (event) => {
        if (contextMenuRef.current?.contains(event.target)) return;
        setContextMenu(null);
      };
      const id = setTimeout(
        () => document.addEventListener("click", onDocClick),
        0,
      );
      return () => {
        clearTimeout(id);
        document.removeEventListener("click", onDocClick);
      };
    }, [contextMenu]);

    const confirmSaveWaypoint = () => {
      const trimmed = waypointName.trim();
      if (!trimmed || !contextMenu) return;
      onContextSavePoseRef.current?.(trimmed, contextMenu.pose);
      setContextMenu(null);
      setWaypointName("");
    };

    return (
      <div
        ref={mapContainer}
        className={`dashboard-card dashboard-card--recessed flex h-full w-full items-center justify-center overflow-hidden p-2 ${
          isPanning ? "map-is-panning" : ""
        }`}
        style={{ cursor: drawingArea ? "crosshair" : undefined }}
      >
        <div
          className="relative"
          style={{
            width: canvasWidth ? `${canvasWidth}px` : undefined,
            height: canvasHeight ? `${canvasHeight}px` : undefined,
          }}
        >
          <div className="flex h-full w-full items-center justify-center">
            <div
              id="nav_div"
              ref={mapItem}
              className="mapContainer h-full w-full text-center text-[0px]"
            />
          </div>

          {areaPreview && (
            <svg
              ref={areaPreviewOverlay}
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 z-[5] h-full w-full overflow-visible"
            >
              {areaPreview.type === "wall" ? (
                <line stroke="#a855f7" strokeLinecap="round" />
              ) : (
                <rect
                  fill={areaRuleColors(areaPreview).fill}
                  stroke={areaRuleColors(areaPreview).stroke}
                  strokeWidth="2"
                />
              )}
            </svg>
          )}

          <div className="absolute right-3 top-3 z-10">
            <IconButton
              label={t(isFullscreen ? "Exit fullscreen" : "Fullscreen")}
              onClick={toggleFullscreen}
              className="bg-bgCard/85 backdrop-blur"
            >
              {isFullscreen ? "✕" : "⤢"}
            </IconButton>
          </div>

          {contextMenu && (
            <div
              ref={contextMenuRef}
              className="fixed z-50 min-w-[190px] rounded-xl border border-borderSubtle bg-bgCard/95 p-1.5 font-[RobotoMono] shadow-2xl shadow-black/50 backdrop-blur"
              style={{ left: contextMenu.clientX, top: contextMenu.clientY }}
            >
              {contextMenu.naming ? (
                <div className="p-1">
                  <input
                    autoFocus
                    type="text"
                    value={waypointName}
                    onChange={(e) => setWaypointName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") confirmSaveWaypoint();
                      if (e.key === "Escape") setContextMenu(null);
                    }}
                    placeholder={t("Waypoint name")}
                    className="w-full rounded-lg border border-borderSubtle bg-bgSurface px-2 py-1.5 text-xs text-textWhiteHover placeholder:text-themeTextGray"
                  />
                  <div className="mt-1.5 flex gap-1.5">
                    <button
                      onClick={confirmSaveWaypoint}
                      className="flex-1 rounded-lg border border-themeBlue px-2 py-1 text-xs font-semibold text-themeBlue hover:bg-themeBlue hover:text-white"
                    >
                      <T>{"Save"}</T>{" "}
                    </button>
                    <button
                      onClick={() => setContextMenu(null)}
                      className="flex-1 rounded-lg border border-borderSubtle px-2 py-1 text-xs text-themeTextGray hover:border-statusRed/40 hover:text-statusRed"
                    >
                      <T>{"Cancel"}</T>{" "}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col">
                  {onContextGoal && (
                    <button
                      onClick={() => {
                        onContextGoalRef.current?.(contextMenu.pose);
                        setContextMenu(null);
                      }}
                      className="rounded-lg px-3 py-2 text-left text-xs text-textWhiteHover hover:bg-bgSurface"
                    >
                      <T>{"Send goal here"}</T>{" "}
                    </button>
                  )}
                  {onContextSavePose && (
                    <button
                      onClick={() =>
                        setContextMenu((prev) => ({ ...prev, naming: true }))
                      }
                      className="rounded-lg px-3 py-2 text-left text-xs text-textWhiteHover hover:bg-bgSurface"
                    >
                      <T>{"Save waypoint here"}</T>{" "}
                    </button>
                  )}
                  {onContextSetPose && (
                    <button
                      onClick={() => {
                        onContextSetPoseRef.current?.(contextMenu.pose);
                        setContextMenu(null);
                      }}
                      className="rounded-lg px-3 py-2 text-left text-xs text-textWhiteHover hover:bg-bgSurface"
                    >
                      <T>{"Correct robot's position here"}</T>{" "}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  },
);

export default Map;

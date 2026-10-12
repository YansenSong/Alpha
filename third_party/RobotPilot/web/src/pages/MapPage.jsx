import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useContext,
} from "react";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import { AuthContext, useRos, useRosStatus, useRuntimeConfig } from "../app/App";
import { useRoleAccess } from "../shared/auth/roleAccess";
import { AppConfig } from "../shared/constants";

import Map from "../components/Map";
import Camera from "../components/Camera";
import Joystick from "../components/Joystick";
import RobotState from "../components/RobotState";
import { MetricCard } from "../shared/ui/Dashboard";
import NavStatus from "../components/NavStatus";
import MapLayers from "../components/MapLayers";
import SystemAlerts from "../components/SystemAlerts";
import WaypointLibrary from "../components/WaypointLibrary";
import SavedInspectionMissionsCard from "../features/inspection-planning/SavedInspectionMissionsCard";
import useSavedWaypoints from "../shared/hooks/useSavedWaypoints";
import useKeepoutZones from "../shared/hooks/useKeepoutZones";
import { addEvent } from "../shared/events/eventLog";
import { INSPECTION_PROFILE } from "../shared/robot/robotContract";
import { useT, T } from "../shared/i18n/i18n";
import useSoftwareStop from "../shared/hooks/useSoftwareStop";
import useMissionRun from "../shared/hooks/useMissionRun";
import useRobotStatus from "../shared/hooks/useRobotStatus";
import { startOneOffMission } from "../shared/missions/taskApi";
import { apiFetch } from "../shared/api/apiFetch";

const INITIAL_POSE_COV = [
  0.25, 0, 0, 0, 0, 0, 0, 0.25, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
  0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0685,
];

const MapPage = () => {
  const ros = useRos();
  const rosStatus = useRosStatus();
  const { config } = useRuntimeConfig();
  const { robotId, robotMode } = useContext(AuthContext);
  const activeMission = useMissionRun();
  const robotStatus = useRobotStatus();
  const missionIsActive = [activeMission?.status, robotStatus.snapshot?.task?.status]
    .filter(Boolean)
    .some((status) => ["running", "paused"].includes(String(status).toLowerCase()));
  const { t } = useT();
  const navigationAccess = useRoleAccess("Operator");
  const localizationAccess = useRoleAccess("Engineer");
  const waypointAccess = useRoleAccess("Engineer");
  const manualAccess = useRoleAccess("Engineer");
  const navigationAccessRef = useRef(navigationAccess);
  navigationAccessRef.current = navigationAccess;
  const localizationAccessRef = useRef(localizationAccess);
  localizationAccessRef.current = localizationAccess;
  const softwareStop = useSoftwareStop();
  const manualDisabledReason =
    robotMode !== "simulation"
      ? t("Manual control is available in simulation mode only.")
      : rosStatus !== "connected"
        ? t("Robot connection is offline!")
        : !manualAccess.allowed
          ? t(manualAccess.reason)
          : !softwareStop.stateFresh || softwareStop.robotState?.active !== false
            ? t("Software stop state is unknown or active.")
            : ["pending", "unknown"].includes(softwareStop.requestState?.status)
              ? t("Software stop request is pending.")
              : missionIsActive
                ? t("Stop the active task before manual control.")
                : "";
  const manualEnabled = !INSPECTION_PROFILE && !manualDisabledReason;
  const softwareStopRef = useRef(softwareStop);
  softwareStopRef.current = softwareStop;
  const navigationSafetyReady = () => {
    const state = softwareStopRef.current;
    return (
      state.stateFresh &&
      navigationAccessRef.current.allowed &&
      !state.robotState?.active &&
      !["pending", "unknown"].includes(state.requestState?.status)
    );
  };
  const mapRef = useRef(null);
  const [businessAlerts, setBusinessAlerts] = useState([]);
  const alertMapId = robotStatus.snapshot?.current_map?.map_id || "";
  const alertMapVersionId = robotStatus.snapshot?.current_map?.map_version_id || "";
  const displayedMapIdentity = `${alertMapId}:${alertMapVersionId}`;
  const displayedMapIdentityRef = useRef(displayedMapIdentity);

  useEffect(() => {
    if (!INSPECTION_PROFILE) return undefined;
    if (!alertMapId || !alertMapVersionId || robotStatus.stale) {
      setBusinessAlerts([]);
      window.NAV2D?.setInspectionAlerts?.([]);
      return undefined;
    }
    let active = true;
    const refresh = async () => {
      const query = new URLSearchParams({ map_id: alertMapId, map_version_id: alertMapVersionId });
      try {
        const response = await apiFetch(
          `/api/v1/robots/${encodeURIComponent(robotId || "")}/inspection/alerts?${query}`,
        );
        const payload = await response.json();
        if (active) {
          const nextAlerts = payload.alerts || [];
          setBusinessAlerts(nextAlerts);
          window.NAV2D?.setInspectionAlerts?.(nextAlerts);
        }
      } catch {
        // Keep the last version-matched pins visible while the alert API is unavailable.
      }
    };
    setBusinessAlerts([]);
    window.NAV2D?.setInspectionAlerts?.([]);
    refresh();
    const timer = window.setInterval(refresh, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.NAV2D?.setInspectionAlerts?.([]);
    };
  }, [alertMapId, alertMapVersionId, robotId, robotStatus.stale]);

  useEffect(() => {
    if (!INSPECTION_PROFILE || !window.NAV2D) return undefined;
    window.NAV2D._inspectionAlertClickCallback = (alertId) => {
      window.location.href = `/route?alert_id=${encodeURIComponent(alertId)}#inspection-records`;
    };
    return () => { window.NAV2D._inspectionAlertClickCallback = null; };
  }, []);

  // mode: null | 'goal' | 'pose' | 'waypoint'
  const [mode, setModeState] = useState(null);
  const modeRef = useRef(null);
  const setMode = (m) => {
    modeRef.current = m;
    setModeState(m);
  };

  const [waypointQueue, setWaypointQueueState] = useState([]);
  const waypointQueueRef = useRef([]);
  const setWaypointQueue = (updater) => {
    const next =
      typeof updater === "function"
        ? updater(waypointQueueRef.current)
        : updater;
    waypointQueueRef.current = next;
    setWaypointQueueState(next);
  };

  const [activeWaypointIndex, setActiveWaypointIndex] = useState(-1);
  const [completedWaypointCount, setCompletedWaypointCount] = useState(0);
  useEffect(() => {
    if (displayedMapIdentityRef.current === displayedMapIdentity) return;
    displayedMapIdentityRef.current = displayedMapIdentity;
    setWaypointQueue([]);
    setActiveWaypointIndex(-1);
    setCompletedWaypointCount(0);
    window.NAV2D?.clearPath?.();
    window.NAV2D?.clearGoalPose?.();
  }, [displayedMapIdentity]);

  const {
    waypoints,
    addWaypoint,
    removeWaypoint,
    updateWaypoint,
    mapId: waypointMapId,
    mapVersionId: waypointMapVersionId,
    loading: waypointsLoading,
    error: waypointsError,
    observedAt: waypointsObservedAt,
    stale: waypointsStale,
    legacyWaypoints,
    importLegacyWaypoints,
  } = useSavedWaypoints();
  useKeepoutZones();
  const waypointsRef = useRef(waypoints);
  useEffect(() => {
    waypointsRef.current = waypoints;
  }, [waypoints]);

  // Draw every queued waypoint on the map, not just the single in-flight goal.
  useEffect(() => {
    window.NAV2D?.setQueuedWaypoints?.(waypointQueue, {
      activeIndex: activeWaypointIndex,
      completedCount: completedWaypointCount,
    });
  }, [waypointQueue, activeWaypointIndex, completedWaypointCount]);

  const initialPoseTopic = useRef(null);
  const navCancelService = useRef(null);
  const pendingInitialPoseRef = useRef(false);

  useEffect(() => {
    if (!ros || !window.ROSLIB) return;

    initialPoseTopic.current = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.INITIAL_POSE_TOPIC,
      messageType: "geometry_msgs/PoseWithCovarianceStamped",
    });

    navCancelService.current = new window.ROSLIB.Service({
      ros,
      name: AppConfig.NAV_CANCEL_GOAL_SERVICE,
      serviceType: "action_msgs/CancelGoal",
    });

    const localizationTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.LOCALIZATION_POSE_TOPIC,
      messageType: AppConfig.LOCALIZATION_POSE_TYPE,
    });
    localizationTopic.subscribe(() => {
      if (!pendingInitialPoseRef.current) return;
      pendingInitialPoseRef.current = false;
      toast.success(t("Robot's position estimate updated"));
    });

    return () => localizationTopic.unsubscribe();
  }, [ros]);

  const startManualSteps = useCallback(
    async (steps, name) => {
      if (INSPECTION_PROFILE) return;
      if (missionIsActive) {
        toast.warn(t("Another task is already active."));
        return false;
      }
      if (!navigationSafetyReady()) {
        setActiveWaypointIndex(-1);
        toast.warn(
          t(
            "Cannot send navigation goal while software stop state is unknown or active",
          ),
        );
        return false;
      }
      try {
        const result = await startOneOffMission({
          robotId,
          mapId: waypointMapId,
          mapVersionId: waypointMapVersionId,
          name,
          steps,
        });
        toast.info(
          `${t("Task accepted")}: ${result.task_id || result.command_id}`,
        );
        return true;
      } catch (error) {
        toast.error(error.message || t("Task could not be started"));
        return false;
      }
    },
    [missionIsActive, robotId, waypointMapId, waypointMapVersionId, t],
  );

  const toPoseStep = (pose, waypointName = "") => ({
    type: "waypoint",
    waypointName,
    pose: {
      x: Number(pose.position.x),
      y: Number(pose.position.y),
      z: Number(pose.orientation.z) || 0,
      w: Number(pose.orientation.w ?? 1),
    },
  });

  const goToWaypoint = useCallback(
    (wp) => {
      if (waypointsStale) {
        toast.warn(
          "Robot waypoint snapshot is stale; reconnect before navigation.",
        );
        return;
      }
      const yaw = Number(wp.yaw ?? wp.z) || 0;
      startManualSteps(
        [
          {
            type: "waypoint",
            waypointId: String(wp.waypoint_id || wp.id),
            waypointName: wp.name,
            pose: {
              x: Number(wp.x),
              y: Number(wp.y),
              z: Math.sin(yaw / 2),
              w: Math.cos(yaw / 2),
            },
          },
        ],
        `${t("Navigate to")}: ${wp.name}`,
      );
    },
    [startManualSteps, t, waypointsStale],
  );

  // Map context actions are persisted as one-off MissionManager tasks.
  const sendGoalAt = useCallback(
    (pose) => {
      startManualSteps([toPoseStep(pose)], t("Single navigation"));
    },
    [startManualSteps, t],
  );

  const runRouteMission = useCallback(
    (route, name = t("Manual route")) => {
      if (!route.length) return false;
      const steps = [];
      route.forEach((pose, index) => {
        steps.push(toPoseStep(pose, `${name} ${index + 1}`));
        if (Number(pose.dwellSeconds) > 0) {
          steps.push({ type: "wait", seconds: Number(pose.dwellSeconds) });
        }
      });
      return startManualSteps(steps, `${t("Manual route")}: ${name}`);
    },
    [startManualSteps, t],
  );

  const saveWaypointAt = async (name, pose, pointType = "inspection") => {
    if (!waypointAccess.allowed) {
      toast.warn(t(waypointAccess.reason));
      return false;
    }
    try {
      await addWaypoint(name, pose, pointType);
      toast.success(`${t("Saved on robot")} "${name}"`);
    } catch (error) {
      toast.error(error.message || t("Unable to save waypoint"));
      return false;
    }
  };

  const setInitialPoseAt = (pose) => {
    if (INSPECTION_PROFILE) return;
    if (!localizationAccess.allowed) {
      toast.warn(t(localizationAccess.reason));
      return;
    }
    if (!initialPoseTopic.current) return;
    initialPoseTopic.current.publish(
      new window.ROSLIB.Message({
        header: { frame_id: "map", stamp: { sec: 0, nanosec: 0 } },
        pose: {
          pose: {
            position: { x: pose.position.x, y: pose.position.y, z: 0 },
            orientation: {
              x: 0,
              y: 0,
              z: pose.orientation.z,
              w: pose.orientation.w,
            },
          },
          covariance: INITIAL_POSE_COV,
        },
      }),
    );
    pendingInitialPoseRef.current = true;
    window.NAV2D?.clearTrail?.();
    window.NAV2D?.clearGoalPose?.();
    toast.success(
      `${t("Initial pose set")}: (${pose.position.x.toFixed(
        2,
      )}, ${pose.position.y.toFixed(2)}) m`,
    );
  };

  // Clicking a saved-waypoint pin on the map fires this — set once (not
  // re-registered every render) and reading the latest list via a ref, the
  // same pattern modeRef/waypointQueueRef already use in this file.
  useEffect(() => {
    if (!window.NAV2D) return undefined;
    window.NAV2D._savedWaypointClickCallback = (id) => {
      const wp = waypointsRef.current.find((w) => w.id === id);
      if (wp) goToWaypoint(wp);
    };
    return () => {
      window.NAV2D._savedWaypointClickCallback = null;
    };
  }, [goToWaypoint]);

  const deactivateMode = useCallback(() => {
    if (window.NAV2D) {
      window.NAV2D.arePointsSettable = false;
      window.NAV2D._poseCallback = null;
    }
    setMode(null);
  }, []);

  // Install the direct NAV2D callback — fires synchronously from stagemouseup,
  // no DOM bubbling or setTimeout needed.
  const installCallback = useCallback(() => {
    if (INSPECTION_PROFILE) return;
    if (!window.NAV2D) return;
    window.NAV2D._poseCallback = (pose) => {
      const m = modeRef.current;
      if (m === "goal") {
        sendGoalAt(pose);
      } else if (m === "pose") {
        if (!localizationAccessRef.current.allowed) {
          toast.warn(t(localizationAccessRef.current.reason));
          deactivateMode();
          return;
        }
        if (!initialPoseTopic.current) return;
        initialPoseTopic.current.publish(
          new window.ROSLIB.Message({
            header: { frame_id: "map", stamp: { sec: 0, nanosec: 0 } },
            pose: {
              pose: {
                position: { x: pose.position.x, y: pose.position.y, z: 0 },
                orientation: {
                  x: 0,
                  y: 0,
                  z: pose.orientation.z,
                  w: pose.orientation.w,
                },
              },
              covariance: INITIAL_POSE_COV,
            },
          }),
        );
        pendingInitialPoseRef.current = true;
        if (window.NAV2D?.clearTrail) window.NAV2D.clearTrail();
        window.NAV2D?.clearGoalPose?.();
        toast.success(
          `${t("Initial pose set")}: (${pose.position.x.toFixed(
            2,
          )}, ${pose.position.y.toFixed(2)}) m`,
        );
        deactivateMode();
      } else if (m === "waypoint") {
        window.NAV2D?.clearGoalPose?.();
        const idx = waypointQueueRef.current.length;
        setWaypointQueue((prev) => [...prev, pose]);
        toast.info(`${t("Waypoint")} ${idx + 1} ${t("added")}`);
      }
    };
  }, [deactivateMode, sendGoalAt, t]);

  const activateMode = useCallback(
    (m) => {
      if (INSPECTION_PROFILE) return;
      const access = m === "pose" ? localizationAccess : navigationAccess;
      if (!access.allowed) {
        toast.warn(t(access.reason));
        return;
      }
      if (!window.NAV2D) return;
      window.NAV2D.arePointsSettable = true;
      installCallback();
      setMode(m);
    },
    [installCallback, localizationAccess, navigationAccess, t],
  );

  // Re-install callback whenever mode changes so the closure always has the right mode
  useEffect(() => {
    if (["goal", "pose", "waypoint"].includes(modeRef.current))
      installCallback();
  }, [mode, installCallback]);

  const cancelGoal = useCallback(() => {
    navCancelService.current?.callService(
      new window.ROSLIB.ServiceRequest({
        goal_info: {
          goal_id: { uuid: new Array(16).fill(0) },
          stamp: { sec: 0, nanosec: 0 },
        },
      }),
      () => {},
      () => {},
    );
    window.NAV2D?.clearGoalPose?.();
  }, []);

  const emergencyStop = useCallback(() => {
    setWaypointQueue([]);
    setActiveWaypointIndex(-1);
    setCompletedWaypointCount(0);
    softwareStop.requestStop();
    cancelGoal();
    addEvent({
      type: "safety",
      severity: "warning",
      message:
        "Software stop requested (map page); awaiting robot confirmation",
    });
    toast.warn(t("Software stop requested; waiting for robot confirmation"));
  }, [cancelGoal, softwareStop, t]);

  const sendHome = useCallback(() => {
    if (INSPECTION_PROFILE) return;
    if (!navigationSafetyReady()) {
      toast.warn(
        t(
          "Cannot send navigation goal while software stop state is unknown or active",
        ),
      );
      return;
    }
    startManualSteps([{ type: "home" }], t("Navigate home"));
  }, [startManualSteps, t]);

  const executeQueue = useCallback(() => {
    if (INSPECTION_PROFILE) return;
    if (!waypointQueueRef.current.length) return;
    runRouteMission(waypointQueueRef.current, t("Manual route"));
  }, [runRouteMission, t]);

  const previewInspectionMission = (mission) => {
    const route = (mission.steps || [])
      .filter((step) => step.type === "waypoint" && step.pose)
      .map((step) => ({
        position: { x: Number(step.pose.x), y: Number(step.pose.y), z: 0 },
        orientation: {
          x: 0,
          y: 0,
          z: Number(step.pose.z) || 0,
          w: Number.isFinite(Number(step.pose.w)) ? Number(step.pose.w) : 1,
        },
      }));
    if (!route.length) {
      toast.warn("所选巡检任务没有可预览的航点。");
      return;
    }
    setWaypointQueue(route);
    setActiveWaypointIndex(-1);
    setCompletedWaypointCount(0);
    window.NAV2D?.drawRoutePlan?.(route);
    mapRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (window.NAV2D) {
        window.NAV2D.arePointsSettable = false;
        window.NAV2D._poseCallback = null;
      }
    };
  }, []);

  const modeBtn = (label, shortLabel, m, activeLabel, shortActiveLabel) => {
    const active = mode === m;
    const access = m === "pose" ? localizationAccess : navigationAccess;
    return (
      <button
        onClick={() => (active ? deactivateMode() : activateMode(m))}
        disabled={!access.allowed}
        title={access.allowed ? undefined : t(access.reason)}
        className={`flex min-h-[52px] w-full items-center justify-center rounded-xl border px-2 py-2 text-center font-[RobotoMono] text-[10px] font-semibold leading-tight transition-colors sm:px-3 sm:text-sm ${
          active
            ? "border-themeBlue bg-themeBlue text-white"
            : "border-borderSubtle bg-bgCard text-themeBlue hover:border-themeBlue"
        }`}
      >
        <span className="sm:hidden">
          {t(active ? shortActiveLabel : shortLabel)}
        </span>
        <span className="hidden sm:inline">
          {t(active ? activeLabel : label)}
        </span>
      </button>
    );
  };

  return (
    <>
      <ToastContainer position="bottom-right" theme="dark" />

      <div className="flex min-h-[calc(100vh-145px)] min-w-0 flex-col gap-3 py-3">
        {!INSPECTION_PROFILE && <SystemAlerts />}
        {INSPECTION_PROFILE && (
          <section aria-label="运行总览" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <div className="dashboard-card p-3"><p className="text-xs text-themeTextGray">机器人</p><strong>{robotStatus.snapshot?.robot_connection?.online ? "在线" : "离线/未知"}</strong><p className="text-xs">{robotStatus.stale ? "状态数据已过期" : robotStatus.snapshot?.robot_connection?.source || robotMode}</p></div>
            <div className="dashboard-card p-3"><p className="text-xs text-themeTextGray">任务</p><strong>{robotStatus.snapshot?.task?.status || "空闲/未知"}</strong><p className="text-xs">{robotStatus.snapshot?.task?.taskId || robotStatus.snapshot?.task?.task_id || "无当前任务"}</p>{robotStatus.snapshot?.task?.active_action && <p className="mt-1 text-xs text-themeBlue">{robotStatus.snapshot.task.active_action.kind} · {robotStatus.snapshot.task.active_action.status}</p>}</div>
            <div className="dashboard-card p-3"><p className="text-xs text-themeTextGray">电量</p><strong>{robotStatus.snapshot?.battery?.available && robotStatus.snapshot?.battery?.percent != null ? `${robotStatus.snapshot.battery.percent}%` : "未知"}</strong><p className="text-xs">{robotStatus.snapshot?.battery?.source || "unavailable"}</p></div>
            <div className="dashboard-card p-3"><p className="text-xs text-themeTextGray">地图与安全</p><strong>{robotStatus.snapshot?.current_map?.map_id || "地图未知"}</strong><p className="text-xs">{robotStatus.snapshot?.autonomy_ready ? "安全门禁就绪" : "门禁未确认"}</p></div>
            <div className="dashboard-card p-3"><p className="text-xs text-themeTextGray">地图内业务告警</p><strong>{robotStatus.stale ? "未知" : businessAlerts.filter((item) => item.state !== "CLOSED").length}</strong><p className="truncate text-xs">{robotStatus.stale ? "地图状态过期" : businessAlerts[0]?.category || "暂无当前版本告警"}</p></div>
            <div className="col-span-2 flex items-center justify-between rounded-lg border border-statusYellow/40 bg-statusYellow/5 p-3 text-xs text-statusYellow sm:col-span-5">
              <span>{robotStatus.error || (robotStatus.stale ? "运行状态过期或不可用；卡片不代表实时状态。" : `运行模式：${robotMode || "unknown"}。物理急停状态未由该接口确认。`)}</span>
              <a className="shrink-0 underline" href="/route#inspection-records">查看巡检结果与告警</a>
            </div>
          </section>
        )}
        <MapLayers />

        {/* Keep telemetry in a narrow sidebar beside the map on desktop. */}
        <section
          className={`grid min-w-0 grid-cols-1 gap-3 ${
            INSPECTION_PROFILE
              ? "xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,1fr)]"
              : "xl:grid-cols-[minmax(190px,0.32fr)_minmax(0,1.35fr)_minmax(320px,1fr)]"
          } disabled:cursor-not-allowed disabled:opacity-40`}
        >
          {!INSPECTION_PROFILE && (
            <div className="order-3 flex min-w-0 flex-col gap-3 xl:order-1">
              <NavStatus />
              <RobotState compact showPosition={false} splitVelocityCards />
              <MetricCard
                compact
                label="Distance to target"
                value="—"
                unit="m"
              />
              <RobotState
                compact
                showPosition
                showVelocity={false}
                separateHeading
              />
            </div>
          )}
          <div
            className={`h-[340px] min-w-0 sm:h-[440px] xl:h-[500px] ${
              INSPECTION_PROFILE ? "order-1 xl:order-1" : "order-1 xl:order-2"
            }`}
            data-tour="map-canvas"
          >
            <Map
              ref={mapRef}
              onContextGoal={INSPECTION_PROFILE ? undefined : sendGoalAt}
              onContextSavePose={saveWaypointAt}
              onContextSetPose={
                INSPECTION_PROFILE ? undefined : setInitialPoseAt
              }
            />
          </div>
          <div
            className={`order-2 h-[340px] min-w-0 sm:h-[440px] xl:h-[500px] ${
              INSPECTION_PROFILE ? "xl:order-2" : "xl:order-3"
            }`}
          >
            <Camera />
          </div>
        </section>

        {/* Manual drive and saved waypoints share an aligned responsive grid. */}
        <section
          className="grid min-w-0 grid-cols-1 items-stretch gap-3 sm:grid-cols-2 lg:grid-cols-12"
          data-tour="manual-drive"
        >
          <div className="dashboard-card flex min-h-[176px] min-w-0 flex-col items-center justify-center gap-2 p-3 sm:col-span-1 lg:col-span-3">
            <p className="font-[RobotoMono] text-xs uppercase tracking-wider text-themeTextGray">
              {t("Manual")}
            </p>
            {!INSPECTION_PROFILE ? (
              <Joystick
                maxSpeed={config.maxLinearSpeed}
                compact
                enabled={manualEnabled}
              />
            ) : (
              <p className="text-center text-xs text-themeTextGray">
                {t("Manual control interface not configured")}
              </p>
            )}
            {!INSPECTION_PROFILE && !manualEnabled && (
              <p className="text-center text-xs text-themeTextGray">
                {manualDisabledReason}
              </p>
            )}
            <button
              onClick={emergencyStop}
              disabled={INSPECTION_PROFILE}
              title={
                INSPECTION_PROFILE
                  ? "Software Stop unavailable: robot interface not configured; not physical E-STOP"
                  : "Software stop request; not physical E-STOP"
              }
              className="mt-1 h-9 w-9 shrink-0 rounded-full border-2 border-statusRed bg-statusRed/10 font-[RobotoMono] text-[9px] font-bold leading-none text-statusRed transition-colors hover:bg-statusRed hover:text-white"
            >
              {INSPECTION_PROFILE ? t("Software Stop") : "STOP"}
            </button>
          </div>

          <div className="min-w-0 sm:col-span-2 lg:col-span-5 [&>div]:h-full">
            <WaypointLibrary
              waypoints={waypoints}
              onAdd={saveWaypointAt}
              onGo={INSPECTION_PROFILE ? undefined : goToWaypoint}
              onRemove={removeWaypoint}
              onUpdate={updateWaypoint}
              mapId={waypointMapId}
              loading={waypointsLoading}
              error={waypointsError}
              observedAt={waypointsObservedAt}
              stale={waypointsStale}
              legacyWaypoints={legacyWaypoints}
              onImportLegacy={importLegacyWaypoints}
              inspectionOnly={INSPECTION_PROFILE}
            />
          </div>

          <SavedInspectionMissionsCard
            mapId={alertMapId}
            mapVersionId={alertMapVersionId}
            stale={
              robotStatus.stale ||
              robotStatus.snapshot?.current_map?.stale !== false
            }
            active={missionIsActive}
            onPreview={previewInspectionMission}
          />
          {!INSPECTION_PROFILE && waypointQueue.length > 0 && (
            <div className="dashboard-card min-w-0 space-y-3 p-3 font-[RobotoMono] sm:col-span-2 sm:p-4 lg:col-span-4">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <p className="text-xs uppercase tracking-wider text-themeTextGray">
                      {t("Waypoint Queue")} ({waypointQueue.length})
                    </p>
                    <button
                      onClick={() => {
                        setWaypointQueue([]);
                        setActiveWaypointIndex(-1);
                        setCompletedWaypointCount(0);
                      }}
                      className="text-xs text-statusRed hover:underline"
                    >
                      <T>{"Clear"}</T>
                    </button>
                  </div>
                  <div className="mb-3 flex max-h-36 flex-wrap gap-1.5 overflow-y-auto">
                    {waypointQueue.map((wp, i) => (
                      <span
                        key={i}
                        className={`rounded border px-2 py-0.5 text-xs ${
                          missionIsActive && i === activeMission?.stepIndex
                            ? "border-themeBlue bg-themeBlue/20 text-themeBlue"
                            : "border-borderSubtle text-themeTextGray"
                        }`}
                      >
                        {i + 1}: ({wp.position.x.toFixed(1)},{" "}
                        {wp.position.y.toFixed(1)}) m
                      </span>
                    ))}
                  </div>
                  {!missionIsActive && (
                    <button
                      onClick={executeQueue}
                      className="w-full rounded-lg border border-themeBlue bg-themeBlue/10 py-1.5 text-xs font-semibold text-themeBlue hover:bg-themeBlue hover:text-white"
                    >
                      <T>{"Execute Queue"}</T>
                    </button>
                  )}
            </div>
          )}
        </section>

        {/* Map actions and route execution share a single operations area. */}
        {!INSPECTION_PROFILE && (
          <section className="min-w-0" data-tour="map-actions">
            <div className="dashboard-card flex min-w-0 flex-col justify-center gap-3 p-3 sm:p-4">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {modeBtn(
                  "○ Send Goal",
                  "Goal",
                  "goal",
                  "● Click to Send Goal",
                  "● Goal",
                )}
                {modeBtn(
                  "⊕ Correct Robot's Position",
                  "Fix Position",
                  "pose",
                  "● Click to Correct Position",
                  "● Fixing",
                )}
                {modeBtn(
                  "＋ Add Waypoint",
                  "Waypoint",
                  "waypoint",
                  "● Adding Waypoints",
                  "● Adding",
                )}
                <button
                  onClick={sendHome}
                  className="min-h-[52px] w-full rounded-xl border border-borderSubtle bg-bgCard px-2 py-2 text-center font-[RobotoMono] text-[10px] font-semibold leading-tight text-textWhiteHover transition-colors hover:border-themeBlue hover:text-themeBlue sm:px-3 sm:text-sm"
                >
                  <span className="sm:hidden">
                    <T>{"Home"}</T>
                  </span>
                  <span className="hidden sm:inline">
                    <T>{"⌂ Go Home"}</T>
                  </span>
                </button>
              </div>

              <p className="min-h-5 px-1 font-[RobotoMono] text-xs leading-5 text-themeTextGray">
                {mode === "goal" &&
                  t(
                    "Click map to navigate. Drag before releasing to set heading.",
                  )}
                {mode === "pose" &&
                  t(
                    "Click the map to tell the robot where it currently is. Drag to set heading. One-shot.",
                  )}
                {mode === "waypoint" &&
                  t(
                    "Each click adds a waypoint. Drag to set heading. Execute all below.",
                  )}
                {!mode && t("Select a mode above to interact with the map.")}
              </p>
            </div>
          </section>
        )}
      </div>
    </>
  );
};

export default MapPage;

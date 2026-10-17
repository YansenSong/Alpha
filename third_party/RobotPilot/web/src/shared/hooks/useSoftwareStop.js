import { useCallback, useContext, useEffect, useRef, useState } from "react";

import { AuthContext, useRos, useRosStatus } from "../../app/App";
import { hasRole } from "../auth/roleAccess";
import { AppConfig } from "../constants";
import { sendStoredMissionCommand } from "../missions/taskApi";
import useMissionRun from "./useMissionRun";

const STATE_STALE_MS = 3000;
const ACK_TIMEOUT_MS = 3000;

export const softwareStopCapabilities = (mode, identity) => {
  const operator = hasRole(mode, identity, "Operator");
  return {
    requestStop: operator,
    releaseStop: operator,
  };
};

export const canStartMission = ({ robotState, stateFresh, requestState }) =>
  Boolean(
    stateFresh &&
      robotState?.active === false &&
      !["pending", "unknown"].includes(requestState?.status),
  );

export const isSoftwareStopStateFresh = (state, now = Date.now()) =>
  Boolean(state && now - state.receivedAt <= STATE_STALE_MS);

export const parseSoftwareStopState = (value) => {
  try {
    const state = typeof value === "string" ? JSON.parse(value) : value;
    if (!state || typeof state.active !== "boolean") return null;
    if (
      typeof state.observed_at !== "string" ||
      !Number.isFinite(Date.parse(state.observed_at))
    )
      return null;
    return {
      active: state.active,
      source: typeof state.source === "string" ? state.source : "unknown",
      reason: typeof state.reason === "string" ? state.reason : "",
      request_id: typeof state.request_id === "string" ? state.request_id : "",
      observed_at: state.observed_at,
      result: ["rejected", "degraded"].includes(state.result)
        ? state.result
        : "confirmed",
      durable: state.durable === true,
      physical_estop:
        state.physical_estop &&
        typeof state.physical_estop.available === "boolean"
          ? state.physical_estop
          : { available: false, active: null },
      receivedAt: Date.now(),
    };
  } catch {
    return null;
  }
};

const createRequestId = () =>
  globalThis.crypto?.randomUUID?.() ||
  `software-stop-${Date.now()}-${Math.random().toString(16).slice(2)}`;

// Unknown motion must never hide the stop action. Disable it only when
// fresh telemetry confirms idle and there is no running/paused task.
export const softwareStopNeeded = (run, motion, now = Date.now()) =>
  Boolean(
    ["running", "paused"].includes(run?.status) ||
      !motion || now - motion.receivedAt > 1500 ||
      !motion.stationary || motion.stationarySince == null ||
      now - motion.stationarySince < 500
  );

const useSoftwareStop = () => {
  const ros = useRos();
  const rosStatus = useRosStatus();
  const { mode, identity, robotId = "robot-001" } = useContext(AuthContext);
  const missionRun = useMissionRun();
  const [robotState, setRobotState] = useState(null);
  const [motion, setMotion] = useState(null);
  const motionRef = useRef(null);
  const [requestState, setRequestState] = useState(null);
  const [, setFreshnessTick] = useState(0);
  const requestTopicRef = useRef(null);
  const stopTopicRef = useRef(null);
  const resumeTaskAfterReleaseRef = useRef(null);
  const previousMissionReasonRef = useRef(missionRun?.reason || "");
  const acknowledgementTimerRef = useRef(null);
  const capabilities = softwareStopCapabilities(mode, identity);
  const stopUnavailableReason = !capabilities.requestStop
    ? "Operator permission required"
    : rosStatus !== "connected" ? "ROS bridge offline"
    : robotState?.active ? "Software stop already active"
    : requestState?.status === "pending" ? "Software stop request pending"
    : !softwareStopNeeded(missionRun, motion) ? "No active task and robot is stationary"
    : "";
  const canRequestStop = !stopUnavailableReason;
  const canReleaseStop = capabilities.releaseStop;
  const stateFresh = isSoftwareStopStateFresh(robotState);
  const canResumePausedTask = Boolean(
    missionRun?.status === "paused" && missionRun?.taskId,
  );

  useEffect(() => {
    if (!ros || rosStatus !== "connected" || !window.ROSLIB) {
      motionRef.current = null;
      setMotion(null);
      return undefined;
    }
    const topic = new window.ROSLIB.Topic({
      ros, name: AppConfig.ROBOT_VELOCITY_TOPIC,
      messageType: "nav_msgs/Odometry", throttle_rate: 200,
    });
    const observe = (message) => {
      const twist = message.twist?.twist;
      const values = ["linear", "angular"].flatMap(kind =>
        ["x", "y", "z"].map(axis => twist?.[kind]?.[axis]));
      if (!values.every(Number.isFinite)) {
        motionRef.current = null;
        setMotion(null);
        return;
      }
      const now = Date.now();
      const stationary = Math.hypot(...values.slice(0, 3)) <= 0.01 &&
        Math.hypot(...values.slice(3)) <= 0.01;
      const previous = motionRef.current;
      const next = { receivedAt: now, stationary,
        stationarySince: stationary
          ? previous?.stationary && now - previous.receivedAt <= 1000
            ? previous.stationarySince : now
          : null };
      motionRef.current = next;
      setMotion(next);
    };
    topic.subscribe(observe);
    return () => topic.unsubscribe(observe);
  }, [ros, rosStatus]);

  useEffect(() => {
    if (!motion) return undefined;
    const timer = window.setTimeout(() => setFreshnessTick(value => value + 1),
      Math.max(1, 1501 - (Date.now() - motion.receivedAt)));
    return () => window.clearTimeout(timer);
  }, [motion]);

  const resumeTask = useCallback(
    (taskId, requestId) => {
      sendStoredMissionCommand(robotId, {
        command: "resume",
        task_id: taskId,
      }).catch((error) => {
        setRequestState((current) =>
          current?.requestId === requestId
            ? {
                ...current,
                status: "rejected",
                reason: error.message || "The paused task could not be resumed.",
              }
            : current,
        );
      });
    },
    [robotId],
  );

  useEffect(() => {
    const reason = String(missionRun?.reason || "").toLowerCase();
    const previousReason = previousMissionReasonRef.current;
    previousMissionReasonRef.current = reason;
    if (
      reason === "mission manager restarted; resume required" &&
      previousReason !== reason
    ) {
      // Discard any release request that was in flight before the restart.
      // The operator must click Resume navigation again after reconnection.
      resumeTaskAfterReleaseRef.current = null;
    }
  }, [missionRun?.reason]);

  useEffect(() => {
    if (
      rosStatus !== "connected" ||
      requestState?.action !== "request_release" ||
      requestState.status !== "confirmed" ||
      robotState?.active !== false
    )
      return;
    const taskId = resumeTaskAfterReleaseRef.current;
    if (!taskId) return;
    resumeTaskAfterReleaseRef.current = null;
    resumeTask(taskId, requestState.requestId);
  }, [requestState, robotState?.active, resumeTask, rosStatus]);

  useEffect(() => {
    if (!robotState) return undefined;
    const staleAt = robotState.receivedAt + STATE_STALE_MS + 1;
    const timeout = window.setTimeout(
      () => setFreshnessTick((tick) => tick + 1),
      Math.max(0, staleAt - Date.now()),
    );
    return () => window.clearTimeout(timeout);
  }, [robotState]);

  useEffect(() => {
    if (!ros || rosStatus !== "connected" || !window.ROSLIB) return undefined;
    const requestTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.SOFTWARE_STOP_REQUEST_TOPIC,
      messageType: "std_msgs/String",
    });
    const stateTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.SOFTWARE_STOP_STATE_TOPIC,
      messageType: "std_msgs/String",
    });
    const stopTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.STOP_TOPIC,
      messageType: "std_msgs/Bool",
    });
    requestTopicRef.current = requestTopic;
    stopTopicRef.current = stopTopic;
    const onState = ({ data }) => {
      const nextState = parseSoftwareStopState(data);
      if (!nextState) return;
      setRobotState(nextState);
      setRequestState((current) => {
        if (!current || !["pending", "unknown"].includes(current.status))
          return current;
        const expectedActive = current.action === "request_stop";
        if (nextState.active !== expectedActive) return current;
        if (acknowledgementTimerRef.current) {
          window.clearTimeout(acknowledgementTimerRef.current);
          acknowledgementTimerRef.current = null;
        }
        return {
          ...current,
          status:
            nextState.result === "rejected"
              ? "rejected"
              : nextState.result === "degraded"
              ? "unknown"
              : "confirmed",
          reason: nextState.reason,
        };
      });
    };
    stateTopic.subscribe(onState);

    const stateRequest = JSON.stringify({
      action: "get_state",
      request_id: createRequestId(),
    });
    requestTopic.publish(new window.ROSLIB.Message({ data: stateRequest }));

    return () => {
      stateTopic.unsubscribe(onState);
      requestTopic.unadvertise?.();
      stopTopic.unadvertise?.();
      requestTopicRef.current = null;
      stopTopicRef.current = null;
      if (acknowledgementTimerRef.current) {
        window.clearTimeout(acknowledgementTimerRef.current);
        acknowledgementTimerRef.current = null;
      }
    };
  }, [ros, rosStatus]);

  useEffect(() => {
    if (rosStatus !== "connected") {
      setRobotState(null);
      // A request that did not complete before a disconnect is not fresh
      // confirmation to resume the task after the robot reconnects.
      resumeTaskAfterReleaseRef.current = null;
    }
  }, [rosStatus]);

  const request = useCallback(
    (action) => {
      if (rosStatus !== "connected" || !stopTopicRef.current) {
        if (action === "request_release") {
          resumeTaskAfterReleaseRef.current = null;
        }
        setRequestState({
          action,
          status: "unknown",
          requestId: "",
          reason: "ROS bridge offline",
        });
        return null;
      }
      const requestId = createRequestId();
      setRequestState({
        action,
        status: "pending",
        requestId,
        reason: "",
        fromActive: robotState?.active,
      });
      stopTopicRef.current.publish(
        new window.ROSLIB.Message({ data: action === "request_stop" }),
      );
      if (acknowledgementTimerRef.current)
        window.clearTimeout(acknowledgementTimerRef.current);
      acknowledgementTimerRef.current = window.setTimeout(() => {
        setRequestState((current) =>
          current?.requestId === requestId && current.status === "pending"
            ? { ...current, status: "unknown" }
            : current,
        );
        acknowledgementTimerRef.current = null;
      }, ACK_TIMEOUT_MS);
      return requestId;
    },
    [robotState?.active, rosStatus],
  );

  const requestStop = useCallback(() => {
    if (!canRequestStop) return null;
    return request("request_stop");
  }, [canRequestStop, request]);

  const requestRelease = useCallback(() => {
    if (!canReleaseStop) return null;
    resumeTaskAfterReleaseRef.current = canResumePausedTask
      ? missionRun.taskId
      : null;
    return request("request_release");
  }, [canReleaseStop, canResumePausedTask, missionRun?.taskId, request]);

  return {
    robotState,
    stateFresh,
    requestState,
    canRequestStop,
    stopUnavailableReason,
    canReleaseStop,
    canResumePausedTask,
    requestStop,
    requestRelease,
  };
};

export default useSoftwareStop;

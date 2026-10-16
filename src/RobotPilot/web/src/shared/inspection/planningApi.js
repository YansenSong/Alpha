import { apiFetch } from "../api/apiFetch";
import { sendStoredMissionCommand } from "../missions/taskApi";

const prefix = (robotId) => `/api/v1/robots/${encodeURIComponent(robotId)}`;
const pause = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

export async function listInspectionMissions(robotId) {
  const response = await apiFetch(`${prefix(robotId)}/missions`, {
    cache: "no-store",
  });
  const payload = await response.json();
  return (payload.missions || []).filter((item) =>
    String(item.id).startsWith("inspection-"),
  );
}

export async function listInspectionPoints(robotId, mapId) {
  const response = await apiFetch(
    `${prefix(robotId)}/waypoints?map_id=${encodeURIComponent(mapId)}`,
    { cache: "no-store" },
  );
  const points = (await response.json()).waypoints || [];
  const plans = await Promise.all(
    points.map(async (point) => {
      try {
        const result = await apiFetch(
          `${prefix(robotId)}/waypoints/${encodeURIComponent(
            point.waypoint_id,
          )}/action-plan`,
          { cache: "no-store" },
        );
        const plan = await result.json();
        return {
          ...point,
          actions: plan.actions || [],
          actionRevision: plan.revision,
        };
      } catch (error) {
        if (error.status === 404)
          return { ...point, actions: [], actionRevision: 0 };
        throw error;
      }
    }),
  );
  return plans;
}

export async function saveInspectionPoint(
  robotId,
  point,
  actions,
  original = null,
) {
  const path = original
    ? `${prefix(robotId)}/waypoints/${encodeURIComponent(original.waypoint_id)}`
    : `${prefix(robotId)}/waypoints`;
  const response = await apiFetch(path, {
    method: original ? "PATCH" : "POST",
    headers: {
      "Content-Type": "application/json",
      ...(original ? { "If-Match": String(original.revision) } : {}),
    },
    body: JSON.stringify(point),
  });
  const saved = await response.json();
  try {
    if (actions.length || original?.actionRevision) {
      await apiFetch(
        `${prefix(robotId)}/waypoints/${encodeURIComponent(
          saved.waypoint_id,
        )}/action-plan`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "If-Match": String(original?.actionRevision || 0),
          },
          body: JSON.stringify({ actions }),
        },
      );
    }
  } catch (error) {
    error.pointSaved = saved;
    throw error;
  }
  return saved;
}

export async function deleteInspectionPoint(robotId, point) {
  await apiFetch(
    `${prefix(robotId)}/waypoints/${encodeURIComponent(point.waypoint_id)}`,
    {
      method: "DELETE",
      headers: { "If-Match": String(point.revision) },
    },
  );
}

export function missionStops(mission) {
  const stops = [];
  for (const step of mission?.steps || []) {
    if (step.type === "waypoint" && (step.waypoint_id || step.waypointId)) {
      stops.push({
        waypoint_id: step.waypoint_id || step.waypointId,
        execute_actions: false,
        uiId: step.id,
      });
    } else if (
      (step.type === "wait" || step.type === "inspection_action") &&
      stops.length
    ) {
      stops[stops.length - 1].execute_actions = true;
    }
  }
  return stops;
}

export async function compileInspectionMission(
  robotId,
  { name, stops, missionId },
) {
  const requestId = window.crypto.randomUUID();
  const response = await apiFetch(`${prefix(robotId)}/inspection/tasks`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": requestId,
    },
    body: JSON.stringify({
      name,
      points: stops.map(({ waypoint_id, execute_actions }) => ({
        waypoint_id,
        execute_actions,
      })),
      compile_only: true,
      ...(missionId ? { mission_id: missionId } : {}),
    }),
  });
  const payload = await response.json();
  const id = payload.mission_id;
  const command = payload.mission;
  if (command?.status === "rejected")
    throw new Error(command.error || "机器人拒绝保存任务");
  if (command?.status === "pending") {
    let accepted = false;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await pause(250);
      const ack = await apiFetch(
        `${prefix(robotId)}/commands/${encodeURIComponent(command.command_id)}`,
        { cache: "no-store" },
      );
      const result = await ack.json();
      if (result.status === "rejected")
        throw new Error(result.error || "机器人拒绝保存任务");
      if (result.status === "accepted") {
        accepted = true;
        break;
      }
    }
    if (!accepted) throw new Error("任务保存回执超时");
  }
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const mission = (await listInspectionMissions(robotId)).find(
      (item) => item.id === id,
    );
    const actual = missionStops(mission);
    if (
      mission &&
      mission.name === name &&
      actual.length === stops.length &&
      actual.every(
        (stop, index) =>
          stop.waypoint_id === stops[index].waypoint_id &&
          stop.execute_actions === stops[index].execute_actions,
      )
    )
      return mission;
    await pause(250);
  }
  throw new Error("机器人已接受保存指令，但尚未能回读任务，请刷新列表核对");
}

export async function deleteInspectionMission(robotId, missionId) {
  return sendStoredMissionCommand(robotId, {
    command: "delete",
    mission_id: missionId,
  });
}

export async function startInspectionMission(robotId, missionId) {
  return sendStoredMissionCommand(robotId, {
    command: "start",
    mission_id: missionId,
  });
}

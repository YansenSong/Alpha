import { apiFetch } from "../api/apiFetch";

const requestKey = () =>
  window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;

const waitForCommand = async (robotId, result) => {
  if (result.status !== "pending") return result;
  const commandUrl = `/api/v1/robots/${encodeURIComponent(
    robotId,
  )}/commands/${encodeURIComponent(result.command_id)}`;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    const response = await apiFetch(commandUrl, { cache: "no-store" });
    const latest = await response.json();
    if (latest.status !== "pending") return latest;
  }
  throw new Error("Robot command acknowledgement timed out.");
};

const postCommand = async (robotId, path, body, method = "POST") => {
  const response = await apiFetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": requestKey(),
    },
    body: JSON.stringify(body),
  });
  const result = await waitForCommand(robotId, await response.json());
  if (result.status !== "accepted") {
    throw new Error(result.error || "Robot rejected the command.");
  }
  return result;
};

/** Send the legacy mission editor's commands through the audited platform API. */
export async function sendStoredMissionCommand(robotId, command) {
  const prefix = `/api/v1/robots/${encodeURIComponent(robotId)}`;
  const missionId = encodeURIComponent(command.mission_id || "");
  const taskId = encodeURIComponent(command.task_id || "");
  switch (command.command) {
    case "save":
      return postCommand(robotId, `${prefix}/missions`, command.mission);
    case "delete":
      return postCommand(robotId, `${prefix}/missions/${missionId}`, undefined, "DELETE");
    case "start":
      return postCommand(robotId, `${prefix}/tasks`, { mission_id: command.mission_id });
    case "pause":
    case "resume":
    case "cancel":
    case "retry":
    case "skip":
    case "release_hold":
      return postCommand(robotId, `${prefix}/tasks/${taskId}/commands`, {
        action: command.command,
      });
    default:
      throw new Error(`Unsupported mission command: ${command.command}`);
  }
}

/** Persist a map-bound one-off mission and start it through the robot task API. */
export async function startOneOffMission({
  robotId,
  mapId,
  mapVersionId,
  name,
  steps,
}) {
  if (!robotId || !mapId || !mapVersionId) {
    throw new Error("Robot or current map identity is unavailable.");
  }
  if (!Array.isArray(steps) || steps.length === 0) {
    throw new Error("A task needs at least one step.");
  }
  const missionId = `manual-${requestKey()}`;
  const prefix = `/api/v1/robots/${encodeURIComponent(robotId)}`;
  await postCommand(robotId, `${prefix}/missions`, {
    id: missionId,
    name: String(name).slice(0, 120),
    steps,
    map_id: mapId,
    map_version_id: mapVersionId,
  });
  return postCommand(robotId, `${prefix}/tasks`, { mission_id: missionId });
}

export function cancelMissionTask(robotId, taskId) {
  return postCommand(
    robotId,
    `/api/v1/robots/${encodeURIComponent(robotId)}/tasks/${encodeURIComponent(
      taskId,
    )}/commands`,
    { action: "cancel" },
  );
}

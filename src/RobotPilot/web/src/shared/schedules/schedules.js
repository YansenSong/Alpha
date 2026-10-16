import { apiFetch } from "../api/apiFetch";

const LEGACY_KEY = "robotpilotSchedules";
const LEGACY_BACKUP_KEY = "robotpilotSchedules.migratedBackup";
const LEGACY_IMPORTED_KEY = "robotpilotSchedules.importedIds";

const robotPath = (robotId) =>
  `/api/v1/robots/${encodeURIComponent(robotId)}/schedules`;

const waitForCommand = async (robotId, result) => {
  if (result.status !== "pending") {
    if (result.status !== "accepted") throw new Error(result.error || "Robot rejected the command.");
    return result;
  }
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 250));
    const response = await apiFetch(
      `/api/v1/robots/${encodeURIComponent(robotId)}/commands/${encodeURIComponent(result.command_id)}`,
      { cache: "no-store" },
    );
    const latest = await response.json();
    if (latest.status === "accepted") return latest;
    if (latest.status === "rejected") throw new Error(latest.error || "Robot rejected the command.");
  }
  throw new Error("Robot command acknowledgement timed out.");
};

export async function fetchSavedRoutes(robotId) {
  const response = await apiFetch(
    `/api/v1/robots/${encodeURIComponent(robotId)}/routes`,
    { cache: "no-store" },
  );
  return (await response.json()).routes || [];
}

export async function saveRouteAsMission(robotId, route) {
  const response = await apiFetch(
    `/api/v1/robots/${encodeURIComponent(robotId)}/routes/${encodeURIComponent(route.map_id)}/${encodeURIComponent(route.name)}/mission`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    },
  );
  const result = await response.json();
  await waitForCommand(robotId, result);
  return result.mission_id;
}

export async function fetchSchedules(robotId) {
  const response = await apiFetch(robotPath(robotId), { cache: "no-store" });
  return (await response.json()).schedules || [];
}

export async function fetchScheduleRuns(robotId, scheduleId) {
  const response = await apiFetch(
    `${robotPath(robotId)}/${encodeURIComponent(scheduleId)}/runs`,
    { cache: "no-store" },
  );
  return (await response.json()).runs || [];
}

export async function createSchedule(robotId, schedule) {
  const response = await apiFetch(robotPath(robotId), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({ schedule }),
  });
  return waitForCommand(robotId, await response.json());
}

export async function patchSchedule(robotId, schedule, patch) {
  const response = await apiFetch(
    `${robotPath(robotId)}/${encodeURIComponent(schedule.schedule_id)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
        "If-Match": String(schedule.revision),
      },
      body: JSON.stringify(patch),
    },
  );
  return response.json();
}

export async function deleteSchedule(robotId, schedule) {
  const response = await apiFetch(
    `${robotPath(robotId)}/${encodeURIComponent(schedule.schedule_id)}`,
    {
      method: "DELETE",
      headers: {
        "Idempotency-Key": crypto.randomUUID(),
        "If-Match": String(schedule.revision),
      },
    },
  );
  return response.json();
}

export function getLegacySchedules() {
  try {
    const value = JSON.parse(localStorage.getItem(LEGACY_KEY) || "[]");
    const imported = new Set(
      JSON.parse(localStorage.getItem(LEGACY_IMPORTED_KEY) || "[]"),
    );
    return Array.isArray(value)
      ? value.filter((item) => !imported.has(String(item.id)))
      : [];
  } catch {
    return [];
  }
}

export function backupLegacySchedules() {
  const raw = localStorage.getItem(LEGACY_KEY) || "[]";
  localStorage.setItem(LEGACY_BACKUP_KEY, raw);
  return raw;
}

export function markLegacyScheduleImported(scheduleId) {
  const imported = new Set(
    JSON.parse(localStorage.getItem(LEGACY_IMPORTED_KEY) || "[]"),
  );
  imported.add(String(scheduleId));
  localStorage.setItem(LEGACY_IMPORTED_KEY, JSON.stringify([...imported]));
}

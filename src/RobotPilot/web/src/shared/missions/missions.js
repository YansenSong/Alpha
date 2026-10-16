// The robot is authoritative. Browser storage is read only for legacy import.
import { newMissionId } from "./id";
import { sendMissionCommand } from "./transport";
let missions = [];
let online = false;
const listeners = new Set();
const emit = () => listeners.forEach((fn) => fn(missions));
const send = (command) => {
  return online && sendMissionCommand(command);
};

export const getMissions = () => missions;
const getMission = (id) => missions.find((m) => m.id === id) || null;
export const isMissionOnline = () => online;
export const subscribeMissions = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
export const setMissionOnline = (value) => {
  online = value;
  emit();
};
export const replaceMissionsFromRobot = (value) => {
  missions = Array.isArray(value) ? value : [];
  emit();
};
export const loadLegacyMissions = () => {
  try {
    const value = JSON.parse(
      localStorage.getItem("robotpilotMissions") || "[]",
    );
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
};
const save = (mission) => {
  if (!send({ command: "save", mission })) return false;
  missions = [...missions.filter((m) => m.id !== mission.id), mission];
  emit();
  return true;
};
export const importMission = (mission) =>
  save({ ...mission, id: String(mission.id) });
export const addMission = (name, mapId, mapVersionId) => {
  if (!mapId || !mapVersionId) return null;
  const mission = {
    id: newMissionId(),
    name,
    steps: [],
    map_id: mapId,
    map_version_id: mapVersionId,
  };
  return save(mission) ? mission : null;
};
export const removeMission = (id) => {
  if (!send({ command: "delete", mission_id: id })) return;
  missions = missions.filter((m) => m.id !== id);
  emit();
};
const setSteps = (id, steps) => {
  const mission = getMission(id);
  if (mission) save({ ...mission, steps });
};
export const addStep = (id, step) => {
  const mission = getMission(id);
  if (mission)
    setSteps(id, [...mission.steps, { ...step, id: newMissionId() }]);
};
export const removeStep = (id, stepId) => {
  const mission = getMission(id);
  if (mission)
    setSteps(
      id,
      mission.steps.filter((step) => step.id !== stepId),
    );
};
export const moveStep = (id, stepId, direction) => {
  const mission = getMission(id);
  if (!mission) return;
  const steps = [...mission.steps];
  const index = steps.findIndex((step) => step.id === stepId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= steps.length) return;
  [steps[index], steps[target]] = [steps[target], steps[index]];
  setSteps(id, steps);
};

// ROS mission manager owns execution; this module exposes its latest snapshot.
import { sendMissionCommand } from "./transport";
import { isMissionOnline } from "./missions";
let run = null;
let history = [];
const listeners = new Set();
export const getRun = () => run;
export const getHistory = () => history;
export const subscribeRun = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
export const setRun = (next) => {
  run = next;
  listeners.forEach((fn) => fn(run));
};
export const setHistory = (next) => {
  history = next || [];
};
const request = (command, extra = {}) =>
  isMissionOnline() && sendMissionCommand({ command, ...extra });
export const requestStart = (missionId) =>
  request("start", { mission_id: missionId });
export const requestStop = () => request("cancel", { task_id: run?.taskId });
export const requestPause = () => request("pause", { task_id: run?.taskId });
export const requestResume = () => request("resume", { task_id: run?.taskId });
export const requestRetry = () => request("retry", { task_id: run?.taskId });
export const requestSkip = () => request("skip", { task_id: run?.taskId });
export const requestReleaseHold = () =>
  request("release_hold", { task_id: run?.taskId });

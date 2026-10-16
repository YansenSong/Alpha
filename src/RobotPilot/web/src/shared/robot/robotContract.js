// Project integration points. Empty names remain unconfigured; mission
// Command and state topics are implemented by mission_manager.
export const INSPECTION_PROFILE =
  (import.meta.env.VITE_UI_PROFILE || import.meta.env.REACT_APP_UI_PROFILE) ===
  "inspection_demo";

export const robotContract = Object.freeze({
  mapTopic: "/ui/map", // Existing UI relay, not a project robot interface.
  localizationPoseTopic: "",
  localizationStateTopic: "",
  navigationGoalTopic: "",
  navigationStatusTopic: "",
  navigationCancelService: "",
  missionCommandTopic: "/mission/command",
  missionStateTopic: "/mission/state",
  softwareStopService: "",
  manualCommandTopic: INSPECTION_PROFILE ? "" : "/cmd_vel",
});

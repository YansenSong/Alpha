const UNAVAILABLE_STEP_TYPES = new Set(["dock", "undock"]);

export const hasUnavailableStep = (mission) =>
  mission?.steps?.some((step) => UNAVAILABLE_STEP_TYPES.has(step.type)) ||
  false;

export const missionKind = (
  mission,
  scheduleMissionIds,
  schedulesAvailable,
) => {
  if (String(mission?.id || "").startsWith("manual-")) return "forced_one_off";
  if (scheduleMissionIds?.has(mission?.id)) return "regular_scheduled";
  return schedulesAvailable ? "operator_specified" : "unavailable";
};

export const isExecutableStep = (stepType) =>
  !UNAVAILABLE_STEP_TYPES.has(stepType);

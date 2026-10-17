const COLORS = {
  keepout: { stroke: "#ef4444", fill: "#ef444438", badge: "#b91c1c" },
  speed: { stroke: "#3b82f6", fill: "#3b82f638", badge: "#1d4ed8" },
  wall: { stroke: "#a855f7", fill: "#a855f738", badge: "#7e22ce" },
  closure: { stroke: "#f97316", fill: "#f9731638", badge: "#c2410c" },
};
const DISABLED = { stroke: "#94a3b8", fill: "#94a3b822", badge: "#64748b" };
export const areaRuleColors = (rule) =>
  rule.enabled === false ? DISABLED : COLORS[rule.type] || COLORS.keepout;

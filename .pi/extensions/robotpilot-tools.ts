import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "get_alpha_info",
    label: "Alpha project information",
    description: "Read static project capabilities. Mock information only; does not query ROS or control a robot.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute() {
      return {
        content: [{ type: "text", text: JSON.stringify({
          project: "AckermannRobot / Alpha",
          mode: "mock",
          modules: ["ROS2 simulation", "localization", "navigation", "RobotPilot web"],
          liveRobotConnected: false,
          availableRobotTools: ["get_alpha_info"],
        }) }],
        details: { mode: "mock" },
      };
    },
  });
}

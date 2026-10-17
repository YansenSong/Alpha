import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "get_alpha_info",
    label: "Alpha project information",
    description: "Read static project capabilities. Static information only; does not query ROS or control a robot.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute() {
      return {
        content: [{ type: "text", text: JSON.stringify({
          project: "AckermannRobot / Alpha",
          mode: "project-info",
          modules: ["ROS2 simulation", "localization", "navigation", "RobotPilot web"],
          liveRobotConnected: false,
          availableRobotTools: ["Use MCP get_robot_status and ROS inspection tools for actual availability"],
        }) }],
        details: { mode: "project-info" },
      };
    },
  });
}

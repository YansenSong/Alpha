import assert from "node:assert/strict";
import { createProjectSession, disposeProjectSession, robotTools } from "./pi-host.mjs";

let session;
try {
  ({ session } = await createProjectSession({ trustProject: true, live: true }));
  assert(robotTools.every(name => session.getActiveToolNames().includes(name)));
  const calls = [];
  session.subscribe(event => {
    if (event.type === "tool_execution_start") calls.push(event.toolName);
  });
  await session.prompt("仅做只读检查：调用 mcp__ros_inspect__get_nodes、mcp__ros_inspect__get_topics 和 mcp__alpha__get_robot_status，报告当前实际环境和导航限制。不要执行导航、停车、取消或任何写操作；不要把历史成功状态当作新的到达验证。简短回答。");
  for (const name of ["mcp__ros_inspect__get_nodes", "mcp__ros_inspect__get_topics", "mcp__alpha__get_robot_status"]) {
    assert(calls.includes(name), `Missing live read-only call: ${name}`);
  }
  assert(!calls.some(name => /navigate_to_location|request_software_stop|cancel_navigation/.test(name)));
  const last = session.messages.filter(message => message.role === "assistant").at(-1);
  assert(!last?.errorMessage, last?.errorMessage);
  console.log("PASS Pi SDK + real model + project MCP tools + live ROS graph/status (read-only)");
} finally {
  await disposeProjectSession(session);
}

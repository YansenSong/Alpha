import assert from "node:assert/strict";
import { createProjectSession, disposeProjectSession, projectRoot, allowedTools } from "./pi-host.mjs";

const live = process.argv.includes("--live");
const trustProject = process.argv.includes("--trust-project");
let session;
try {
  const host = await createProjectSession({ trustProject, live });
  session = host.session;
  console.log(`PASS project resources: ${projectRoot}`);
  console.log(`PASS tool allowlist: ${allowedTools.join(", ")}`);
  const tool = host.resourceLoader.getExtensions().extensions.find(extension => extension.tools.has("get_alpha_info")).tools.get("get_alpha_info");
  assert.ok(tool, "Project tool must be registered");
  const result = await tool.definition.execute("verify-offline", {}, new AbortController().signal, () => {}, {});
  const info = JSON.parse(result.content[0].text);
  assert.equal(info.mode, "project-info");
  assert.equal(info.liveRobotConnected, false);
  console.log("PASS static project-info tool execution");
  if (live) {
    console.log(`Model: ${session.model.provider}/${session.model.id}`);
    let deltas = 0;
    let toolEnds = 0;
    let settled = 0;
    let failure;
    const unsubscribe = session.subscribe(event => {
      if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
        deltas++;
        process.stdout.write(event.assistantMessageEvent.delta);
      }
      if (event.type === "tool_execution_end") {
        if (event.isError) failure = "Tool execution failed";
        if (event.toolName === "get_alpha_info" && !event.isError) toolEnds++;
      }
      if (event.type === "message_end" && event.message.role === "assistant" && event.message.stopReason === "error") {
        failure = "Model request failed (inspect local Pi authentication/provider configuration)";
      }
      if (event.type === "agent_settled") settled++;
    });
    const timeout = setTimeout(() => { failure = "Live verification timed out"; void session.abort(); }, 90000);
    try {
      await session.prompt("请调用 get_alpha_info 工具，然后用一句中文说明项目支持哪些能力，并说明项目信息是静态信息，实时机器人状态需要查询 MCP 工具。");
      assert.ifError(failure);
      assert.ok(deltas > 0, "Must receive streamed text");
      assert.ok(toolEnds > 0, "Model must execute get_alpha_info");
      assert.ok(settled > 0, "Must receive agent_settled");
      console.log("\nPASS live streaming, model-selected tool execution and settled event");
      let abortRequested = false;
      let abortPromise;
      const stop = session.subscribe(event => {
        if (event.type === "message_update" && !abortRequested) {
          abortRequested = true;
          abortPromise = session.abort();
        }
      });
      try {
        await session.prompt("请写一篇很长的机器人导航技术介绍，至少五千字。");
        await abortPromise;
        assert.ok(abortRequested, "Abort must be triggered during generation");
        assert.equal(session.isStreaming, false);
        console.log("\nPASS abort during generation");
      } finally { stop(); }
    } finally { clearTimeout(timeout); unsubscribe(); }
  } else {
    console.log("Offline checks complete. Model streaming and abort have NOT been tested.");
  }
} catch (error) {
  console.error(`FAIL ${error.message}`);
  process.exitCode = 1;
} finally {
  await disposeProjectSession(session);
}

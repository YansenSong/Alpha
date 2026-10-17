import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  createAgentSession, createMcpExtension, DefaultResourceLoader, ModelRuntime,
  SessionManager, SettingsManager, getAgentDir,
} from "@earendil-works/pi-coding-agent";

export const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
export const allowedTools = ["get_alpha_info"];
export const robotTools = ["mcp__ros_inspect__get_nodes", "mcp__ros_inspect__get_node_details", "mcp__ros_inspect__get_topics", "mcp__ros_inspect__get_topic_type", "mcp__ros_inspect__get_services", "mcp__ros_inspect__get_actions", "mcp__ros_inspect__get_action_status", "mcp__ros_inspect__subscribe_once", "mcp__alpha__get_robot_status", "mcp__alpha__list_navigation_locations", "mcp__alpha__navigate_to_location", "mcp__alpha__get_task_status", "mcp__alpha__request_software_stop", "mcp__alpha__cancel_navigation"];

// Deliberately separate global executable resources from model credentials.
// Trust is scoped to this host invocation; never updates ~/.pi/agent/trust.json.
export async function createProjectSession({ trustProject = false, live = false, enableMcp = live && process.env.ALPHA_AGENT_MCP !== "0", sessionManager = SessionManager.inMemory() } = {}) {
  if (!trustProject) throw new Error("Project resource loading requires explicit trustProject: true");
  const agentDir = path.join(projectRoot, "third_party/RobotPilot/agent-gateway/.runtime/agent");
  await mkdir(agentDir, { recursive: true });
  const settingsManager = SettingsManager.create(projectRoot, agentDir);
  const configFile = path.join(projectRoot, ".pi/mcp.json");
  const mcpConfig = enableMcp ? JSON.parse(await readFile(configFile, "utf8")) : null;
  if (mcpConfig && Object.keys(mcpConfig.mcpServers).some(name => !["alpha", "ros_inspect"].includes(name))) {
    throw new Error("Only Alpha's project MCP servers are permitted");
  }
  const loadConfig = () => ({
    servers: Object.entries(mcpConfig?.mcpServers ?? {}).map(([name, config]) => ({ name, config, source: configFile, scope: "project" })),
    errors: [], autoEnableCodemode: false, projectConfig: configFile,
  });
  const resourceLoader = new DefaultResourceLoader({
    cwd: projectRoot, agentDir, settingsManager,
    extensionFactories: enableMcp ? [createMcpExtension({ loadConfig, logPath: path.join(agentDir, "mcp.log") })] : [],
    noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
  });
  await resourceLoader.reload({ resolveProjectTrust: async () => true });
  const loaded = resourceLoader.getExtensions();
  if (loaded.errors.length) throw new Error(`Project extension loading failed: ${JSON.stringify(loaded.errors)}`);
  const expectedExtension = path.join(projectRoot, ".pi/extensions/robotpilot-tools.ts");
  if (loaded.extensions.length !== (enableMcp ? 2 : 1) || !loaded.extensions.some(extension => path.resolve(extension.path) === expectedExtension)) {
    throw new Error("Unexpected extension set: only robotpilot-tools.ts is permitted in this verification host");
  }
  if (!resourceLoader.getAppendSystemPrompt().some(text => text.includes("ALPHA_AGENT_POLICY"))) {
    throw new Error("Project APPEND_SYSTEM.md was not loaded");
  }
  // No global executable extensions/settings are used. ModelRuntime alone reads
  // the user's existing model registry and authentication when live is requested.
  const modelRuntime = await ModelRuntime.create(live ? {} : {
    authPath: path.join(agentDir, "auth.json"),
    modelsPath: path.join(agentDir, "models.json"),
  });
  let model;
  if (live) {
    const available = await modelRuntime.getAvailable();
    let defaults = {};
    try {
      defaults = JSON.parse(await readFile(path.join(getAgentDir(), "settings.json"), "utf8"));
    } catch (error) { if (error.code !== "ENOENT") throw new Error("Cannot read Pi model preferences"); }
    if (Boolean(process.env.PI_AGENT_PROVIDER) !== Boolean(process.env.PI_AGENT_MODEL)) {
      throw new Error("Set both PI_AGENT_PROVIDER and PI_AGENT_MODEL");
    }
    const provider = process.env.PI_AGENT_PROVIDER ?? defaults.defaultProvider;
    const modelId = process.env.PI_AGENT_MODEL ?? defaults.defaultModel;
    if (Boolean(provider) !== Boolean(modelId)) throw new Error("Set both PI_AGENT_PROVIDER and PI_AGENT_MODEL");
    model = provider
      ? available.find(m => m.provider === provider && m.id === modelId)
      : available[0];
    if (!model) throw new Error("No authenticated model available; configure Pi or set PI_AGENT_PROVIDER and PI_AGENT_MODEL");
  }
  const { session } = await createAgentSession({
    cwd: projectRoot, agentDir, settingsManager, resourceLoader, modelRuntime, model,
    tools: enableMcp ? [...allowedTools, ...robotTools] : allowedTools,
    sessionManager,
    thinkingLevel: "off",
  });
  try {
    await session.bindExtensions({});
    if (enableMcp) {
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline && !robotTools.every(name => session.getActiveToolNames().includes(name))) {
        await new Promise(resolve => setTimeout(resolve, 100));
      }
    }
    const actual = session.getActiveToolNames().slice().sort();
    const expected = (enableMcp ? [...allowedTools, ...robotTools] : [...allowedTools]).sort();
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      throw new Error(`Unexpected active tools: ${actual.join(", ")}`);
    }
    return { session, resourceLoader };
  } catch (error) {
    await disposeProjectSession(session);
    throw error;
  }
}

export async function disposeProjectSession(session) {
  if (!session) return;
  await session.abort();
  if (session.extensionRunner?.hasHandlers("session_shutdown")) {
    await session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" });
  }
  session.dispose();
}

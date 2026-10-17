import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  createAgentSession, DefaultResourceLoader, ModelRuntime,
  SessionManager, SettingsManager, getAgentDir,
} from "@earendil-works/pi-coding-agent";

export const projectRoot = fileURLToPath(new URL("../../../../", import.meta.url));
export const allowedTools = ["get_alpha_info"];

// Deliberately separate global executable resources from model credentials.
// Trust is scoped to this host invocation; never updates ~/.pi/agent/trust.json.
export async function createProjectSession({ trustProject = false, live = false, sessionManager = SessionManager.inMemory() } = {}) {
  if (!trustProject) throw new Error("Project resource loading requires explicit trustProject: true");
  const agentDir = path.join(projectRoot, "third_party/RobotPilot/agent-gateway/.runtime/agent");
  await mkdir(agentDir, { recursive: true });
  const settingsManager = SettingsManager.create(projectRoot, agentDir);
  const resourceLoader = new DefaultResourceLoader({
    cwd: projectRoot, agentDir, settingsManager,
    noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
  });
  await resourceLoader.reload({ resolveProjectTrust: async () => true });
  const loaded = resourceLoader.getExtensions();
  if (loaded.errors.length) throw new Error(`Project extension loading failed: ${JSON.stringify(loaded.errors)}`);
  const expectedExtension = path.join(projectRoot, ".pi/extensions/robotpilot-tools.ts");
  if (loaded.extensions.length !== 1 || path.resolve(loaded.extensions[0].path) !== expectedExtension) {
    throw new Error("Unexpected extension set: only robotpilot-tools.ts is permitted in this verification host");
  }
  if (!resourceLoader.getAppendSystemPrompt().some(text => text.includes("MOCK ONLY"))) {
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
    tools: allowedTools,
    sessionManager,
    thinkingLevel: "off",
  });
  try {
    await session.bindExtensions({});
    const actual = session.getActiveToolNames().slice().sort();
    if (JSON.stringify(actual) !== JSON.stringify(allowedTools)) {
      throw new Error(`Unexpected active tools: ${actual.join(", ")}`);
    }
    return { session, resourceLoader };
  } catch (error) {
    session.dispose();
    throw error;
  }
}

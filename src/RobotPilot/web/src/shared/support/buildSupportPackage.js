import packageJson from "../../../package.json";
import { getEvents } from "../events/eventLog";
import { loadParamRows, readParamValue } from "../constants/navParams";

const PARAM_READ_TIMEOUT_MS = 2500;
const RECENT_EVENTS_LIMIT = 50;

// Best-effort, read-only snapshot of the curated Nav2 param list — a fresh
// ROSLIB.Service per node/get_parameters call, raced against a timeout so one
// unresponsive node can't hang the whole export. The snapshot can be called
// from a page that never mounted parameter controls, such as Health Centre.
const snapshotNavParams = (ros, rosConnected) => {
  if (!ros || !rosConnected || !window.ROSLIB) {
    return Promise.resolve(
      loadParamRows().map(({ node, param, type }) => ({
        node,
        param,
        type,
        value: null,
        status: "not-read (rosbridge offline)",
      })),
    );
  }

  const services = {};
  const svc = (node) => {
    if (!services[node]) {
      services[node] = new window.ROSLIB.Service({
        ros,
        name: `${node}/get_parameters`,
        serviceType: "rcl_interfaces/srv/GetParameters",
      });
    }
    return services[node];
  };

  const readOne = ({ node, param, type }) =>
    new Promise((resolve) => {
      let done = false;
      const finish = (value, status) => {
        if (done) return;
        done = true;
        resolve({ node, param, type, value, status });
      };
      const timer = setTimeout(() => finish(null, "timeout"), PARAM_READ_TIMEOUT_MS);
      try {
        svc(node).callService(
          new window.ROSLIB.ServiceRequest({ names: [param] }),
          (res) => {
            clearTimeout(timer);
            const pv = res?.values?.[0];
            if (!pv || pv.type === 0) finish(null, "not-set");
            else finish(readParamValue(pv), "read");
          },
          () => {
            clearTimeout(timer);
            finish(null, "error");
          },
        );
      } catch {
        clearTimeout(timer);
        finish(null, "error");
      }
    });

  return Promise.all(loadParamRows().map(readOne));
};

/**
 * Assembles a single JSON-serializable snapshot for offline troubleshooting:
 * connection status, the Health Centre rollup, recent events, runtime config,
 * and a best-effort Nav2 param snapshot. The package includes no connection
 * address or credentials.
 *
 * Callers pass in health and runtime settings they already loaded; this
 * function doesn't create additional ROS subscriptions.
 */
export default async function buildSupportPackage({
  ros,
  rosStatus,
  config,
  health,
}) {
  const navParams = await snapshotNavParams(ros, rosStatus === "connected");

  return {
    generatedAt: new Date().toISOString(),
    appVersion: packageJson.version,
    userAgent: typeof navigator !== "undefined" ? navigator.userAgent : null,
    connection: { rosStatus },
    health: {
      overall: health.overall,
      overallLabel: health.overallLabel,
      issues: health.issues,
    },
    recentEvents: getEvents().slice(0, RECENT_EVENTS_LIMIT),
    runtimeConfig: config,
    navParams,
  };
}

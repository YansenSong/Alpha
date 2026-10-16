import { AppConfig } from "./index";

const STORAGE_KEY = "robotpilotRuntimeConfig";

// Browser-only drive limits and notification preferences, persisted locally.
export const DEFAULT_RUNTIME_CONFIG = {
  maxLinearSpeed: AppConfig.MAX_LINEAR_SPEED,
  maxAngularSpeed: AppConfig.MAX_ANGULAR_SPEED,
  notificationsEnabled: false,
  lowBatteryThreshold: 20,
};

export function loadRuntimeConfig() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    delete stored.demoMode;
    delete stored.rosbridgeHost;
    delete stored.rosbridgePort;
    delete stored.cameraPort;
    return { ...DEFAULT_RUNTIME_CONFIG, ...stored };
  } catch {
    return { ...DEFAULT_RUNTIME_CONFIG };
  }
}

export function saveRuntimeConfig(config) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

// Follow the page hostname in production and use the configured robot host
// when the Vite development server runs locally.
export function resolveRosbridgeHost() {
  const isLocalDevServer = window.location.href.includes(
    "http://localhost:3000/",
  );
  return isLocalDevServer
    ? AppConfig.ROSBRIDGE_SERVER_IP
    : window.location.hostname;
}

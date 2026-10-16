// React DOM 18 的开发版会在模块加载时读取 navigator.userAgent.indexOf。
// 某些嵌入式浏览器没有提供 userAgent；先补齐，再加载应用入口。
if (typeof navigator.userAgent !== "string") {
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: "",
  });
}

// Keep settings and browser drafts from existing OpenAMR installations.
try {
  for (const suffix of [
    "EventLog", "KeepoutZones", "LangV2", "Metrics", "Missions",
    "ParamRows", "RegisteredDevices", "RuntimeConfig", "SavedWaypoints",
    "Schedules",
  ]) {
    const oldKey = `openamr${suffix}`;
    const newKey = `robotpilot${suffix}`;
    const value = localStorage.getItem(oldKey);
    if (value !== null && localStorage.getItem(newKey) === null) {
      localStorage.setItem(newKey, value);
    }
  }
} catch {
  // Storage may be disabled; the app can still run without persisted settings.
}

import("./index.jsx");

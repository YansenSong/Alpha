import { afterEach, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

test("inspection profile omits the standalone missions page", async () => {
  vi.stubEnv("REACT_APP_UI_PROFILE", "inspection_demo");
  vi.resetModules();
  const { PAGE_REGISTRY, NAV_REGISTRY } = await import("./registry");
  expect(PAGE_REGISTRY.map(({ path }) => path)).toEqual([
    "/",
    "/route",
    "/maps",
    "/info",
    "/health",
    "/events",
    "/assets",
    "/logs",
    "/bms",
    "/scheduler",
  ]);
  expect(NAV_REGISTRY.some(({ path }) => path === "/missions")).toBe(false);
});

test("legacy profile omits removed optional pages and keeps device management", async () => {
  vi.stubEnv("REACT_APP_UI_PROFILE", "");
  vi.resetModules();
  const { PAGE_REGISTRY } = await import("./registry");
  expect(PAGE_REGISTRY.some(({ path }) => path === "/blocks")).toBe(false);
  expect(PAGE_REGISTRY.some(({ path }) => path === "/robot")).toBe(false);
  expect(PAGE_REGISTRY.some(({ path }) => path === "/metrics")).toBe(false);
  expect(PAGE_REGISTRY.some(({ path }) => path === "/recordings")).toBe(false);
  expect(PAGE_REGISTRY.some(({ path }) => path === "/devices")).toBe(true);
});

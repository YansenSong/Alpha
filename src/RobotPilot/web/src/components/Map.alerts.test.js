import { readFileSync } from "node:fs";
import { afterEach, expect, test, vi } from "vitest";

const script = readFileSync("public/ros/nav2d.js", "utf8");

afterEach(() => {
  delete window.NAV2D;
  delete window.createjs;
});

test("map pins accept map-frame positions, invoke alert details and clear old pins", () => {
  class Shape {
    constructor() {
      this.graphics = Object.fromEntries(
        ["beginFill", "beginStroke", "setStrokeStyle", "drawCircle"]
          .map((name) => [name, () => this.graphics]),
      );
      this.listeners = {};
    }
    addEventListener(name, handler) { this.listeners[name] = handler; }
  }
  class Text {
    constructor(text) { this.text = text; }
  }
  window.createjs = { Shape, Text };
  new Function("window", script)(window);
  const scene = {
    scaleX: 2, scaleY: 2,
    addChild: vi.fn((item) => { item.parent = scene; }),
    removeChild: vi.fn((item) => { item.parent = null; }),
  };
  window.NAV2D.canvas = { scene };
  const onAlert = vi.fn();
  window.NAV2D._inspectionAlertClickCallback = onAlert;
  window.NAV2D.setInspectionAlerts([
    { alert_id: "alert-1", category: "fire_smoke",
      position: { frame_id: "map", x: 1.5, y: -2 } },
    { alert_id: "alert-wrong-frame", position: { frame_id: "odom", x: 3, y: 4 } },
    { alert_id: "alert-no-location" },
  ]);
  expect(window.NAV2D.inspectionAlertItems).toHaveLength(1);
  const { marker, label } = window.NAV2D.inspectionAlertItems[0];
  expect([marker.x, marker.y]).toEqual([1.5, 2]);
  expect(label.text).toContain("fire_smoke");
  marker.listeners.click({ nativeEvent: { button: 0 } });
  expect(onAlert).toHaveBeenCalledWith("alert-1");
  marker.listeners.click({ nativeEvent: { button: 2 } });
  expect(onAlert).toHaveBeenCalledTimes(1);
  window.NAV2D.setInspectionAlerts([]);
  expect(window.NAV2D.inspectionAlertItems).toHaveLength(0);
  expect(scene.removeChild).toHaveBeenCalledWith(marker);
});

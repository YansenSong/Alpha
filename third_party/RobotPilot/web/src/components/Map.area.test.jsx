import React from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("../app/App", () => ({ useRos: () => ({}) }));
vi.mock("../shared/i18n/i18n", () => ({
  useT: () => ({ t: (value) => value }),
  T: ({ children }) => children,
}));
vi.mock("../shared/ui/Dashboard", () => ({
  IconButton: ({ children, ...props }) => <button {...props}>{children}</button>,
}));

import Map from "./Map";

const pointer = (target, type, x, y) => {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.assign(event, {
    button: 0, pointerType: "mouse", pointerId: 1, clientX: x, clientY: y,
  });
  target.dispatchEvent(event);
};

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(560);
  vi.spyOn(SVGElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: 800, height: 560,
  });
  window.ROSLIB = { Topic: class {
    subscribe() {}
    unsubscribe() {}
    publish() {}
  } };
  window.NAV2D = { InitMap: vi.fn(), shift: vi.fn() };
  window.createjs = {
    Shape: class {
      constructor() {
        this.graphics = Object.fromEntries(
          ["clear", "beginFill", "beginStroke", "setStrokeStyle", "drawRect", "moveTo", "lineTo"]
            .map((name) => [name, () => this.graphics]),
        );
      }
    },
  };
  window.ROS2D = { Viewer: class {
    constructor({ divID, width, height }) {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width, height });
      document.getElementById(divID).appendChild(canvas);
      this.scene = {
        canvas,
        children: [],
        offsetX: 0,
        globalToRos: (x, y) => ({ x: x / 10, y: y / 10 }),
        localToGlobal(x, y) { return { x: x * 10 + this.offsetX, y: y * 10 }; },
        addChild(shape) { shape.parent = this; this.children.push(shape); },
        removeChild(shape) { this.children = this.children.filter((item) => item !== shape); shape.parent = null; },
        get numChildren() { return this.children.length; },
        setChildIndex(shape, index) {
          this.removeChild(shape);
          shape.parent = this;
          this.children.splice(index, 0, shape);
        },
      };
    }
  } };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete window.ROSLIB;
  delete window.ROS2D;
  delete window.createjs;
  delete window.NAV2D;
});

test("drawing mode turns a canvas drag into a robot map rectangle", async () => {
  const onAreaDraw = vi.fn();
  const { container, rerender } = render(<Map drawingArea areaDrawType="keepout"
    onAreaDraw={onAreaDraw} />);
  const canvas = await waitFor(() => {
    const element = container.querySelector("canvas");
    expect(element).toBeTruthy();
    return element;
  });
  pointer(canvas, "pointerdown", 100, 100);
  pointer(canvas, "pointermove", 200, 200);
  pointer(canvas, "pointerup", 200, 200);
  expect(onAreaDraw).toHaveBeenCalledWith({ cx: 15, cy: 15, w: 10, h: 10 });
  expect(window.NAV2D.shift).not.toHaveBeenCalled();

  const liveScene = window.NAV2D.canvas.scene;
  const draft = { type: "keepout", cx: 15, cy: 15, w: 10, h: 10 };
  rerender(<Map drawingArea={false} areaDrawType="keepout"
    areaPreview={draft}
    onAreaDraw={onAreaDraw} />);
  await waitFor(() => {
    expect(liveScene.children).toHaveLength(0);
    expect(container.querySelector("svg rect")?.getAttribute("width")).toBe("100");
  });
  const rectangle = container.querySelector("svg rect");
  const beforePan = Number(rectangle.getAttribute("x"));
  liveScene.offsetX = 20;
  await waitFor(() => expect(Number(rectangle.getAttribute("x"))).toBe(beforePan + 20));
  rerender(<Map drawingArea={false} areaDrawType="keepout"
    areaPreview={draft} onAreaDraw={onAreaDraw} />);
  await new Promise((resolve) => setTimeout(resolve, 1100));
  expect(container.querySelector("svg rect")).toBe(rectangle);
});

import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import useTranscriptScroll from "./useTranscriptScroll";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function View({ revision, session = "one" }) {
  const scroll = useTranscriptScroll(session, revision);
  return (
    <>
      <div
        data-testid="list"
        ref={scroll.listRef}
        onScroll={scroll.onScroll}
        onWheel={scroll.onWheel}
        onKeyDown={scroll.onKeyDown}
      >
        <div ref={scroll.bodyRef} />
      </div>
      <button onClick={scroll.jumpToLatest}>最新消息</button>
      <output>{scroll.following ? "跟随" : "阅读历史"}</output>
    </>
  );
}

test("content resize follows the bottom but never drags a history reader down", () => {
  let resize;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback) {
        resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  const view = render(<View revision={0} />);
  const list = screen.getByTestId("list");
  let height = 1000;
  let top = 0;
  Object.defineProperties(list, {
    clientHeight: { get: () => 400 },
    scrollHeight: { get: () => height },
    scrollTop: {
      get: () => top,
      set: (value) => {
        top = value;
      },
    },
  });
  view.rerender(<View revision={1} />);
  expect(top).toBe(600);
  // Content grew, but the user did not move: keep following despite a scroll event.
  height = 1400;
  fireEvent.scroll(list);
  act(() => resize());
  expect(top).toBe(1000);
  fireEvent.wheel(list, { deltaY: -100 });
  top = 200;
  fireEvent.scroll(list);
  height = 1800;
  view.rerender(<View revision={2} />);
  act(() => resize());
  expect(top).toBe(200);
  expect(screen.getByText("阅读历史")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "最新消息" }));
  expect(top).toBe(1400);
  expect(screen.getByText("跟随")).toBeTruthy();
  fireEvent.wheel(list, { deltaY: -100 });
  view.rerender(<View revision={3} session="two" />);
  expect(screen.getByText("跟随")).toBeTruthy();
});

import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "./apiFetch";

const jsonResponse = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

afterEach(() => vi.restoreAllMocks());

describe("apiFetch error contract", () => {
  it("uses the idempotency key as the request correlation id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ csrf_token: null }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/v1/robots/robot-001/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": "request-123456" },
      body: "{}",
    });

    expect(fetchMock.mock.calls[1][1].headers.get("X-Request-ID")).toBe(
      "request-123456",
    );
  });

  it.each([
    [401, "SESSION_EXPIRED"],
    [403, "PERMISSION_DENIED"],
    [409, "CONFLICT"],
    [412, "PRECONDITION_FAILED"],
    [429, "RATE_LIMITED"],
    [503, "ROBOT_UNAVAILABLE"],
  ])("maps HTTP %i to %s and retains its request id", async (status, code) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { message: "Backend detail", request_id: "req-42" },
            status,
          ),
        ),
    );

    await expect(
      apiFetch("/api/v1/robots/robot-001/status"),
    ).rejects.toMatchObject({
      name: "ApiError",
      status,
      code,
      requestId: "req-42",
      message: "Backend detail",
    });
  });

  it("fetches CSRF before writes and reports stale version conflicts", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ csrf_token: "csrf-123" }))
      .mockResolvedValueOnce(
        jsonResponse({ message: "Reload the latest version." }, 412),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiFetch("/api/v1/robots/robot-001/config", {
        method: "PUT",
        body: JSON.stringify({ low_battery_threshold: 20 }),
      }),
    ).rejects.toMatchObject({ code: "PRECONDITION_FAILED" });
    expect(fetchMock.mock.calls[1][1].headers.get("X-CSRF-Token")).toBe(
      "csrf-123",
    );
    expect(fetchMock.mock.calls[1][1].credentials).toBe("include");
  });

  it("turns network failures into a stable API error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(
      apiFetch("/api/v1/robots/robot-001/status"),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      apiFetch("/api/v1/robots/robot-001/status"),
    ).rejects.toMatchObject({
      code: "NETWORK_ERROR",
      status: null,
    });
  });
});

import { describe, expect, it } from "vitest";

import { hasRole, roleBlockReason } from "./roleAccess";

describe("role access matrix", () => {
  it("allows only the role levels listed by the platform policy", () => {
    expect(hasRole("local", { role: "Viewer" }, "Operator")).toBe(false);
    expect(hasRole("local", { role: "Operator" }, "Operator")).toBe(true);
    expect(hasRole("local", { role: "Operator" }, "Engineer")).toBe(false);
    expect(hasRole("local", { role: "Engineer" }, "Engineer")).toBe(true);
    expect(hasRole("local", { role: "Admin" }, "Admin")).toBe(true);
    expect(hasRole("open", null, "Admin")).toBe(true);
    expect(hasRole("unavailable", null, "Viewer")).toBe(false);
  });

  it("gives a clear reason when identity or authentication is unavailable", () => {
    expect(roleBlockReason("local", null, "Operator")).toBe("Login required");
    expect(roleBlockReason("unavailable", null, "Viewer")).toBe(
      "Authentication state unavailable",
    );
    expect(roleBlockReason("local", { role: "Viewer" }, "Operator")).toBe(
      "Operator permission required",
    );
  });
});

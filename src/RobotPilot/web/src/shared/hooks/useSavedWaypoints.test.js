import { describe, expect, it } from "vitest";

import { waypointFromApi, yawFromPose } from "./useSavedWaypoints";

describe("saved waypoint API mapping", () => {
  it("converts stored yaw radians to the legacy map quaternion fields", () => {
    const waypoint = waypointFromApi({
      waypoint_id: "wp-1",
      map_id: "grid-hash",
      name: "Dock",
      x: 1,
      y: 2,
      yaw: Math.PI / 2,
      revision: 3,
    });

    expect(waypoint.id).toBe("wp-1");
    expect(waypoint.z).toBeCloseTo(Math.sin(Math.PI / 4));
    expect(waypoint.w).toBeCloseTo(Math.cos(Math.PI / 4));
  });

  it("converts the map's planar quaternion to yaw radians", () => {
    expect(
      yawFromPose({
        orientation: { z: Math.sin(Math.PI / 4), w: Math.cos(Math.PI / 4) },
      }),
    ).toBeCloseTo(Math.PI / 2);
  });
});

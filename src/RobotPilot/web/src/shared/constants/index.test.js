import { describe, expect, test } from "vitest";

import { AppConfig } from "./index";

describe("simulation topic contract", () => {
  test("matches the nav_liorf_neupan simulation outputs", () => {
    expect(AppConfig.SCAN_TOPIC).toBe("/scan");
    expect(AppConfig.ROBOT_POSE_TOPIC).toBe("/odometry/filtered");
    expect(AppConfig.ROBOT_VELOCITY_TOPIC).toBe("/odometry/filtered");
    expect(AppConfig.LOCALIZATION_POSE_TOPIC).toBe(
      "/liorf_localization/mapping/odometry",
    );
    expect(AppConfig.LOCALIZATION_POSE_TYPE).toBe("nav_msgs/Odometry");
    expect(AppConfig.NAVIGATION_STATE_TOPIC).toBe("/navigation/state");
    expect(AppConfig.NAVIGATION_STATE_TYPE).toBe("nav_status/NavigationStatus");
  });
});

import { T } from "../shared/i18n/i18n";
import React, { useState, useEffect, useRef } from "react";

import { useRos } from "../app/App";
import { AppConfig } from "../shared/constants/index";
import { MetricCard } from "../shared/ui/Dashboard";

const quatToYaw = (q) =>
  Math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z));

const formatVelocity = (value) => {
  const formatted = value.toFixed(1);
  return formatted === "-0.0" ? "0.0" : formatted;
};

const formatCoordinate = (value) => {
  const rounded = Math.abs(value) < 0.015 ? 0 : value;
  const formatted = rounded.toFixed(2);
  return formatted === "-0.00" ? "0.00" : formatted;
};

const angleDifference = (left, right) =>
  Math.abs(((left - right + 540) % 360) - 180);

const formatHeading = (degrees) => {
  const formatted = degrees.toFixed(1);
  return formatted === "-0.0" ? "0.0" : formatted;
};

const State = ({
  compact = false,
  showPosition = true,
  showVelocity = true,
  splitVelocityCards = false,
  separateHeading = false,
  gridClassName = "",
}) => {
  const ros = useRos();

  const [linear, setLinear] = useState("0.0");
  const [angular, setAngular] = useState("0.0");
  const [xCoord, setXCoord] = useState("—");
  const [yCoord, setYCoord] = useState("—");
  const [orientation, setOrientation] = useState("—");
  const amclActiveRef = useRef(false);
  const displayedPositionRef = useRef(null);
  const displayedHeadingRef = useRef(null);
  const linearSpeedRef = useRef(0);
  const angularSpeedRef = useRef(0);

  useEffect(() => {
    if (!ros || !window.ROSLIB) return;

    displayedPositionRef.current = null;
    displayedHeadingRef.current = null;
    amclActiveRef.current = false;
    const updatePosition = (pos, ori) => {
      if (!Number.isFinite(pos?.x) || !Number.isFinite(pos?.y) || !ori) return;
      const previous = displayedPositionRef.current;
      const stationary = Math.abs(linearSpeedRef.current) < 0.02;
      if (
        !previous ||
        !stationary ||
        Math.hypot(pos.x - previous.x, pos.y - previous.y) >= 0.03
      ) {
        displayedPositionRef.current = { x: pos.x, y: pos.y };
        setXCoord(formatCoordinate(pos.x));
        setYCoord(formatCoordinate(pos.y));
      }
      const heading = quatToYaw(ori) * (180 / Math.PI);
      const headingStationary =
        stationary && Math.abs(angularSpeedRef.current) < 0.01;
      if (
        displayedHeadingRef.current === null ||
        !headingStationary ||
        angleDifference(heading, displayedHeadingRef.current) >= 0.3
      ) {
        displayedHeadingRef.current = heading;
        setOrientation(formatHeading(heading));
      }
    };

    // 使用 AMCL 位姿（精确且经过地图校正）。
    let localizationTopic;
    if (showPosition) {
      localizationTopic = new window.ROSLIB.Topic({
        ros,
        name: AppConfig.LOCALIZATION_POSE_TOPIC,
        messageType: AppConfig.LOCALIZATION_POSE_TYPE,
      });

      localizationTopic.subscribe((msg) => {
        const pos = msg?.pose?.pose?.position;
        const ori = msg?.pose?.pose?.orientation;
        if (!pos || !ori) return;
        amclActiveRef.current = true;
        updatePosition(pos, ori);
      });
    }

    // 使用 odom 速度（连续、实时）。
    const odomTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.ROBOT_POSE_TOPIC,
      messageType: "nav_msgs/Odometry",
    });

    odomTopic.subscribe((msg) => {
      const vel = msg?.twist?.twist;
      if (!vel) return;
      linearSpeedRef.current = Number(vel.linear.x) || 0;
      angularSpeedRef.current = Number(vel.angular.z) || 0;
      setLinear(formatVelocity(vel.linear.x));
      setAngular(formatVelocity(vel.angular.z));

      // AMCL 未运行时，回退到 odom 位姿。
      if (showPosition && !amclActiveRef.current) {
        const pos = msg?.pose?.pose?.position;
        const ori = msg?.pose?.pose?.orientation;
        if (pos && ori) {
          updatePosition(pos, ori);
        }
      }
    });

    return () => {
      localizationTopic?.unsubscribe();
      odomTopic.unsubscribe();
    };
  }, [ros, showPosition]);

  return (
    <div
      className={`grid w-full min-w-0 grid-cols-1 ${
        showPosition && showVelocity ? "sm:grid-cols-2" : ""
      } ${compact ? "gap-2" : "gap-3"} ${gridClassName}`}
    >
      {showVelocity && (
        <MetricCard
          compact={compact}
          label="Linear velocity"
          value={linear}
          unit="m/s"
          meta={
            !splitVelocityCards && (
              <span
                className="font-[RobotoMono]"
                title="Angular velocity around the vertical axis"
              >
                <T>{"Angular"}</T>{" "}
                <strong className="font-semibold text-textWhiteHover">
                  {angular}
                </strong>{" "}
                rad/s
              </span>
            )
          }
        />
      )}
      {showVelocity && splitVelocityCards && (
        <MetricCard
          compact={compact}
          label="Angular"
          value={angular}
          unit="rad/s"
        />
      )}
      {showPosition && (
        <MetricCard
          compact={compact}
          label={separateHeading ? "Robot coordinates" : "Robot position"}
          value={
            separateHeading
              ? (
                <>
                  {xCoord}
                  {xCoord !== "—" && (
                    <span className="ml-px text-[0.75rem] font-medium tracking-normal text-themeTextGray">
                      m
                    </span>
                  )}
                  {", "}
                  {yCoord}
                  {yCoord !== "—" && (
                    <span className="ml-px text-[0.75rem] font-medium tracking-normal text-themeTextGray">
                      m
                    </span>
                  )}
                </>
              )
              : `${xCoord}, ${yCoord}`
          }
          unit={separateHeading ? undefined : "m"}
          meta={
            !separateHeading && (
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-themeTextGray/70">
                  <T>{"X / Y coordinates"}</T>{" "}
                </span>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-[RobotoMono]">
                    <T>{"Heading"}</T>{" "}
                    <strong className="font-semibold text-textWhiteHover">
                      {orientation}
                      {orientation !== "—" ? "°" : ""}
                    </strong>
                  </span>
                </div>
              </div>
            )
          }
        />
      )}
      {showPosition && separateHeading && (
        <MetricCard
          compact={compact}
          label="Robot heading"
          value={orientation}
          unit={orientation === "—" ? undefined : "°"}
        />
      )}
    </div>
  );
};

export default State;

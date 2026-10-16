import { useCallback, useContext, useEffect, useRef, useState } from "react";

import { AuthContext, useRos, useRosStatus } from "../../app/App";
import { AppConfig } from "../constants";
import { apiFetch } from "../api/apiFetch";

export const SAVED_WAYPOINTS_KEY = "robotpilotSavedWaypoints";
const EMPTY_WAYPOINTS = [];

export const loadWaypoints = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(SAVED_WAYPOINTS_KEY) || "[]");
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
};

export const waypointFromApi = (item) => ({
  ...item,
  id: item.waypoint_id,
  z: Math.sin(item.yaw / 2),
  w: Math.cos(item.yaw / 2),
});

export const yawFromPose = (pose) => {
  const orientation = pose?.orientation || {};
  const z = Number(orientation.z) || 0;
  const w = Number.isFinite(Number(orientation.w)) ? Number(orientation.w) : 1;
  return Math.atan2(2 * w * z, 1 - 2 * z * z);
};

/** Robot-side waypoint storage scoped to the current 2D occupancy-grid hash. */
export default function useSavedWaypoints() {
  const ros = useRos();
  const rosStatus = useRosStatus();
  const { robotId } = useContext(AuthContext);
  const [mapIdentity, setMapIdentity] = useState(null);
  const [waypoints, setWaypoints] = useState([]);
  const [legacyWaypoints] = useState(loadWaypoints);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [observedAt, setObservedAt] = useState(null);
  const [loadedMapIdentity, setLoadedMapIdentity] = useState(null);
  const requestSequence = useRef(0);
  const previousMapId = useRef("");

  useEffect(() => {
    if (!ros || !window.ROSLIB) {
      setLoading(false);
      return undefined;
    }
    const response = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.ROUTE_DATA_RESP_TOPIC,
      messageType: "std_msgs/String",
    });
    const request = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.ROUTE_DATA_REQ_TOPIC,
      messageType: "std_msgs/Empty",
    });
    const onCatalog = (message) => {
      try {
        const active = JSON.parse(message?.data || "{}").active_files || {};
        if (
          typeof active.map_id === "string" &&
          active.map_id &&
          active.map_id !== "Null"
        ) {
          setMapIdentity({
            mapId: active.map_id,
            mapVersionId: active.map_version_id || active.map_id,
          });
        } else {
          setMapIdentity(null);
        }
      } catch {
        setMapIdentity(null);
      }
    };
    response.subscribe(onCatalog);
    request.publish();
    return () => {
      response.unsubscribe(onCatalog);
      request.unadvertise?.();
    };
  }, [ros]);

  const refresh = useCallback(async () => {
    if (!mapIdentity?.mapId || !robotId) {
      setWaypoints([]);
      setError("The current 2D map identity is unavailable.");
      setLoading(false);
      return;
    }
    const sequence = ++requestSequence.current;
    setLoading(true);
    try {
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/waypoints?map_id=${encodeURIComponent(mapIdentity.mapId)}`,
      );
      const payload = await response.json();
      if (sequence === requestSequence.current) {
        const currentVersion = mapIdentity.mapVersionId || mapIdentity.mapId;
        const matching = (payload.waypoints || []).filter((item) => {
          const version = item.map_version_id || item.map_id;
          return (
            item.map_id === mapIdentity.mapId && version === currentVersion
          );
        });
        setWaypoints(matching.map(waypointFromApi));
        setLoadedMapIdentity(mapIdentity);
        setObservedAt(new Date().toISOString());
        setError("");
      }
    } catch (requestError) {
      if (sequence === requestSequence.current) {
        // Preserve the last successful snapshot and expose its stale status.
        setError(requestError.message || "Unable to load robot waypoints.");
      }
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [mapIdentity, robotId]);

  const matchesCurrentMap =
    loadedMapIdentity?.mapId === mapIdentity?.mapId &&
    loadedMapIdentity?.mapVersionId === mapIdentity?.mapVersionId;
  const visibleWaypoints = matchesCurrentMap ? waypoints : EMPTY_WAYPOINTS;

  useEffect(() => {
    window.NAV2D?.setSavedWaypoints?.(visibleWaypoints);
  }, [visibleWaypoints]);

  useEffect(() => {
    const nextIdentity = `${mapIdentity?.mapId || ""}:${
      mapIdentity?.mapVersionId || ""
    }`;
    if (previousMapId.current !== nextIdentity) {
      previousMapId.current = nextIdentity;
      setWaypoints([]);
      setLoadedMapIdentity(null);
    }
  }, [mapIdentity?.mapId, mapIdentity?.mapVersionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const addWaypoint = useCallback(
    async (name, pose, pointType = "inspection", source = "operator") => {
      if (!mapIdentity?.mapId)
        throw new Error("The current 2D map identity is unavailable.");
      const position = pose?.position || {};
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(robotId)}/waypoints`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            map_id: mapIdentity.mapId,
            map_version_id: mapIdentity.mapVersionId,
            name,
            point_type: pointType,
            source,
            x: Number(position.x),
            y: Number(position.y),
            yaw: yawFromPose(pose),
            action: "none",
            perception_type: null,
            wait_time: 0,
            enabled: true,
          }),
        },
      );
      const saved = waypointFromApi(await response.json());
      await refresh();
      return saved;
    },
    [mapIdentity, refresh, robotId],
  );

  const updateWaypoint = useCallback(
    async (waypointId, updates) => {
      const waypoint = waypoints.find((item) => item.id === waypointId);
      if (!waypoint)
        throw new Error("Waypoint is no longer in the active map.");
      await apiFetch(
        `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/waypoints/${encodeURIComponent(
          waypoint.waypoint_id || waypoint.id,
        )}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "If-Match": `"${waypoint.revision}"`,
          },
          body: JSON.stringify(updates),
        },
      );
      await refresh();
    },
    [refresh, robotId, waypoints],
  );

  const removeWaypoint = useCallback(
    async (id) => {
      const waypoint = waypoints.find((item) => item.id === id);
      if (!waypoint) return;
      await apiFetch(
        `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/waypoints/${encodeURIComponent(
          waypoint.waypoint_id || waypoint.id,
        )}`,
        {
          method: "DELETE",
          headers: { "If-Match": `"${waypoint.revision}"` },
        },
      );
      await refresh();
    },
    [refresh, robotId, waypoints],
  );

  const importLegacyWaypoints = useCallback(async () => {
    if (!mapIdentity?.mapId)
      throw new Error("The current 2D map identity is unavailable.");
    const backupKey = `${SAVED_WAYPOINTS_KEY}.backup.${encodeURIComponent(
      robotId,
    )}.${encodeURIComponent(mapIdentity.mapId)}`;
    if (!localStorage.getItem(backupKey)) {
      localStorage.setItem(backupKey, JSON.stringify(legacyWaypoints));
    }
    const existing = new Set(
      waypoints.map((item) => item.name.toLocaleLowerCase()),
    );
    let imported = 0;
    let skipped = 0;
    for (const item of legacyWaypoints) {
      const name = String(item?.name || "").trim();
      if (!name || existing.has(name.toLocaleLowerCase())) {
        skipped += 1;
        continue;
      }
      await addWaypoint(
        name,
        {
          position: { x: item.x, y: item.y },
          orientation: { z: item.z, w: item.w },
        },
        "inspection",
        "browser_import",
      );
      existing.add(name.toLocaleLowerCase());
      imported += 1;
    }
    await refresh();
    return { imported, skipped, backupKey };
  }, [addWaypoint, legacyWaypoints, mapIdentity, refresh, robotId, waypoints]);

  return {
    waypoints: visibleWaypoints,
    addWaypoint,
    removeWaypoint,
    updateWaypoint,
    mapId: mapIdentity?.mapId || "",
    mapVersionId: mapIdentity?.mapVersionId || "",
    loading,
    error,
    observedAt: matchesCurrentMap ? observedAt : null,
    stale:
      Boolean(error) ||
      rosStatus !== "connected" ||
      !loadedMapIdentity ||
      loadedMapIdentity.mapId !== mapIdentity?.mapId ||
      loadedMapIdentity.mapVersionId !== mapIdentity?.mapVersionId,
    legacyWaypoints,
    importLegacyWaypoints,
    refresh,
  };
}

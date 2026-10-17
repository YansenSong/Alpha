import { useCallback, useContext, useEffect, useRef, useState } from "react";

import { AuthContext, useRos, useRosStatus } from "../../app/App";
import { apiFetch } from "../api/apiFetch";
import { useRoleAccess } from "../auth/roleAccess";

/** Map rules are authoritative on the robot and scoped to the active map. */
export default function useKeepoutZones() {
  const ros = useRos();
  const { robotId } = useContext(AuthContext);
  const status = useRosStatus();
  const editAccess = useRoleAccess("Engineer");
  const [snapshot, setSnapshot] = useState(null);
  const [observedAt, setObservedAt] = useState(null);
  const [connected, setConnected] = useState(false);
  const [awaitingMapRules, setAwaitingMapRules] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState("");
  const [application, setApplication] = useState("IDLE");
  const [speedControl, setSpeedControl] = useState(null);
  const storedVersionRef = useRef(null);
  const commandRef = useRef(null);
  const pendingRef = useRef(null);
  const catalogMapRef = useRef("");
  const activeCatalogRef = useRef(null);
  const savedRulesRef = useRef(null);
  const savedRequestRef = useRef(0);
  const savedReadRef = useRef({ mapId: "", at: 0 });
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const stateRecent =
    connected && Boolean(observedAt) && now - Date.parse(observedAt) <= 5000;
  const snapshotFresh =
    Boolean(snapshot?.ready) &&
    connected &&
    Boolean(observedAt) &&
    !awaitingMapRules &&
    now - Date.parse(observedAt) <= 5000;

  useEffect(() => {
    if (!ros || status !== "connected" || !window.ROSLIB) {
      setConnected(false);
      commandRef.current = null;
      pendingRef.current = null;
      return undefined;
    }
    setConnected(true);
    const stateTopic = new window.ROSLIB.Topic({
      ros,
      name: "/area_rules/state",
      messageType: "std_msgs/String",
    });
    const ackTopic = new window.ROSLIB.Topic({
      ros,
      name: "/area_rules/ack",
      messageType: "std_msgs/String",
    });
    const controlTopic = new window.ROSLIB.Topic({
      ros,
      name: "/area_rules/control",
      messageType: "std_msgs/String",
    });
    const commandTopic = new window.ROSLIB.Topic({
      ros,
      name: "/area_rules/command",
      messageType: "std_msgs/String",
    });
    const catalogTopic = new window.ROSLIB.Topic({
      ros,
      name: "/ackermann/routes/catalog",
      messageType: "std_msgs/String",
    });
    commandRef.current = commandTopic;
    const showRules = (robotState = snapshotRef.current) => {
      const saved = savedRulesRef.current;
      const savedMatches =
        saved &&
        saved.map_id === (catalogMapRef.current || robotState?.map_id) &&
        (!robotState?.map_key || saved.map_key === robotState.map_key);
      const pending = Boolean(
        savedMatches && (!robotState || saved.version > robotState.version),
      );
      window.NAV2D?.setAreaRules?.(
        pending ? saved.rules : robotState?.rules || [],
      );
    };
    const readSavedRules = async (mapId, group, mapName) => {
      if (!robotId || !mapId) return;
      const last = savedReadRef.current;
      if (last.mapId === mapId && Date.now() - last.at < 4000) return;
      savedReadRef.current = { mapId, at: Date.now() };
      const requestNumber = ++savedRequestRef.current;
      try {
        const path = `/api/v1/robots/${encodeURIComponent(
          robotId,
        )}/maps/saved/by-id/${encodeURIComponent(mapId)}/rules`;
        const response = await apiFetch(path);
        const saved = await response.json();
        if (requestNumber !== savedRequestRef.current || saved.map_id !== mapId)
          return;
        savedRulesRef.current = saved;
        showRules();
      } catch {
        // Older API instances do not expose lookup by map identity yet.
        if (!group || !mapName || group === "Null" || mapName === "Null")
          return;
        const sources = group === "maps" ? ["project", "ui"] : ["ui"];
        for (const source of sources) {
          try {
            const path = `/api/v1/robots/${encodeURIComponent(
              robotId,
            )}/maps/saved/${encodeURIComponent(group)}/${encodeURIComponent(
              mapName,
            )}/rules?source=${source}`;
            const response = await apiFetch(path);
            const saved = await response.json();
            if (requestNumber !== savedRequestRef.current) return;
            if (
              saved.map_key !== snapshotRef.current?.map_key ||
              snapshotRef.current?.map_id !== mapId
            )
              continue;
            savedRulesRef.current = { ...saved, map_id: mapId };
            showRules();
            return;
          } catch {
            // Try the next catalog source.
          }
        }
      }
    };
    catalogTopic.subscribe((message) => {
      try {
        const active = JSON.parse(message.data || "{}").active_files || {};
        const nextMapId =
          active.map_id && active.map_id !== "Null" ? active.map_id : "";
        if (nextMapId !== catalogMapRef.current) {
          savedRequestRef.current += 1;
          savedRulesRef.current = null;
          setAwaitingMapRules(true);
          window.NAV2D?.setAreaRules?.([]);
        }
        catalogMapRef.current = nextMapId;
        activeCatalogRef.current = active;
        readSavedRules(nextMapId, active.group, active.map);
      } catch {
        // Catalog messages are informational; the robot rule state remains authoritative.
      }
    });
    stateTopic.subscribe((message) => {
      try {
        const next = JSON.parse(message.data);
        if (!Array.isArray(next.rules)) return;
        if (catalogMapRef.current && next.map_id !== catalogMapRef.current) {
          setAwaitingMapRules(true);
          window.NAV2D?.setAreaRules?.([]);
          return;
        }
        setSnapshot(next);
        if (
          storedVersionRef.current !== null &&
          next.version >= storedVersionRef.current
        ) {
          setApplication(
            next.version === storedVersionRef.current && next.navigation_applied
              ? "APPLIED"
              : "STORED",
          );
        }
        setObservedAt(new Date().toISOString());
        setAwaitingMapRules(false);
        setError("");
        showRules(next);
      } catch {
        setError("无法解析机器人返回的地图规则");
      }
    });
    ackTopic.subscribe((message) => {
      try {
        const ack = JSON.parse(message.data);
        if (ack.request_id !== pendingRef.current) return;
        pendingRef.current = null;
        setError(ack.ok ? "" : ack.error || "地图规则保存失败");
        if (ack.ok) {
          storedVersionRef.current = ack.stored_version;
          setApplication("STORED");
        } else {
          setApplication("FAILED");
        }
      } catch {
        // Ignore unrelated or malformed acknowledgements.
      }
    });
    controlTopic.subscribe((message) => {
      try {
        setSpeedControl({
          ...JSON.parse(message.data),
          observedAt: Date.now(),
        });
      } catch {
        setSpeedControl(null);
      }
    });
    return () => {
      stateTopic.unsubscribe();
      ackTopic.unsubscribe();
      controlTopic.unsubscribe();
      catalogTopic.unsubscribe();
      commandRef.current = null;
      pendingRef.current = null;
      savedRequestRef.current += 1;
    };
  }, [ros, status, robotId]);

  const send = useCallback(
    (action, rule) => {
      if (!editAccess.allowed) {
        setError(editAccess.reason);
        return false;
      }
      if (
        !snapshotFresh ||
        !snapshot?.map_key ||
        !commandRef.current ||
        pendingRef.current
      ) {
        setError("地图规则服务未就绪，或仍在等待上一次操作");
        return false;
      }
      setError("");
      setApplication("PENDING");
      const requestId = `web-area-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2)}`;
      pendingRef.current = requestId;
      commandRef.current.publish(
        new window.ROSLIB.Message({
          data: JSON.stringify({
            request_id: requestId,
            map_key: snapshot.map_key,
            map_id: snapshot.map_id,
            map_version_id: snapshot.map_version_id,
            expected_version: snapshot.version,
            action,
            rule,
          }),
        }),
      );
      // Lost acknowledgements must not leave the editor locked forever.
      setTimeout(() => {
        if (pendingRef.current === requestId) {
          pendingRef.current = null;
          setError("未收到机器人确认，请检查连接和规则列表");
          setApplication("FAILED");
        }
      }, 5000);
      return true;
    },
    [editAccess, snapshot, snapshotFresh],
  );

  return {
    rules: snapshot?.rules || [],
    ready: snapshotFresh,
    stateRecent,
    gridMapId: snapshot?.grid_map_id || null,
    mapKey: snapshot?.map_key || null,
    version: snapshot?.version ?? null,
    mapId: snapshot?.map_id || null,
    mapVersionId: snapshot?.map_version_id || null,
    observedAt,
    stale:
      !connected ||
      awaitingMapRules ||
      !observedAt ||
      now - Date.parse(observedAt) > 5000,
    error,
    application,
    navigationApplied: Boolean(snapshot?.navigation_applied) && snapshotFresh,
    navigationHold: Boolean(snapshot?.navigation_hold) || !snapshotFresh,
    navigationHoldReason: snapshot?.navigation_hold_reason || "WAITING_RULES",
    configuredSpeedLimit:
      now - (speedControl?.observedAt || 0) <= 500
        ? speedControl?.configured_speed_limit_mps ?? null
        : null,
    constrainedSpeedLimit:
      now - (speedControl?.observedAt || 0) <= 500
        ? speedControl?.speed_limit ?? null
        : null,
    actualSpeed:
      now - (speedControl?.observedAt || 0) <= 500
        ? speedControl?.actual_speed_mps ?? null
        : null,
    canEdit: editAccess.allowed,
    permissionReason: editAccess.reason,
    upsertRule: (rule) => send("upsert", rule),
    setRuleEnabled: (id, enabled) => send("set_enabled", { id, enabled }),
    deleteRule: (id) => send("delete", { id }),
  };
}

import { useCallback, useContext, useEffect, useRef, useState } from "react";

import { AuthContext } from "../../app/App";
import { apiFetch } from "../api/apiFetch";

const POLL_MS = 5000;
const STALE_MS = 12000;

export default function useRobotStatus() {
  const { robotId } = useContext(AuthContext);
  const [snapshot, setSnapshot] = useState(null);
  const [receivedAt, setReceivedAt] = useState(0);
  const [error, setError] = useState("");
  const refreshRef = useRef(null);

  const refresh = useCallback(async () => {
    if (!robotId) return;
    try {
      const response = await apiFetch(
        `/api/v1/robots/${encodeURIComponent(robotId)}/status`,
        { cache: "no-store" },
      );
      setSnapshot(await response.json());
      setReceivedAt(Date.now());
      setError("");
    } catch (cause) {
      setError(cause.message || "Robot status unavailable.");
    }
  }, [robotId]);
  refreshRef.current = refresh;

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!robotId || typeof EventSource === "undefined") return undefined;
    const stream = new EventSource(
      `/api/v1/robots/${encodeURIComponent(robotId)}/events`,
      { withCredentials: true },
    );
    stream.addEventListener("robot_state", () => refreshRef.current?.());
    return () => stream.close();
  }, [robotId]);

  return {
    snapshot,
    stale: !receivedAt || Date.now() - receivedAt > STALE_MS,
    receivedAt,
    error,
    refresh,
  };
}

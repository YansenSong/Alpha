import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { agentReducer, initialAgentState } from "./agentReducer";

const newId = () => crypto.randomUUID();
function readSaved(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key));
    return {
      active: value?.active ?? null,
      sessions: Array.isArray(value?.sessions)
        ? value.sessions.filter(
            (s) => typeof s.id === "string" && /^[0-9a-f]{64}$/.test(s.token),
          )
        : [],
    };
  } catch {
    return { active: null, sessions: [] };
  }
}

export default function useAgentSocket({ enabled, storageKey }) {
  const [state, dispatch] = useReducer(agentReducer, initialAgentState);
  const [storageWarning, setStorageWarning] = useState("");
  const [deletingId, setDeletingId] = useState(null);
  const deleteRef = useRef(null);
  const deleteTimer = useRef(null);
  const [saved, setSaved] = useState(() => readSaved(storageKey));
  const savedRef = useRef(saved);
  const socketRef = useRef(null);
  const commandTimer = useRef(null);
  const locked = useRef(false);
  const [target, setTarget] = useState(() => ({
    id: readSaved(storageKey).active,
    create: false,
    nonce: 0,
  }));
  const persist = useCallback(
    (update) => {
      const next = update(savedRef.current);
      savedRef.current = next;
      setSaved(next);
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        setStorageWarning("浏览器无法保存会话凭证；关闭页面后可能无法恢复。");
      }
    },
    [storageKey],
  );

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let socket;
    let retryTimer;
    let handshakeTimer;
    let retries = 0;
    let boundId = target.id;
    let shouldCreate = target.create;
    let awaitingBind = false;
    let failedBind = false;
    dispatch({ type: "reset" });
    const connect = () => {
      if (disposed) return;
      dispatch({
        type: "connection",
        value: retries ? "reconnecting" : "connecting",
      });
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(
        `${protocol}//${window.location.host}/agent-api/ws`,
      );
      socketRef.current = socket;
      handshakeTimer = setTimeout(() => socket.close(), 10000);
      socket.onopen = () => {
        if (disposed) return;
        clearTimeout(handshakeTimer);
        dispatch({ type: "connection", value: "connected" });
        const credential = savedRef.current.sessions.find(
          (s) => s.id === boundId,
        );
        let message;
        if (credential)
          message = {
            type: "session.resume",
            session_id: credential.id,
            resume_token: credential.token,
          };
        else if (shouldCreate) {
          message = { type: "session.create" };
          shouldCreate = false;
        } else if (boundId) {
          failedBind = true;
          dispatch({
            type: "error",
            message: "找不到该会话的恢复凭证，请新建会话。",
          });
        }
        if (message) {
          awaitingBind = true;
          dispatch({ type: "connection", value: "binding" });
          socket.send(JSON.stringify({ ...message, request_id: newId() }));
          handshakeTimer = setTimeout(() => socket.close(), 20000);
        }
      };
      socket.onmessage = ({ data }) => {
        if (disposed) return;
        let event;
        try {
          event = JSON.parse(data);
        } catch {
          return;
        }
        if (event.type === "session.deleted") {
          const id = event.session_id;
          if (deleteRef.current?.id === id) {
            clearTimeout(deleteTimer.current);
            deleteRef.current = null;
            setDeletingId(null);
          }
          const wasCurrent = boundId === id;
          persist((old) => {
            const sessions = old.sessions.filter((entry) => entry.id !== id);
            return {
              sessions,
              active: old.active === id ? sessions[0]?.id ?? null : old.active,
            };
          });
          if (wasCurrent) {
            dispatch({ type: "reset" });
            setTarget({
              id: savedRef.current.active,
              create: false,
              nonce: newId(),
            });
          }
          return;
        }
        if (
          event.type === "request.error" &&
          event.request_id === deleteRef.current?.requestId
        ) {
          clearTimeout(deleteTimer.current);
          deleteRef.current = null;
          setDeletingId(null);
        }
        if (event.type === "session.snapshot") {
          clearTimeout(handshakeTimer);
          clearTimeout(commandTimer.current);
          locked.current = false;
          awaitingBind = false;
          retries = 0;
          boundId = event.session_id;
          if (event.resume_token) {
            persist((old) => ({
              active: boundId,
              sessions: [
                {
                  id: boundId,
                  token: event.resume_token,
                  label: `会话 ${new Date().toLocaleString("zh-CN", {
                    month: "numeric",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}`,
                },
                ...old.sessions.filter((s) => s.id !== boundId),
              ],
            }));
          }
        }
        if (event.type === "request.error" && awaitingBind) {
          failedBind = true;
          awaitingBind = false;
          dispatch({ type: "connection", value: "connected" });
          clearTimeout(handshakeTimer);
        }
        if (
          [
            "chat.accepted",
            "request.error",
            "request.ack",
            "agent.settled",
          ].includes(event.type)
        ) {
          clearTimeout(commandTimer.current);
          locked.current = false;
        }
        dispatch({ type: "event", event });
      };
      socket.onerror = () => {}; // close drives reconnection; raw browser events contain no useful diagnostic.
      socket.onclose = () => {
        if (disposed) return;
        clearTimeout(handshakeTimer);
        clearTimeout(commandTimer.current);
        clearTimeout(deleteTimer.current);
        deleteRef.current = null;
        setDeletingId(null);
        locked.current = false;
        dispatch({
          type: "connection",
          value: "disconnected",
          error: "Agent Gateway 连接断开，正在重连；已提交的消息不会自动重发。",
        });
        if (!failedBind)
          retryTimer = setTimeout(
            connect,
            Math.min(1000 * 2 ** retries++, 15000),
          );
      };
    };
    connect();
    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      clearTimeout(handshakeTimer);
      clearTimeout(commandTimer.current);
      clearTimeout(deleteTimer.current);
      deleteRef.current = null;
      setDeletingId(null);
      locked.current = false;
      socketRef.current = null;
      socket?.close();
    };
  }, [enabled, target, persist]);

  const deleteSession = useCallback((id) => {
    const credential = savedRef.current.sessions.find(
      (entry) => entry.id === id,
    );
    const socket = socketRef.current;
    if (
      !credential ||
      socket?.readyState !== WebSocket.OPEN ||
      deleteRef.current
    ) {
      dispatch({ type: "error", message: "请等待 Gateway 连接后再删除会话。" });
      return false;
    }
    const requestId = newId();
    deleteRef.current = { id, requestId };
    setDeletingId(id);
    socket.send(
      JSON.stringify({
        type: "session.delete",
        request_id: requestId,
        session_id: id,
        resume_token: credential.token,
      }),
    );
    deleteTimer.current = setTimeout(() => {
      deleteRef.current = null;
      setDeletingId(null);
      dispatch({ type: "error", message: "删除确认超时，请检查连接后重试。" });
    }, 20000);
    return true;
  }, []);
  const selectSession = useCallback(
    (id) => {
      persist((old) => ({ ...old, active: id }));
      setTarget({ id, create: false, nonce: newId() });
    },
    [persist],
  );
  const createSession = useCallback(() => {
    setTarget({ id: null, create: true, nonce: newId() });
  }, []);
  const send = useCallback(
    (type, text) => {
      const socket = socketRef.current;
      if (
        socket?.readyState !== WebSocket.OPEN ||
        state.connection !== "ready" ||
        !state.sessionId ||
        locked.current
      )
        return false;
      if (
        type === "chat.prompt" &&
        (state.status === "running" || !text.trim())
      )
        return false;
      const id = newId();
      locked.current = true;
      dispatch({ type: "pending", value: { id, text, type } });
      socket.send(
        JSON.stringify({
          type,
          request_id: id,
          session_id: state.sessionId,
          ...(text ? { text } : {}),
        }),
      );
      commandTimer.current = setTimeout(() => {
        dispatch({
          type: "error",
          message: "请求确认超时，正在重新同步会话；请先核对历史记录。",
        });
        socket.close();
      }, 20000);
      return true;
    },
    [state.connection, state.sessionId, state.status],
  );
  return {
    ...state,
    error: state.error || storageWarning,
    sessions: saved.sessions,
    deletingId,
    deleteSession,
    createSession,
    selectSession,
    prompt: (text) => send("chat.prompt", text),
    abort: () => send("chat.abort"),
  };
}

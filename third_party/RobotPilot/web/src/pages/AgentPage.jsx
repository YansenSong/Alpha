import React, { useContext, useEffect, useMemo, useRef, useState } from "react";
import { AuthContext } from "../app/App";
import {
  DashboardCard,
  SectionHeader,
  StatusBadge,
} from "../shared/ui/Dashboard";
import { groupMessages } from "../features/agent/groupMessages";
import ToolCallCard from "../features/agent/ToolCallCard";
import useTranscriptScroll from "../features/agent/useTranscriptScroll";
import AssistantMessage from "../features/agent/AssistantMessage";
import useAgentSocket from "../features/agent/useAgentSocket";
import "../features/agent/agent.css";

const states = {
  done: "已完成",
  running: "执行中",
  error: "失败",
  aborted: "已停止",
  interrupted: "已中断",
};
const connections = {
  binding: "正在加载会话",
  connecting: "正在连接",
  connected: "已连接 · 请选择会话",
  ready: "已连接",
  reconnecting: "正在重连",
  disconnected: "连接断开",
};

function AgentWorkspace({ robotId }) {
  const agent = useAgentSocket({
    enabled: true,
    storageKey: `robotpilot-agent-v1:${robotId}`,
  });
  const [draft, setDraft] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const scroll = useTranscriptScroll(agent.sessionId, agent.items);
  const inputRef = useRef(null);
  const running = agent.status === "running";
  const ready = agent.connection === "ready";
  const sending = agent.pending?.type === "chat.prompt";
  const stopping = agent.pending?.type === "chat.abort";
  const messages = useMemo(() => groupMessages(agent.items), [agent.items]);

  useEffect(() => {
    if (agent.lastAccepted)
      setDraft((current) =>
        current === agent.lastAccepted.text ? "" : current,
      );
  }, [agent.lastAccepted]);

  const submit = (event) => {
    event.preventDefault();
    if (draft.trim() && !running && !agent.pending) agent.prompt(draft);
  };
  return (
    <div className="agent-workspace">
      <DashboardCard
        as="aside"
        className="agent-sessions p-3"
        aria-label="Agent 会话"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">会话记录</h2>
          <button
            type="button"
            className="agent-button px-3 text-sm"
            disabled={agent.connection === "binding" || !!agent.deletingId}
            onClick={agent.createSession}
          >
            新建会话
          </button>
        </div>
        {deleteTarget && (
          <div
            className="agent-delete-confirm"
            role="group"
            aria-label="确认删除会话"
          >
            <p className="text-sm leading-6">
              删除“{deleteTarget.label}”？聊天记录将永久删除。
            </p>
            <div className="mt-3 flex gap-2">
              <button
                className="agent-button px-3"
                type="button"
                onClick={() => setDeleteTarget(null)}
              >
                取消
              </button>
              <button
                className="agent-button px-3 text-statusRed"
                type="button"
                onClick={() => {
                  agent.deleteSession(deleteTarget.id);
                  setDeleteTarget(null);
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        )}
        <nav aria-label="选择聊天会话" className="agent-session-list">
          {agent.sessions.map((session) => (
            <div key={session.id} className="agent-session-row">
              <button
                type="button"
                className="agent-session min-w-0 flex-1"
                aria-current={
                  agent.sessionId === session.id ? "true" : undefined
                }
                disabled={!!agent.deletingId}
                onClick={() => agent.selectSession(session.id)}
              >
                <span className="block truncate text-sm">{session.label}</span>
                <span className="mt-1 block font-mono text-xs text-themeTextGray">
                  {session.id.slice(0, 8)}
                </span>
              </button>
              <button
                type="button"
                className="agent-session-delete"
                aria-label={`删除${session.label}`}
                disabled={!!agent.deletingId}
                onClick={() => setDeleteTarget(session)}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  aria-hidden="true"
                >
                  <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7" />
                </svg>
              </button>
            </div>
          ))}
          {!agent.sessions.length && (
            <p className="px-2 py-4 text-sm leading-6 text-themeTextGray">
              新建会话，开始与 RoboAgent 对话。
            </p>
          )}
        </nav>
        <p className="mt-4 text-xs leading-6 text-themeTextGray">
          历史保存在本机 Gateway。此浏览器保存恢复凭证，请使用可信设备。
        </p>
      </DashboardCard>

      <DashboardCard className="agent-chat" aria-label="RoboAgent">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-borderSubtle/20 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">
              Pi Agent{" "}
              <span className="ml-2 font-normal text-themeTextGray">
                / {agent.sessionId?.slice(0, 8) || "尚未选择会话"}
              </span>
            </h2>
            <p className="mt-1 text-xs text-themeTextGray">
              {running
                ? "正在处理你的请求"
                : agent.status === "interrupted"
                ? "上次运行已中断，可以继续对话"
                : "项目能力查询 · Mock 工具"}
            </p>
          </div>
          <div role="status">
            <StatusBadge
              status={ready ? "connected" : "warning"}
              label={connections[agent.connection]}
            />
          </div>
        </div>
        {agent.error && (
          <div
            role="alert"
            className="mx-4 mt-3 rounded-lg border border-statusYellow/40 bg-statusYellow/10 p-3 text-sm leading-6"
          >
            {agent.error}
          </div>
        )}
        <div
          ref={scroll.listRef}
          className="agent-messages"
          role="region"
          aria-label="对话记录"
          aria-busy={running}
          onScroll={scroll.onScroll}
          onWheel={scroll.onWheel}
          onKeyDown={scroll.onKeyDown}
        >
          <div ref={scroll.bodyRef} className="agent-transcript">
            {!agent.items.length && (
              <div className="m-auto max-w-lg px-2 py-12 text-center">
                <div className="mb-4 font-mono text-xs uppercase tracking-[0.2em] text-themeTextGray">
                  Alpha × Pi
                </div>
                <h3 className="mb-3 text-xl font-semibold">从了解项目开始</h3>
                <p className="text-sm leading-7 text-themeTextGray">
                  查询项目能力、查看工具执行过程，并在多轮对话中继续探索。当前没有连接真实机器人。
                </p>
                {!agent.sessionId ? (
                  <button
                    className="agent-button mt-6 px-5"
                    type="button"
                    disabled={
                      agent.connection === "binding" || !!agent.deletingId
                    }
                    onClick={agent.createSession}
                  >
                    新建对话
                  </button>
                ) : (
                  <button
                    className="agent-suggestion mt-6"
                    type="button"
                    onClick={() => {
                      setDraft(
                        "你好，请调用工具检查一下，目前支持哪些 Alpha 项目能力？",
                      );
                      inputRef.current?.focus();
                    }}
                  >
                    目前支持哪些项目能力？
                  </button>
                )}
              </div>
            )}
            {messages.map((message) => (
              <article
                key={message.id}
                className={`agent-message ${
                  message.role === "user" ? "agent-message--user" : ""
                }`}
              >
                {message.role !== "user" && (
                  <div className="mb-2 flex items-center gap-3 text-xs text-themeTextGray">
                    <span className="agent-avatar" aria-hidden="true">
                      π
                    </span>
                    <span className="agent-author">Pi Agent</span>
                    {message.status !== "done" && (
                      <span>{states[message.status] || message.status}</span>
                    )}
                  </div>
                )}
                <div className="agent-reply-parts">
                  {message.parts.map((item) =>
                    item.role === "tool" ? (
                      <ToolCallCard key={item.id} item={item} />
                    ) : item.role === "user" ? (
                      <div key={item.id} className="agent-user-text">
                        {item.text}
                      </div>
                    ) : (
                      <AssistantMessage
                        key={item.id}
                        text={item.text}
                        status={item.status}
                        showActions={
                          message.status !== "running" &&
                          item.id === message.parts.at(-1)?.id
                        }
                        copyText={
                          item.id === message.parts.at(-1)?.id
                            ? message.parts
                                .filter(
                                  (part) =>
                                    part.role === "assistant" &&
                                    part.text?.trim(),
                                )
                                .map((part) => part.text)
                                .join("\n\n")
                            : undefined
                        }
                      />
                    ),
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
        {!scroll.following && (
          <button
            className="agent-button mx-auto mb-2 px-4 text-xs"
            type="button"
            onClick={scroll.jumpToLatest}
          >
            回到最新消息
          </button>
        )}
        <form className="agent-composer" onSubmit={submit}>
          <label htmlFor="agent-prompt" className="sr-only">
            发送给 Pi
          </label>
          <div className="agent-input-frame">
            <textarea
              ref={inputRef}
              id="agent-prompt"
              value={draft}
              rows={2}
              maxLength={12000}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  submit(event);
                }
              }}
              placeholder={
                agent.sessionId ? "输入你的问题…" : "请先新建或选择会话"
              }
              className="agent-input"
            />
            <div className="agent-composer-action">
              {running ? (
                <button
                  className="agent-button px-5"
                  type="button"
                  disabled={!ready || stopping}
                  onClick={agent.abort}
                >
                  {stopping ? "正在停止…" : "停止生成"}
                </button>
              ) : (
                <button
                  className="agent-button agent-button--primary px-6"
                  type="submit"
                  disabled={!ready || !draft.trim() || !!agent.pending}
                >
                  {sending ? "提交中…" : "发送消息"}
                </button>
              )}
            </div>
          </div>
        </form>
      </DashboardCard>
    </div>
  );
}

export default function AgentPage() {
  const { mode, robotId } = useContext(AuthContext);
  const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const enabled = import.meta.env.DEV && local && mode === "open";
  return (
    <div className="agent-page">
      <SectionHeader
        eyebrow="Project intelligence"
        title="RoboAgent"
        action={<StatusBadge status="info" label="Mock 模式" />}
      />
      {enabled ? (
        <AgentWorkspace key={robotId} robotId={robotId} />
      ) : (
        <DashboardCard className="p-6 text-sm leading-7">
          Agent 页面目前仅在本机 Vite 开发服务的 open
          模式启用。请使用项目开发启动脚本，并单独启动 Pi Gateway。
        </DashboardCard>
      )}
    </div>
  );
}

import React, { useId, useMemo, useState } from "react";

const states = {
  done: "已完成",
  running: "执行中",
  error: "失败",
  aborted: "已停止",
  interrupted: "已中断",
};
export default function ToolCallCard({ item }) {
  const [expanded, setExpanded] = useState(null);
  const open = expanded ?? item.status === "error";
  const panelId = useId();
  const result = useMemo(() => {
    if (!item.text)
      return item.status === "running" ? "正在等待工具返回结果…" : "未返回结果";
    try {
      return JSON.stringify(JSON.parse(item.text), null, 2);
    } catch {
      return item.text;
    }
  }, [item.text, item.status]);
  return (
    <section className="agent-tool" data-status={item.status}>
      <button
        type="button"
        className="agent-tool-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setExpanded(!open)}
      >
        <span className="agent-tool-state" aria-hidden="true">
          {item.status === "running" ? (
            <span className="agent-tool-spinner" />
          ) : (
            <svg
              width="14"
              height="14"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            >
              <path
                d={
                  item.status === "done"
                    ? "m4 10 4 4 8-8"
                    : "m6 6 8 8M14 6l-8 8"
                }
              />
            </svg>
          )}
        </span>
        <span className="agent-tool-label">
          <span>
            {item.name === "get_alpha_info" ? "查询项目能力" : "执行工具"}
          </span>
          <code>{item.name}</code>
        </span>
        <span className="agent-tool-status">
          {states[item.status] || item.status}
        </span>
        <svg
          className="agent-tool-chevron"
          width="14"
          height="14"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          aria-hidden="true"
        >
          <path d="m7 4 6 6-6 6" />
        </svg>
      </button>
      <div id={panelId} hidden={!open} className="agent-tool-result">
        <div className="agent-tool-result-label">工具结果</div>
        <pre tabIndex={0} aria-label={`${item.name} 执行结果`}>
          {result}
        </pre>
      </div>
    </section>
  );
}

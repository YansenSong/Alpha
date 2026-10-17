import React, {
  Children,
  isValidElement,
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import cpp from "highlight.js/lib/languages/cpp";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

for (const [name, language] of Object.entries({
  bash,
  cpp,
  javascript,
  json,
  python,
  typescript,
  xml,
  yaml,
})) {
  hljs.registerLanguage(name, language);
}
const plugins = [remarkGfm];

function CopyButton({ text, label = "复制代码" }) {
  const [feedback, setFeedback] = useState("");
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setFeedback("已复制");
    } catch {
      setFeedback("复制失败，请手动选择文本");
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setFeedback(""), 2500);
  };
  return (
    <span className="agent-copy-control">
      <button
        type="button"
        className="agent-copy"
        onClick={copy}
        aria-label={label}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          aria-hidden="true"
        >
          <rect x="8" y="8" width="12" height="12" rx="2" />
          <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
        </svg>
        {feedback === "已复制" ? feedback : label}
      </button>
      <span
        className={
          feedback.startsWith("复制失败") ? "agent-copy-error" : "sr-only"
        }
        role="status"
      >
        {feedback}
      </span>
    </span>
  );
}

function CodeBlock({ children }) {
  const [wrap, setWrap] = useState(false);
  const child = Children.toArray(children).find(isValidElement);
  const code = String(child?.props.children ?? "").replace(/\n$/, "");
  const language = /language-([\w+-]+)/
    .exec(child?.props.className ?? "")?.[1]
    ?.toLowerCase();
  const highlighted = useMemo(() => {
    // Bound synchronous highlighting cost; unknown languages remain plain text.
    if (!language || !hljs.getLanguage(language) || code.length > 30000)
      return null;
    return hljs.highlight(code, { language, ignoreIllegals: true }).value;
  }, [code, language]);
  return (
    <div className="agent-code-block">
      <div className="agent-code-header">
        <span>{language || "text"}</span>
        <div className="agent-code-actions">
          <button
            type="button"
            className="agent-copy"
            aria-label="代码自动换行"
            aria-pressed={wrap}
            onClick={() => setWrap(!wrap)}
          >
            换行
          </button>
          <CopyButton text={code} />
        </div>
      </div>
      <pre
        className={wrap ? "agent-code-wrap" : undefined}
        tabIndex={0}
        aria-label={`${language || "文本"}代码`}
      >
        {highlighted === null ? (
          <code>{code}</code>
        ) : (
          <code
            className="hljs"
            dangerouslySetInnerHTML={{ __html: highlighted }}
          />
        )}
      </pre>
    </div>
  );
}

function safeUrl(value) {
  return /^(https?:\/\/|mailto:)/i.test(value) ? value : "";
}
function MessageLink({ href, children }) {
  if (!href) return <span>{children}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      referrerPolicy="no-referrer"
    >
      {children}
    </a>
  );
}
function MarkdownTable({ children }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className={`agent-table-frame ${expanded ? "agent-table-expanded" : ""}`}
    >
      <div className="agent-table-toolbar">
        <span>表格</span>
        <button
          type="button"
          className="agent-copy"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "收起表格" : "展开表格"}
        </button>
      </div>
      <div
        className="agent-table-scroll"
        role="region"
        aria-label="回复中的表格"
        tabIndex={0}
      >
        <table>{children}</table>
      </div>
    </div>
  );
}

const components = {
  pre: CodeBlock,
  a: MessageLink,
  img: ({ src, alt }) => (
    <MessageLink href={src}>{alt ? `图片：${alt}` : "查看图片"}</MessageLink>
  ),
  table: MarkdownTable,
  h1: ({ children }) => <h3 className="agent-md-title">{children}</h3>,
  h2: ({ children }) => <h4 className="agent-md-heading">{children}</h4>,
  h3: ({ children }) => <h5 className="agent-md-subheading">{children}</h5>,
};

const AssistantMessage = memo(function AssistantMessage({
  text,
  status,
  showActions = true,
  copyText,
}) {
  const streaming = status === "running";
  const hasText = Boolean(text?.trim());
  if (!hasText && status === "done") return null;
  return (
    <div className="agent-assistant-content">
      {hasText ? (
        <div className="agent-markdown">
          <Markdown
            remarkPlugins={plugins}
            components={components}
            urlTransform={safeUrl}
            skipHtml
          >
            {text}
          </Markdown>
        </div>
      ) : (
        <div className="agent-thinking">
          <span className="agent-thinking-dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>
            {streaming
              ? "正在思考…"
              : status === "error"
              ? "本次回复生成失败"
              : "本次回复已停止或中断"}
          </span>
        </div>
      )}
      {streaming && hasText && (
        <div className="agent-stream-status" role="status">
          <span className="agent-stream-dot" aria-hidden="true" />
          正在生成
        </div>
      )}
      {showActions && !streaming && hasText && (
        <div className="agent-reply-actions">
          <CopyButton text={copyText ?? text} label="复制回复" />
        </div>
      )}
    </div>
  );
});
export default AssistantMessage;

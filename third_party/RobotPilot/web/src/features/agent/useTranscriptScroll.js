import { useCallback, useLayoutEffect, useRef, useState } from "react";

// Follow is reader intent, not merely a distance recomputed after content grows.
export default function useTranscriptScroll(sessionId, revision) {
  const listRef = useRef(null);
  const bodyRef = useRef(null);
  const active = useRef(true);
  const sampledTop = useRef(0);
  const [following, setFollowing] = useState(true);
  const setFollow = useCallback((value) => {
    active.current = value;
    setFollowing(value);
  }, []);
  const scrollToBottom = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight);
    sampledTop.current = el.scrollTop;
  }, []);
  useLayoutEffect(() => {
    setFollow(true);
    scrollToBottom();
  }, [sessionId, setFollow, scrollToBottom]);
  useLayoutEffect(() => {
    if (active.current) scrollToBottom();
  }, [revision, scrollToBottom]);
  useLayoutEffect(() => {
    if (typeof ResizeObserver === "undefined" || !bodyRef.current) return;
    const observer = new ResizeObserver(() => {
      if (active.current) scrollToBottom();
    });
    observer.observe(bodyRef.current);
    if (listRef.current) observer.observe(listRef.current);
    return () => observer.disconnect();
  }, [scrollToBottom]);
  const onScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    // Layout growth without reader movement must not disable following.
    if (Math.abs(el.scrollTop - sampledTop.current) > 1) {
      setFollow(el.scrollHeight - el.clientHeight - el.scrollTop < 64);
    }
    sampledTop.current = el.scrollTop;
  }, [setFollow]);
  return {
    listRef,
    bodyRef,
    following,
    onScroll,
    onWheel: (event) => {
      if (event.deltaY < 0) setFollow(false);
    },
    onKeyDown: (event) => {
      if (["ArrowUp", "PageUp", "Home"].includes(event.key)) setFollow(false);
    },
    jumpToLatest: () => {
      setFollow(true);
      scrollToBottom();
    },
  };
}

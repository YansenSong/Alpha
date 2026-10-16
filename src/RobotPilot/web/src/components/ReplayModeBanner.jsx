import { T } from "../shared/i18n/i18n";
import React, { useEffect, useState } from "react";
import { fetchRecordingsStatus } from "../features/recordings/recordingsApi";

const POLL_MS = 3000;

/**
 * rosbag 回放期间无论当前位于哪个页面都始终显示。回放可从 Recordings 页面启动，但操作员可能随后切换到其他页面；
 * 如果没有横幅，其他页面的遥测数据就会与实时机器人数据无法区分。此横幅不可关闭，
 * 用于避免将回放数据误认为实时数据。
 */
const ReplayModeBanner = () => {
  const [replay, setReplay] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      fetchRecordingsStatus()
        .then((data) => {
          if (!cancelled) setReplay(data.replay || null);
        })
        .catch(() => {
          if (!cancelled) setReplay(null);
        });
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!replay) return null;

  return (
    <div className="mb-3 flex items-center gap-3 rounded-xl border border-statusYellow/40 bg-statusYellow/10 px-4 py-2 font-[RobotoMono] text-xs text-statusYellow">
      <span className="flex h-2 w-2 shrink-0 rounded-full bg-statusYellow" />
      <span className="flex-1">
        <span className="font-bold uppercase tracking-wider">
          <T>{"Replay mode"}</T>
        </span>{" "}
        <T>{"— you're viewing recorded telemetry, not a live robot."}</T>{" "}
        {replay.paused ? <T>{"(paused)"}</T> : ""}
      </span>
    </div>
  );
};

export default ReplayModeBanner;

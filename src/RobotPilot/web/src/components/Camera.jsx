import React, { useEffect, useCallback, useState } from "react";
import {
  CAMERA_TOPIC_OPTIONS,
  DEFAULT_CAMERA_TOPIC,
} from "../shared/constants/index";
import { EmptyState, LoadingSkeleton } from "../shared/ui/Dashboard";
import { useT } from "../shared/i18n/i18n";

const Camera = () => {
  const { t } = useT();
  const [videoSrc, setVideoSrc] = useState("");
  const [topic, setTopic] = useState(DEFAULT_CAMERA_TOPIC);
  const [quality, setQuality] = useState("balanced");
  const [status, setStatus] = useState("idle");

  const streamProfiles = {
    low: { quality: 25, width: 320, height: 240 },
    balanced: { quality: 45, width: 480, height: 360 },
    high: { quality: 70, width: 640, height: 480 },
  };

  const tryToConnectToCamera = useCallback(async () => {
    const profile = streamProfiles[quality] || streamProfiles.balanced;
    const params = new URLSearchParams({
      topic,
      quality: String(profile.quality),
      width: String(profile.width),
      height: String(profile.height),
    });
    const videoSrcString = `/api/camera/stream?${params}`;
    setStatus("loading");
    setVideoSrc(videoSrcString);
    // 有意不将 streamProfiles 放入依赖项：它每次渲染都会创建新的对象字面量，但其值是静态的，因此无需作为依赖。
  }, [quality, topic]);

  useEffect(() => {
    setVideoSrc("");
    setStatus("idle");
  }, [quality, topic]);

  useEffect(() => {
    tryToConnectToCamera();
  }, [tryToConnectToCamera]);

  const stopCamera = () => {
    setVideoSrc("");
    setStatus("idle");
  };

  const openFullscreen = () => {
    if (videoSrc) window.open(videoSrc, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="dashboard-card dashboard-card--recessed flex h-full w-full flex-col overflow-hidden font-[RobotoMono]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-borderSubtle bg-bgSurface/70 px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${
              status === "online"
                ? "bg-statusGreen"
                : status === "error"
                ? "bg-statusRed"
                : "bg-statusYellow"
            }`}
          />
          <span className="text-xs uppercase tracking-wider text-themeTextGray">
            {t("Camera")}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <select
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            className="rounded border border-borderSubtle bg-bgCard px-2 py-0.5 text-xs text-textWhiteHover"
          >
            {CAMERA_TOPIC_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {t(label)}
              </option>
            ))}
          </select>
          <select
            value={quality}
            onChange={(e) => setQuality(e.target.value)}
            className="rounded border border-borderSubtle bg-bgCard px-2 py-0.5 text-xs text-textWhiteHover"
          >
            <option value="low">{t("Low")}</option>
            <option value="balanced">{t("Balanced")}</option>
            <option value="high">{t("High")}</option>
          </select>
          <button
            type="button"
            onClick={status === "idle" ? tryToConnectToCamera : stopCamera}
            className="min-h-[32px] rounded-lg border border-borderSubtle px-2.5 text-xs text-themeBlue hover:border-themeBlue"
          >
            {t(status === "idle" ? "Start" : "Stop")}
          </button>
          <button
            type="button"
            onClick={openFullscreen}
            disabled={!videoSrc}
            className="min-h-[32px] rounded-lg border border-borderSubtle px-2.5 text-xs text-themeBlue hover:border-themeBlue disabled:opacity-40"
          >
            {t("Full")}
          </button>
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center bg-bgSurface/30">
        {videoSrc ? (
          <img
            key={videoSrc}
            src={videoSrc}
            className="h-full w-full object-cover"
            alt="Camera feed"
            onLoad={() => setStatus("online")}
            onError={(e) => {
              setStatus("error");
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <EmptyState
            title="Camera is paused"
            description="Start the video feed to see what the robot sees."
            icon={
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                className="h-5 w-5"
                aria-hidden="true"
              >
                <rect x="3" y="6" width="14" height="12" rx="3" />
                <path d="m17 10 4-2v8l-4-2" strokeLinejoin="round" />
              </svg>
            }
            action={
              <button
                type="button"
                onClick={tryToConnectToCamera}
                className="rounded-lg border border-themeBlue/40 bg-themeBlue/10 px-4 py-2 text-xs font-semibold text-themeBlue hover:bg-themeBlue hover:text-white"
              >
                {t("Start camera")}
              </button>
            }
          />
        )}
        {status === "loading" ? (
          <div className="absolute inset-x-8 bottom-8 rounded-xl border border-borderSubtle bg-bgCard/90 p-4 backdrop-blur">
            <LoadingSkeleton lines={2} />
          </div>
        ) : null}
        {status === "error" && (
          <button
            type="button"
            onClick={tryToConnectToCamera}
            className="absolute rounded-lg border border-borderSubtle bg-bgCard px-3 py-2 text-xs text-statusRed"
          >
            {t("Camera unavailable")}
          </button>
        )}
      </div>
    </div>
  );
};

export default Camera;

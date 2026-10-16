import { T } from "../shared/i18n/i18n";
import React, { useEffect, useState } from "react";

const API_BASE = "";

/** Show a warning if the development-only open mode is accessed remotely. */
const AuthModeBanner = () => {
  const [status, setStatus] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/auth/status`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status || dismissed) return null;

  const showNetworkWarning =
    status.mode === "open" && status.isLocalNetwork === false;
  if (!showNetworkWarning) return null;

  return (
    <div className="mb-3 flex items-start gap-3 rounded-xl border border-statusYellow/30 bg-statusYellow/10 px-4 py-2 font-[RobotoMono] text-xs leading-snug text-statusYellow">
      <span className="flex-1">
        {showNetworkWarning && (
          <span>
            <T>
              {
                "Open mode is for local development only. Enable AUTH_MODE=local for remote access."
              }
            </T>{" "}
          </span>
        )}
      </span>
      <button
        onClick={() => setDismissed(true)}
        className="shrink-0 text-statusYellow/70 hover:text-statusYellow"
        aria-label="Dismiss warning"
      >
        ×
      </button>
    </div>
  );
};

export default AuthModeBanner;

import React, { useState } from "react";
import { toast } from "react-toastify";

import { useRos, useRosStatus, useRuntimeConfig } from "../app/App";
import buildSupportPackage from "../shared/support/buildSupportPackage";
import { useT } from "../shared/i18n/i18n";

/**
 * Downloads a single JSON file bundling connection status, the Health Centre
 * rollup, recent events, runtime config, and a best-effort Nav2 param snapshot
 * — meant to be attached to a support
 * ticket instead of asking an operator to screenshot five different pages.
 * `health` ({overall, overallLabel, issues}) is passed in from a parent that
 * already calls useSystemDiagnostics, so this button never subscribes to ROS
 * topics on its own.
 */
const SupportPackageButton = ({ health }) => {
  const { t } = useT();
  const ros = useRos();
  const rosStatus = useRosStatus();
  const { config } = useRuntimeConfig();
  const [busy, setBusy] = useState(false);

  const download = async () => {
    setBusy(true);
    try {
      const pkg = await buildSupportPackage({
        ros,
        rosStatus,
        config,
        health,
      });
      const blob = new Blob([JSON.stringify(pkg, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `robotpilot-support-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(t("Support package downloaded"));
    } catch (err) {
      toast.error(
        `${t("Couldn't build support package")}: ${err?.message || err}`,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      onClick={download}
      disabled={busy}
      className="rounded-lg border border-borderSubtle px-3 py-1.5 text-xs text-themeTextGray transition-colors hover:border-themeBlue hover:text-themeBlue disabled:opacity-40"
    >
      {t(busy ? "Building…" : "Export support package")}
    </button>
  );
};

export default SupportPackageButton;

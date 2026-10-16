import React from "react";
import { useRuntimeConfig } from "../app/App";
import { useT } from "../shared/i18n/i18n";

/**
 * Demo Mode 开启时始终显示，不允许关闭。它与 AuthModeBanner 的警告采用相同展示方式，但原因不同：
 * 此横幅用于明确遥测数据是模拟数据，避免被误认为来自真实机器人。它也提供了快速切回真实连接的入口，
 * 符合“允许从 Demo 切换到真实连接”的需求。
 */
const DemoModeBanner = () => {
  const { config, updateConfig } = useRuntimeConfig();
  const { t } = useT();
  if (!config.demoMode) return null;

  return (
    <div className="mb-3 flex items-center gap-3 rounded-xl border border-themeBlue/40 bg-themeBlue/10 px-4 py-2 font-[RobotoMono] text-xs text-themeBlue">
      <span className="flex h-2 w-2 shrink-0 rounded-full bg-themeBlue" />
      <span className="flex-1">
        <span className="font-bold uppercase tracking-wider">{t("Demo mode")}</span>{" "}
        {t("— every value on screen is simulated. No robot is connected.")}
      </span>
      <button
        onClick={() => updateConfig({ demoMode: false })}
        className="shrink-0 rounded-lg border border-themeBlue/40 px-2.5 py-1 font-semibold hover:bg-themeBlue hover:text-white"
      >
        {t("Exit demo mode")}
      </button>
    </div>
  );
};

export default DemoModeBanner;

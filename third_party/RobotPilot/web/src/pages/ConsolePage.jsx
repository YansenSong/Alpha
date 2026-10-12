import { T } from "../shared/i18n/i18n";
import React from "react";

import { useRosStatus } from "../app/App";
import RosoutConsole from "../components/RosoutConsole";
import TopicEcho from "../components/TopicEcho";
import { SectionHeader, StatusBadge } from "../shared/ui/Dashboard";

/**
 * 可观测性页面：提供实时 /rosout 日志控制台和“回显任意 topic”面板，操作员无需在加载 ROS 环境的终端中操作，
 * 即可从浏览器调试正在运行的软件栈。两个面板共用应用级 ROS 连接。
 */
const ConsolePage = () => {
  const rosStatus = useRosStatus();
  const connected = rosStatus === "connected";

  return (
    <div className="flex min-h-[calc(100vh-145px)] flex-col gap-3 py-3">
      <SectionHeader
        title="Console"
        description="Live ROS logs and raw topic inspection"
        action={
          <StatusBadge
            status={connected ? "connected" : "disconnected"}
            pulse={connected}
            label={connected ? "Robot connected" : "Robot offline"}
          />
        }
      />

      {!connected && (
        <p className="dashboard-card px-4 py-2 font-[RobotoMono] text-xs text-themeTextGray">
          <T>
            {
              "Not connected to the robot — logs and topic echo will start streaming once the connection is live. Check the robot network and UI backend."
            }
          </T>{" "}
        </p>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-2">
        <div className="h-[880px] max-h-[880px] min-h-0">
          <RosoutConsole />
        </div>
        <div className="h-[880px] max-h-[880px] min-h-0">
          <TopicEcho />
        </div>
      </div>
    </div>
  );
};

export default ConsolePage;

import React, { useContext, useRef, useState } from "react";
import { AuthContext, useRosStatus } from "../app/App";
import { useRoleAccess } from "../shared/auth/roleAccess";
import useMissionRun from "../shared/hooks/useMissionRun";
import { cancelMissionTask } from "../shared/missions/taskApi";
import { useT } from "../shared/i18n/i18n";
import SoftwareStopActionButton from "./SoftwareStopActionButton";

export default function CancelTaskButton({ disabled = false }) {
  const { robotId } = useContext(AuthContext);
  const rosStatus = useRosStatus();
  const access = useRoleAccess("Operator");
  const run = useMissionRun();
  const { t } = useT();
  const [request, setRequest] = useState(null);
  const sending = useRef(false);
  const active = run?.taskId && ["running", "paused"].includes(run.status);
  const pending = request?.taskId === run?.taskId && request.status === "pending";
  if (!active) return null;

  const cancel = async () => {
    if (sending.current || pending || disabled || !access.allowed || rosStatus !== "connected") return;
    const taskId = run.taskId;
    sending.current = true;
    setRequest({ taskId, status: "pending" });
    try {
      await cancelMissionTask(robotId, taskId);
      // ACK is not the terminal task state; keep waiting for the robot snapshot.
    } catch (error) {
      setRequest({ taskId, status: "error", error: error.message });
    } finally {
      sending.current = false;
    }
  };
  return (
    <div className="flex flex-col items-center gap-1">
      <SoftwareStopActionButton
        onClick={cancel}
        disabled={disabled || !access.allowed || rosStatus !== "connected" || pending}
        title={t("Cancel the current task without releasing software stop")}
      >
        {t(pending ? "Waiting for cancellation" : "Cancel task")}
      </SoftwareStopActionButton>
      {request?.taskId === run.taskId && request.status === "error" && (
        <span role="alert" className="max-w-48 text-xs text-statusRed">{request.error}</span>
      )}
    </div>
  );
}

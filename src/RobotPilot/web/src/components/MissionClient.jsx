import { useContext, useEffect } from "react";
import { toast } from "react-toastify";
import { useRos, useRosStatus } from "../app/App";
import { AuthContext } from "../app/App";
import { AppConfig } from "../shared/constants";
import {
  replaceMissionsFromRobot,
  setMissionOnline,
} from "../shared/missions/missions";
import { setHistory, setRun } from "../shared/missions/missionClient";
import { setMissionCommandTransport } from "../shared/missions/transport";
import { sendStoredMissionCommand } from "../shared/missions/taskApi";

// A ROS bridge only: closing this tab cannot stop the robot-side executor.
const MissionClient = () => {
  const ros = useRos();
  const rosStatus = useRosStatus();
  const { robotId } = useContext(AuthContext);
  useEffect(() => {
    if (rosStatus !== "connected") {
      setMissionOnline(false);
      setMissionCommandTransport(null);
      return;
    }
    const stateTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.MISSION_STATE_TOPIC,
      messageType: "std_msgs/String",
    });
    const ackTopic = new window.ROSLIB.Topic({
      ros,
      name: AppConfig.MISSION_ACK_TOPIC,
      messageType: "std_msgs/String",
    });
    let latestState = 0;
    setMissionCommandTransport((command) =>
      sendStoredMissionCommand(robotId, command).catch((error) => {
        toast.error(`任务指令被拒绝：${error.message}`);
      }),
    );
    stateTopic.subscribe((msg) => {
      try {
        const state = JSON.parse(msg.data);
        if (state.schema_version !== 1) return;
        latestState = Date.now();
        setMissionOnline(true);
        replaceMissionsFromRobot(state.missions);
        setRun(state.run);
        setHistory(state.history);
      } catch {
        /* ignore malformed ROS messages */
      }
    });
    ackTopic.subscribe((msg) => {
      try {
        const ack = JSON.parse(msg.data);
        if (ack.ok === false)
          toast.error(`Mission command rejected: ${ack.error}`);
      } catch {
        /* ignore malformed ROS messages */
      }
    });
    const watchdog = setInterval(() => {
      if (Date.now() - latestState > 6000) setMissionOnline(false);
    }, 3000);
    return () => {
      clearInterval(watchdog);
      stateTopic.unsubscribe();
      ackTopic.unsubscribe();
      setMissionCommandTransport(null);
      setMissionOnline(false);
    };
  }, [ros, rosStatus, robotId]);
  return null;
};
export default MissionClient;

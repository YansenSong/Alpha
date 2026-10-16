import { useEffect, useState } from "react";

import { getRun, subscribeRun } from "../missions/missionClient";

// React binding for the robot mission snapshot received by MissionClient.
export default function useMissionRun() {
  const [run, setRunState] = useState(getRun);
  useEffect(() => subscribeRun(setRunState), []);
  return run;
}

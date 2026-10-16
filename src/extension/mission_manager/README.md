# Robot-side missions

`mission_manager` is started by `robot_bringup/launch/navigation.launch.py`.
It keeps mission definitions and run records in `~/.ros/ackermann_missions.sqlite3`
on the robot. Override the `database_path` ROS parameter to move the database.
The browser can close while a task is running. After the mission manager itself
restarts, a running task is marked `PAUSED` and requires an explicit resume.

ROS bridge protocol uses `std_msgs/msg/String` JSON:

* `/mission/command`: `{ "request_id": "...", "command": "save", "mission": {"id":"...","name":"...","steps":[...]}}`; other commands are `delete`, `start`, `pause`, `resume`, `cancel`, `retry`, `skip`, `release_hold`, and `query`. `delete` and `start` take `mission_id`; controls take the current `task_id`.
* `/mission/state`: reliable, transient-local snapshot every two seconds and on changes. Includes `missions`, latest `run` (with `task_id`, step snapshot, state, and events), and recent `history`.
* `/mission/ack`: `{ "request_id": "...", "ok": true }` or an error.

Waypoint steps contain their own map-frame pose `{x,y,z,w}`. Changing a
browser-saved waypoint later does not change a saved mission or an active run.
The UI has an explicit import button for legacy browser drafts. Drafts with
missing waypoints are skipped.

Navigation uses `/goal_pose` and `/navigation/state`. Pause, cancel, and skip
assert `/mission/hold` so the velocity mux holds zero; resume or a new task
releases only that override. Operator `/stop` remains independent. Failed or
cancelled tasks keep the drive hold until an operator explicitly releases it
or starts another task. Dock and undock use `/dock_trigger`, `/undock_robot`, and
`/dock_trigger_status`; these steps require a controller that reports `docked`
or `idle`. The stop override only stops vehicle velocity. A dock
controller that continues its own sequence must implement cancellation before
pause or skip can interrupt that sequence fully.

# Structured navigation lifecycle. /navigation/planner_state is bridge input;
# /navigation/execution_state is the sole authoritative navigation result.
uint8 WAITING_FOR_GOAL=0
uint8 PLANNING=1
uint8 MOVING=2
uint8 ARRIVED=3
uint8 FAILED=4
builtin_interfaces/Time stamp
geometry_msgs/PoseStamped goal
builtin_interfaces/Time path_stamp
string execution_id
uint8 state
bool held
string detail
# Immutable terminal observations generated only by nav_status; empty otherwise.
string result_json

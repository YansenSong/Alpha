# nav_neupan_bringup

Launch package for the Smac Hybrid-A* + NeuPAN real-vehicle navigation stack.
Shared sensors, motion interface, and LIORF localization are provided by
`vehicle_bringup`.

The full real-vehicle launch starts the hardware, shared localization, Smac
planning bridge, point-cloud scan conversion, RViz, and NeuPAN. NeuPAN runs in
the `neupan` Conda environment through the repository script
`scripts/run_neupan.sh`.

The recommended entry point is:

```bash
./scripts/start_vehicle.sh nav maps/<map_name>
```

Direct launch:

```bash
ros2 launch nav_neupan_bringup navigation.launch.py \
  project_dir:=$(pwd) \
  vehicle_config:=$(pwd)/config/vehicle.yaml \
  map:=$(pwd)/maps/<map_name>/map.yaml \
  map_pgm:=$(pwd)/maps/<map_name>/map.pgm \
  globalmap_pcd:=$(pwd)/maps/<map_name>/GlobalMap.pcd \
  start_hardware:=true
```

The command gate forwards the NeuPAN output to the shared `/ackermann_cmd` interface.

The launch also starts `area_rules`, `map_bundle_monitor`, and `mission_manager`.
The global costmap applies `/area_rules/filter_info` through KeepoutFilter.
Planner preview paths are remapped to `/planner_server/preview_plan`; only the
bridge publishes an accepted execution path on `/plan`. NeuPAN acknowledges
installation on `/neupan/path_install_status`.

In this navigation launch, the hardware command gate requires fresh area-control
and navigation-hold messages (0.5 s timeout). It obeys `/mission/hold` and
`/stop`, and applies area speed limits while preserving the steering angle.
When hardware is started separately, pass `enable_navigation_rules:=true` to
`vehicle_bringup real_vehicle.launch.py` as well.

Area-rule speed observation defaults to LIORF odometry; override
`rules_odom_topic` if a different measured odometry source is available.
The map monitor requires a valid `<map-name>.bundle.json` beside the map YAML,
matching both the 2D map and `GlobalMap.pcd`. Missing or mismatched map identity,
stale localization, or stale rule/costmap status keeps navigation held; an empty
rule list does not bypass the map checks. Create map manifests with the existing
`mission_manager map_bundle_manifest` tool (`--help` lists its arguments).

The optional `enable_inspection_adapter:=true` starts the external inspection
provider adapter. The real-vehicle launch never enables a simulated provider.

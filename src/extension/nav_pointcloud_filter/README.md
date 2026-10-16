# Point cloud self filter

`self_filter_node` removes returns from inside the vehicle body from a
LiDAR point cloud. It has two consumers, with opposite offsets because they
want opposite things:

| Consumer | Launch | Output | Offset |
|---|---|---|---|
| Navigation | `nav_neupan_bringup/navigation.launch.py` | `/navigation/points_no_body` → `pointcloud_to_laserscan` | `xy_inset: +0.02` (shrink: keep the vehicle edge visible in `/scan`) |
| Mapping | `vehicle_bringup/mapping.launch.py` | `/lidar_points_no_body` → LIO-SAM | `xy_inset: -0.03` (grow: swallow the outer skin too) |

The filter transforms each point into `rear_axle_link` at the cloud timestamp
and rejects points within a rectangular body volume. The XY bounds come from
`vehicle.planning.footprint` in `config/vehicle.yaml`; the Z bounds run from
-0.05 m to the measured LiDAR mounting height.

## Why mapping wants it

LIO-SAM discards everything closer than its `lidarMinRange`, and that alone
used to cover the body, so mapping subscribed to the raw cloud. Measured on the
vehicle 2026-10-16: the body contributes roughly 5000 points per frame and
**every one of them is within 0.75 m of the LiDAR**, so `lidarMinRange: 1.0`
blocked all of them. The cost was that all real geometry within 1 m was thrown
away with them.

Filtering the body explicitly is what makes a lower `lidarMinRange` safe, so
mapping runs this node and drops the floor to 0.3 m. The two settings are
coupled and must move together: with the filter off, LIO-SAM needs the floor
back above the furthest body return (0.75 m, and `mapping.launch.py` passes
0.9 m). `mapping.launch.py` sets both, so they cannot drift apart.

## Offsets

`xy_inset` is an offset from the measured footprint, and the membership test is
written `-rear_ + inset` / `front_ - inset` / `half_width_ - inset`, so a
**negative value widens** the box. Values below -0.5 are rejected: past that it
is no longer a body box.

## Z bounds

The top of the box is the LiDAR mounting height, which is right because nothing
on the vehicle is above the LiDAR. Measurement caveat: ~20 points per frame
still came back from just above the LiDAR plane (z 1.21-1.25 m) inside the
footprint, i.e. from the LiDAR's own mount. `mapping.launch.py` therefore adds
a 0.10 m top margin.

## Interface

`points_in` / `points_out` are `sensor_msgs/PointCloud2`. The output retains
each surviving point's complete binary record, including `ring` and `time`, as
well as the original timestamp and frame -- which is what lets LIO-SAM keep
deskewing the filtered cloud. Invalid XYZ points are discarded. If the
timestamped transform is unavailable, that frame is dropped rather than
publishing an unfiltered cloud.

# Navigation point cloud self filter

`self_filter_node` removes returns from inside the vehicle body before the
navigation stack converts `/lidar_points` to `/scan`. Mapping and LIORF
localization continue to subscribe to their original point cloud.

The filter transforms each point into `rear_axle_link` at the cloud timestamp
and rejects points within a rectangular body volume. The XY bounds come from
`vehicle.planning.footprint` in `config/vehicle.yaml`. A 0.02 m inward offset
keeps points just outside the measured body visible. The Z bounds currently
span -0.05 m to the measured LiDAR mounting height; the actual body top has
not been measured, so these limits should be checked against a recorded cloud.

Input and output are `sensor_msgs/PointCloud2` on `points_in` and `points_out`.
The output retains each surviving point's complete binary record, including
`ring` and `time`, as well as the original timestamp and frame. Invalid XYZ
points are discarded. If the timestamped transform is unavailable, that frame
is dropped rather than publishing an unfiltered navigation cloud.

The real-vehicle navigation launch remaps `points_out` to
`/navigation/points_no_body` and feed that topic to `pointcloud_to_laserscan`.
Do not remap a mapping or localization input to this output.

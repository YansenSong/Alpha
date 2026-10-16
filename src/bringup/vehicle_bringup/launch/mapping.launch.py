"""Start real-vehicle LIO-SAM mapping: LiDAR + IMU + self filter + LIO-SAM.

Sits at the same layer as localization.launch.py: the bringup package composes
the sensors with the algorithm package, and the root config/vehicle.yaml stays
the single source for frame names, extrinsics, the LiDAR mounting pose and the
body box used to reject the vehicle's own returns.

This is the mapping counterpart of the localization stack -- it does NOT start
LIO-SAM's own odometry consumers (Nav2, NeuPAN, the motion interface), so the
vehicle can be pushed around while the map builds.

Why a self filter at all: LIO-SAM discards everything closer than
lidarMinRange, and that alone used to be the whole story, because every return
off the vehicle body sits within 0.75 m of the LiDAR (measured 2026-10-16: ~5000
body points per frame, none beyond 0.75 m). With lidarMinRange at its old 1.0 m
value nothing from the vehicle ever reached LIO-SAM, and the cost was that all
real geometry within 1 m was thrown away too. Filtering the body explicitly is
what makes it safe to lower lidarMinRange and keep that near-field detail.
"""

import math
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# Outward offset applied to the measured footprint. The body box is only as
# accurate as the tape measure that produced vehicle.planning.footprint, so the
# rejection volume is grown slightly to swallow returns off the outer skin.
# Positive would shrink it, which is what the navigation scan wants instead.
DEFAULT_SELF_FILTER_INSET = -0.03

# Headroom above the LiDAR mounting height for the top of the rejection volume.
# Measured 2026-10-16: with the volume capped exactly at the LiDAR height,
# ~20 points per frame still came back from just above the LiDAR plane (z 1.21
# to 1.25 m) inside the footprint, i.e. from the LiDAR's own mount. The cap is
# raised by this margin so they are removed as well.
SELF_FILTER_TOP_MARGIN = 0.10

SELF_FILTER_TOPIC = '/lidar_points_no_body'


def _load_body_box(vehicle_config):
    """Read the vehicle body volume for the self filter from vehicle.yaml.

    Everything here is measured geometry rather than a tuned constant: the XY
    bounds are the verified footprint and the top is the measured LiDAR height.
    """
    if not vehicle_config:
        raise RuntimeError(
            "mapping.launch.py requires a non-empty 'vehicle_config' path"
        )
    if not os.path.isfile(vehicle_config):
        raise RuntimeError(f"Vehicle config does not exist: {vehicle_config}")

    with open(vehicle_config, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}

    vehicle = data.get('vehicle', {})
    footprint = vehicle.get('planning', {}).get('footprint', {})
    mounting = vehicle.get('sensor_mounting', {}).get('lidar', {})
    frames = vehicle.get('frames', {})

    base_frame = str(frames.get('base', '')).strip()
    if not base_frame:
        raise RuntimeError("vehicle.frames.base must not be empty")

    base_height = frames.get('base_height_above_ground')
    if isinstance(base_height, bool) or not isinstance(base_height, (int, float)):
        raise RuntimeError(
            "vehicle.frames.base_height_above_ground must be a number in "
            f"metres, got: {base_height!r}"
        )

    if str(footprint.get('status', '')).strip().upper() != 'VERIFIED':
        raise RuntimeError(
            "vehicle.planning.footprint must be VERIFIED in config/vehicle.yaml "
            "for the self filter body box"
        )

    if str(mounting.get('status', '')).strip().upper() != 'VERIFIED':
        raise RuntimeError(
            "vehicle.sensor_mounting.lidar must be VERIFIED in "
            "config/vehicle.yaml for the self filter height cap"
        )

    box = {'base_frame': base_frame}
    for field in ('front_extent', 'rear_extent', 'half_width'):
        value = footprint.get(field)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value <= 0.02):
            raise RuntimeError(
                f"vehicle.planning.footprint.{field} must be > 0.02 m, "
                f"got: {value!r}"
            )
        box[field] = float(value)

    lidar_height = mounting.get('height_above_ground')
    if (isinstance(lidar_height, bool) or
            not isinstance(lidar_height, (int, float)) or
            not math.isfinite(lidar_height)):
        raise RuntimeError(
            "vehicle.sensor_mounting.lidar.height_above_ground must be a "
            f"number in metres, got: {lidar_height!r}"
        )

    # z bounds are expressed in frames.base, whose height above the ground is
    # base_height_above_ground; the mounting height is measured from the ground.
    lidar_in_base = float(lidar_height) - float(base_height)
    box['min_z'] = -0.05
    box['max_z'] = lidar_in_base + SELF_FILTER_TOP_MARGIN
    return box


def _mapping_nodes(context, body_box, lio_sam_share, vehicle_share):
    enabled = LaunchConfiguration('enable_self_filter').perform(context).strip().lower()
    enabled = enabled in {'1', 'true', 'yes', 'on'}
    raw_topic = LaunchConfiguration('points_topic').perform(context)

    # lidar_rviz MUST stay false. The LiDAR driver's RViz view publishes a
    # zero-placeholder rear_axle_link -> laser_link transform, and LIO-SAM's
    # run.launch.py publishes the measured one. Same edge, two publishers, and
    # on /tf_static the last one to arrive wins -- so enabling both makes the
    # TF nondeterministically wrong. The LIO-SAM RViz window is the one to
    # watch here.
    hardware = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(vehicle_share, 'launch', 'real_vehicle.launch.py')
        ),
        launch_arguments={
            'vehicle_config': LaunchConfiguration('vehicle_config'),
            'enable_lidar': 'true',
            'lidar_config': LaunchConfiguration('lidar_config'),
            'lidar_rviz': 'false',
            'enable_imu': LaunchConfiguration('enable_imu'),
            'imu_port': LaunchConfiguration('imu_port'),
            'imu_sensor_id': LaunchConfiguration('imu_sensor_id'),
            'imu_params_file': LaunchConfiguration('imu_params_file'),
            # Mapping moves the vehicle by hand: never bring up the STM32
            # backend or the command gate.
            'enable_control': 'false',
            'enable_command_gate': 'false',
        }.items(),
    )

    if not enabled:
        lio_sam_topic = raw_topic
        # No filter, so the raw cloud still carries the body: LIO-SAM's own
        # minimum range has to cover the furthest body return (0.75 m).
        lio_sam_min_range = '0.9'
        filter_nodes = []
    else:
        lio_sam_topic = SELF_FILTER_TOPIC
        # The body is gone, so the floor can drop to a little above the LiDAR's
        # own minimum and the near-field real geometry is kept.
        lio_sam_min_range = '0.3'
        filter_nodes = [
            # Same node the navigation stack uses for /scan. It copies each
            # surviving point's whole binary record, so ring and time reach
            # LIO-SAM intact and deskew keeps working.
            Node(
                package='nav_pointcloud_filter',
                executable='self_filter_node',
                name='mapping_self_filter',
                output='screen',
                parameters=[{
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                    'xy_inset': LaunchConfiguration('self_filter_inset'),
                    **body_box,
                }],
                remappings=[
                    ('points_in', raw_topic),
                    ('points_out', SELF_FILTER_TOPIC),
                ],
            ),
        ]

    lio_sam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(lio_sam_share, 'launch', 'run.launch.py')
        ),
        launch_arguments={
            'vehicle_config': LaunchConfiguration('vehicle_config'),
            'points_topic': lio_sam_topic,
            'lidar_min_range': lio_sam_min_range,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'use_rviz': LaunchConfiguration('use_rviz'),
        }.items(),
    )

    return [hardware, *filter_nodes, lio_sam]


def generate_launch_description():
    vehicle_share = get_package_share_directory('vehicle_bringup')
    lidar_share = get_package_share_directory('lidar_driver')
    imu_share = get_package_share_directory('imu')
    lio_sam_share = get_package_share_directory('lio_sam')

    arguments = [
        DeclareLaunchArgument(
            'vehicle_config',
            default_value='',
            description=(
                'Absolute path to root config/vehicle.yaml. VERIFIED LiDAR/IMU '
                'extrinsics, VERIFIED LiDAR mounting and a VERIFIED footprint '
                'are required.'
            ),
        ),
        DeclareLaunchArgument(
            'lidar_config',
            default_value=os.path.join(lidar_share, 'config', 'config.yaml'),
            description='Path to the Hesai lidar_driver YAML configuration.',
        ),
        DeclareLaunchArgument('enable_imu', default_value='true'),
        DeclareLaunchArgument('imu_port', default_value='/dev/ttyUSB0'),
        DeclareLaunchArgument('imu_sensor_id', default_value='1'),
        DeclareLaunchArgument(
            'imu_params_file',
            default_value=os.path.join(
                imu_share, 'config', 'lpms_ig1_rs232_calibration.yaml'
            ),
            description='LPMS-IG1 RS232 software calibration parameter file.',
        ),
        DeclareLaunchArgument(
            'points_topic',
            default_value='/lidar_points',
            description='Raw PointCloud2 topic published by the LiDAR driver.',
        ),
        DeclareLaunchArgument(
            'enable_self_filter',
            default_value='true',
            description=(
                'Reject the vehicle body from the cloud before LIO-SAM. Off '
                'feeds the raw cloud straight to LIO-SAM, which is only safe '
                'while lidarMinRange is large enough to cover the body.'
            ),
        ),
        DeclareLaunchArgument(
            'self_filter_inset',
            default_value=str(DEFAULT_SELF_FILTER_INSET),
            description=(
                'Footprint offset for the rejection box. Negative grows it to '
                'swallow the outer skin; the navigation scan uses a positive '
                'value to keep the skin visible instead.'
            ),
        ),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'use_rviz',
            default_value='true',
            description='Start the LIO-SAM RViz window (Fixed Frame: map).',
        ),
    ]

    return LaunchDescription(arguments + [
        OpaqueFunction(
            function=lambda context: _mapping_nodes(
                context,
                _load_body_box(
                    LaunchConfiguration('vehicle_config').perform(context)
                ),
                lio_sam_share,
                vehicle_share,
            ),
        ),
    ])

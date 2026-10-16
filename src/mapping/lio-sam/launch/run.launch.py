"""Start LIO-SAM mapping with project-level real-vehicle frames and extrinsics.

Everything geometry-related -- frame names, the LiDAR/IMU extrinsics and the
measured LiDAR mounting -- is read from the root config/vehicle.yaml at launch
time rather than duplicated in this package's parameter file.
"""

import math
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _numeric_list(value, length, field):
    if not isinstance(value, list) or len(value) != length:
        raise RuntimeError(
            f"{field} must be a list with exactly {length} numeric values"
        )
    result = []
    for item in value:
        number = float(item)
        if not math.isfinite(number):
            raise RuntimeError(f"{field} must contain only finite numbers")
        result.append(number)
    return result


def _load_vehicle_calibration(path):
    """Runtime LIO-SAM overrides taken from config/vehicle.yaml.

    Covers the frame names, the measured LiDAR mounting pose and the LiDAR/IMU
    extrinsics, so none of them can drift from the single project-level source.
    Mirrors the same loader in bringup/vehicle_bringup/launch/localization.launch.py.
    """
    if not path:
        raise RuntimeError(
            "lio_sam run.launch.py requires a non-empty 'vehicle_config' path"
        )
    if not os.path.isfile(path):
        raise RuntimeError(f"Vehicle config does not exist: {path}")

    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}

    vehicle = data.get('vehicle', {})
    extrinsics = vehicle.get('sensor_extrinsics', {}).get('lidar_to_imu', {})
    mounting = vehicle.get('sensor_mounting', {}).get('lidar', {})
    frames = vehicle.get('frames', {})

    status = str(extrinsics.get('status', '')).strip().upper()
    if status != 'VERIFIED':
        raise RuntimeError(
            "LiDAR/IMU extrinsics are not VERIFIED in config/vehicle.yaml; "
            "LIO-SAM will not start with stale/default calibration"
        )

    lidar_frame = str(frames.get('lidar', '')).strip()
    base_frame = str(frames.get('base', '')).strip()
    for label, name in (('lidar', lidar_frame), ('base', base_frame)):
        if not name:
            raise RuntimeError(f"vehicle.frames.{label} must not be empty")

    base_height = frames.get('base_height_above_ground')
    if isinstance(base_height, bool) or not isinstance(base_height, (int, float)):
        raise RuntimeError(
            "vehicle.frames.base_height_above_ground must be a number in "
            f"metres, got: {base_height!r}"
        )

    mounting_status = str(mounting.get('status', '')).strip().upper()
    if mounting_status != 'VERIFIED':
        raise RuntimeError(
            "vehicle.sensor_mounting.lidar is not VERIFIED in "
            f"config/vehicle.yaml (found {mounting_status or 'no status'!s}); "
            "the laser_link static transform would use unmeasured mounting "
            "values."
        )

    mounting_numbers = {}
    for field in ('x', 'y', 'height_above_ground', 'roll_deg', 'pitch_deg',
                  'yaw_deg'):
        value = mounting.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(
                f"vehicle.sensor_mounting.lidar.{field} must be a number, "
                f"got: {value!r}"
            )
        mounting_numbers[field] = float(value)

    # static_transform_publisher takes radians, and the --flag form is used
    # deliberately: the legacy positional form is
    #   x y z YAW pitch ROLL frame_id child_frame_id
    # i.e. the opposite order to the roll/pitch/rpy that vehicle.yaml is written
    # in. With a non-zero mounting yaw the positional form publishes the yaw as
    # a roll. Same construction as
    # bringup/nav_neupan_bringup/launch/navigation.launch.py.
    tf = [
        '--x', f"{mounting_numbers['x']}",
        '--y', f"{mounting_numbers['y']}",
        '--z', f"{mounting_numbers['height_above_ground'] - float(base_height)}",
        '--roll', f"{math.radians(mounting_numbers['roll_deg'])}",
        '--pitch', f"{math.radians(mounting_numbers['pitch_deg'])}",
        '--yaw', f"{math.radians(mounting_numbers['yaw_deg'])}",
        '--frame-id', base_frame,
        '--child-frame-id', lidar_frame,
    ]

    return {
        # LIORF/LIO-SAM publish odometry in baselinkFrame and LIO-SAM's
        # imuPreintegration looks up the fixed lidarFrame->baselinkFrame
        # transform, so these two must be frames.base and frames.lidar rather
        # than a package-local "base_link" that nothing on the vehicle defines.
        'lidarFrame': lidar_frame,
        'baselinkFrame': base_frame,
        'extrinsicTrans': _numeric_list(
            extrinsics.get('translation_xyz'), 3,
            'vehicle.sensor_extrinsics.lidar_to_imu.translation_xyz',
        ),
        'extrinsicRot': _numeric_list(
            extrinsics.get('rotation_matrix'), 9,
            'vehicle.sensor_extrinsics.lidar_to_imu.rotation_matrix',
        ),
        'extrinsicRPY': _numeric_list(
            extrinsics.get('orientation_matrix'), 9,
            'vehicle.sensor_extrinsics.lidar_to_imu.orientation_matrix',
        ),
        'tf': tf,
    }


def _lio_sam_nodes(context, share_dir):
    parameter_file = LaunchConfiguration('params_file').perform(context)
    vehicle_config = LaunchConfiguration('vehicle_config').perform(context)
    use_sim_time = LaunchConfiguration('use_sim_time')

    calibration = _load_vehicle_calibration(vehicle_config)
    tf_arguments = calibration.pop('tf')
    runtime_parameters = {
        'use_sim_time': use_sim_time,
        'pointCloudTopic': LaunchConfiguration('points_topic'),
        # Injected rather than left to params.yaml because it is coupled to
        # whether the caller filtered the vehicle body out of the cloud: the
        # body occupies roughly 5000 points per frame, all of them within
        # 0.75 m of the LiDAR (measured 2026-10-16). With the self filter on,
        # a low floor here keeps near-field geometry; without it, the floor has
        # to stay above the whole body or LIO-SAM maps its own chassis.
        'lidarMinRange': LaunchConfiguration('lidar_min_range'),
        **calibration,
    }
    rviz_config_file = os.path.join(share_dir, 'config', 'rviz2.rviz')

    return [
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='map_to_odom_static',
            arguments=['0.0', '0.0', '0.0', '0.0', '0.0', '0.0', 'map', 'odom'],
            parameters=[{'use_sim_time': use_sim_time}],
            output='screen',
        ),
        # Measured LiDAR mounting, so the TF tree has a real rear_axle_link ->
        # laser_link edge. Exactly one node consumes it: imuPreintegration's
        # TransformFusion, which publishes odom->baselinkFrame from the fixed
        # lidarFrame->baselinkFrame lookup. That lookup failing is NOT loud --
        # lidar2Baselink is a default-constructed (identity) member, so the
        # catch only logs and then publishes an odom->rear_axle_link that is
        # wrong by 0.62 m, 1.20 m and 90 deg of yaw. That transform is what
        # Nav2, the self filter, area_rules and NeuPAN consume, so the map would
        # look right while the vehicle's pose in it did not.
        #
        # The LiDAR driver's own launch publishes this SAME edge (start.py)
        # with all-zero values when its RViz view is enabled. That is not two
        # parents -- it is two conflicting publishers of one /tf_static edge,
        # where the winner is whichever arrives last. Keep lidar_rviz:=false in
        # mapping so the measured value is the only one published.
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='laser_link_static_tf',
            arguments=[*tf_arguments],
            parameters=[{'use_sim_time': use_sim_time}],
            output='screen',
        ),
        # The two TF edges LIO-SAM needs are published above and below; there is
        # no robot_state_publisher or URDF anywhere in this project, and the
        # vehicle bringup publishes no sensor frames with lidar_rviz:=false.
        Node(
            package='lio_sam',
            executable='lio_sam_imuPreintegration',
            name='lio_sam_imuPreintegration',
            parameters=[parameter_file, runtime_parameters],
            output='screen',
        ),
        Node(
            package='lio_sam',
            executable='lio_sam_imageProjection',
            name='lio_sam_imageProjection',
            parameters=[parameter_file, runtime_parameters],
            output='screen',
        ),
        Node(
            package='lio_sam',
            executable='lio_sam_featureExtraction',
            name='lio_sam_featureExtraction',
            parameters=[parameter_file, runtime_parameters],
            output='screen',
        ),
        Node(
            package='lio_sam',
            executable='lio_sam_mapOptimization',
            name='lio_sam_mapOptimization',
            parameters=[parameter_file, runtime_parameters],
            output='screen',
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            condition=IfCondition(LaunchConfiguration('use_rviz')),
            arguments=['-d', rviz_config_file],
            parameters=[{'use_sim_time': use_sim_time}],
            output='screen',
        ),
    ]


def generate_launch_description():
    share_dir = get_package_share_directory('lio_sam')

    return LaunchDescription([
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(share_dir, 'config', 'params.yaml'),
            description='Path to the LIO-SAM algorithm/sensor parameter file.',
        ),
        DeclareLaunchArgument(
            'vehicle_config',
            default_value='',
            description=(
                'Absolute path to root config/vehicle.yaml. VERIFIED LiDAR/IMU '
                'extrinsics and a VERIFIED LiDAR mounting are required.'
            ),
        ),
        DeclareLaunchArgument(
            'points_topic',
            default_value='/lidar_points',
            description=(
                'PointCloud2 topic for LIO-SAM. Defaults to the Hesai driver '
                'output; overridden so the topic has one source like the frames.'
            ),
        ),
        DeclareLaunchArgument(
            'lidar_min_range',
            default_value='0.9',
            description=(
                'lidarMinRange for LIO-SAM. The default suits the RAW cloud, '
                'where it must stay above the furthest vehicle body return '
                '(measured at 0.75 m). Lower it only when the input cloud has '
                'already had the body removed.'
            ),
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='false',
            description='Use ROS simulation clock. Real vehicle default is false.',
        ),
        DeclareLaunchArgument(
            'use_rviz',
            default_value='true',
            description='Start the LIO-SAM RViz window.',
        ),
        OpaqueFunction(
            function=_lio_sam_nodes,
            args=[share_dir],
        ),
    ])

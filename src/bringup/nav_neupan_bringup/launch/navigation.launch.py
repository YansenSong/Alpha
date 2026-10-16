"""Compose the real-vehicle Smac + NeuPAN navigation stack."""

import math
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def _load_lidar_mounting(vehicle_config):
    """Read vehicle.sensor_mounting.lidar from config/vehicle.yaml.

    Returns the scan-slice height plus the static transform placing laser_link
    in frames.base. Note the two references involved -- see the comments in
    vehicle.yaml: height_above_ground is measured from the ground, while the
    transform is relative to frames.base.
    """
    if not vehicle_config:
        raise RuntimeError(
            "navigation.launch.py requires a non-empty 'vehicle_config' path"
        )
    if not os.path.isfile(vehicle_config):
        raise RuntimeError(f"Vehicle config does not exist: {vehicle_config}")

    with open(vehicle_config, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}

    vehicle = data.get('vehicle', {})
    mounting = vehicle.get('sensor_mounting', {}).get('lidar', {})
    footprint = vehicle.get('planning', {}).get('footprint', {})
    frames = vehicle.get('frames', {})
    base_height = frames.get('base_height_above_ground')
    base_frame = str(frames.get('base', '')).strip()
    lidar_frame = str(frames.get('lidar', '')).strip()

    for label, name in (('base', base_frame), ('lidar', lidar_frame)):
        if not name:
            raise RuntimeError(f"vehicle.frames.{label} must not be empty")

    status = str(mounting.get('status', '')).strip().upper()
    if status != 'VERIFIED':
        raise RuntimeError(
            "vehicle.sensor_mounting.lidar is not VERIFIED in "
            "config/vehicle.yaml (found "
            f"{status or 'no status'!s}); the scan slice and the laser_link "
            "static transform would use unmeasured mounting values. Measure the "
            "LiDAR height above the ground and its mounting rotations, then set "
            "them there."
        )

    numbers = {}
    for field in ('x', 'y', 'height_above_ground', 'roll_deg', 'pitch_deg',
                  'yaw_deg', 'ground_margin'):
        value = mounting.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(
                f"vehicle.sensor_mounting.lidar.{field} must be a number, "
                f"got: {value!r}"
            )
        numbers[field] = float(value)

    if isinstance(base_height, bool) or not isinstance(base_height, (int, float)):
        raise RuntimeError(
            "vehicle.frames.base_height_above_ground must be a number in "
            f"metres, got: {base_height!r}"
        )

    # The ground plane sits at -height_above_ground in laser_link.
    min_height = numbers['ground_margin'] - numbers['height_above_ground']

    if str(footprint.get('status', '')).strip().upper() != 'VERIFIED':
        raise RuntimeError('vehicle.planning.footprint must be VERIFIED for self filtering')
    body = {}
    for field in ('front_extent', 'rear_extent', 'half_width'):
        value = footprint.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0.02:
            raise RuntimeError(f'vehicle.planning.footprint.{field} must be > 0.02 m')
        body[field] = float(value)

    # static_transform_publisher takes radians.
    tf = (
        f"{numbers['x']}",
        f"{numbers['y']}",
        f"{numbers['height_above_ground'] - float(base_height)}",
        f"{math.radians(numbers['roll_deg'])}",
        f"{math.radians(numbers['pitch_deg'])}",
        f"{math.radians(numbers['yaw_deg'])}",
    )
    return {
        'min_height': min_height,
        'body': body,
        'height_in_base': numbers['height_above_ground'] - float(base_height),
        'tf': tf,
        'base_frame': base_frame,
        'lidar_frame': lidar_frame,
    }


def _scan_node(context):
    """Build the scan node and the laser_link static transform.

    Both depend on vehicle.yaml, so they are resolved together.

    The transform is published unconditionally, not behind an RViz switch:
    NeuPAN calls lookup_transform(map_frame, laser_link) and this is the only
    publisher of laser_link in the navigation modes. The placeholder in the
    LiDAR driver launch is gated on the standalone RViz view, which
    scripts/start_vehicle.sh turns off for nav/nav2.
    """
    share = get_package_share_directory('nav_neupan_bringup')
    vehicle_config = LaunchConfiguration('vehicle_config').perform(context)
    layout = _load_lidar_mounting(vehicle_config)
    return [
        Node(
            package='nav_pointcloud_filter',
            executable='self_filter_node',
            name='nav_self_filter',
            output='screen',
            parameters=[{
                'use_sim_time': LaunchConfiguration('use_sim_time'),
                'base_frame': layout['base_frame'],
                **layout['body'],
                'xy_inset': 0.02,
                'min_z': -0.05,
                'max_z': layout['height_in_base'],
            }],
            remappings=[
                ('points_in', LaunchConfiguration('points_topic')),
                ('points_out', '/navigation/points_no_body'),
            ],
        ),
        Node(
            package='pointcloud_to_laserscan',
            executable='pointcloud_to_laserscan_node',
            name='pointcloud_to_laserscan',
            output='screen',
            parameters=[
                os.path.join(share, 'config', 'pcl_to_scan.yaml'),
                {
                    'use_sim_time': LaunchConfiguration('use_sim_time'),
                    'min_height': layout['min_height'],
                },
            ],
            remappings=[
                ('cloud_in', '/navigation/points_no_body'),
                ('scan', '/scan'),
            ],
        ),
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='laser_link_static_tf',
            output='screen',
            arguments=[
                *layout['tf'], layout['base_frame'], layout['lidar_frame'],
            ],
            parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
        ),
    ]


def generate_launch_description():
    nav_share = get_package_share_directory('nav_neupan_bringup')
    vehicle_share = get_package_share_directory('vehicle_bringup')
    nav_status_share = get_package_share_directory('nav_status')
    lidar_share = get_package_share_directory('lidar_driver')
    motion_share = get_package_share_directory('motion_interface')
    project_dir = LaunchConfiguration('project_dir')
    vehicle_config = LaunchConfiguration('vehicle_config')
    use_sim_time = LaunchConfiguration('use_sim_time')
    arguments = [
        DeclareLaunchArgument('project_dir', default_value=os.getcwd()),
        DeclareLaunchArgument('start_hardware', default_value='false'),
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('map_pgm', default_value=''),
        DeclareLaunchArgument('globalmap_pcd', default_value=''),
        DeclareLaunchArgument('vehicle_config', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'lidar_config',
            default_value=os.path.join(lidar_share, 'config', 'config.yaml')),
        DeclareLaunchArgument('enable_imu', default_value='false'),
        DeclareLaunchArgument('imu_port', default_value='/dev/ttyUSB0'),
        DeclareLaunchArgument('imu_sensor_id', default_value='1'),
        DeclareLaunchArgument(
            'imu_params_file',
            default_value=os.path.join(
                get_package_share_directory('imu'),
                'config', 'lpms_ig1_rs232_calibration.yaml')),
        DeclareLaunchArgument(
            'bridge_params_file',
            default_value=os.path.join(
                motion_share, 'config', 'bridge_params.yaml')),
        DeclareLaunchArgument(
            'status_params_file',
            default_value=os.path.join(
                motion_share, 'config', 'status_params.yaml')),
        DeclareLaunchArgument(
            'points_topic',
            default_value='/lidar_points',
            description='Real-vehicle point cloud input for pointcloud_to_laserscan.',
        ),
        DeclareLaunchArgument(
            'use_rviz',
            default_value='true',
            description='Start the navigation RViz window.',
        ),
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                vehicle_share, 'config', 'liorf_localization.yaml')),
    ]
    hardware = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(vehicle_share, 'launch', 'real_vehicle.launch.py')),
        condition=IfCondition(LaunchConfiguration('start_hardware')),
        launch_arguments={
            'vehicle_config': vehicle_config,
            'enable_lidar': 'true',
            'lidar_config': LaunchConfiguration('lidar_config'),
            'lidar_rviz': 'false',
            'enable_imu': LaunchConfiguration('enable_imu'),
            'imu_port': LaunchConfiguration('imu_port'),
            'imu_sensor_id': LaunchConfiguration('imu_sensor_id'),
            'imu_params_file': LaunchConfiguration('imu_params_file'),
            'enable_control': 'true',
            'enable_command_gate': 'true',
            'bridge_params_file': LaunchConfiguration('bridge_params_file'),
            'status_params_file': LaunchConfiguration('status_params_file'),
        }.items(),
    )
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(vehicle_share, 'launch', 'localization.launch.py')
        ),
        launch_arguments={
            'globalmap_pcd': LaunchConfiguration('globalmap_pcd'),
            'vehicle_config': LaunchConfiguration('vehicle_config'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'params_file': LaunchConfiguration('params_file'),
        }.items(),
    )
    planning = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav_share, 'launch', 'planning.launch.py')
        ),
        launch_arguments={
            'map': LaunchConfiguration('map'),
            'map_pgm': LaunchConfiguration('map_pgm'),
            'vehicle_config': LaunchConfiguration('vehicle_config'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
    )
    scan = OpaqueFunction(function=_scan_node)
    nav_status = Node(
        package='nav_status',
        executable='nav_status_node',
        name='nav_status_node',
        output='screen',
        parameters=[
            os.path.join(nav_status_share, 'config', 'nav_status.yaml'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')},
        ],
    )
    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        condition=IfCondition(LaunchConfiguration('use_rviz')),
        arguments=['-d', os.path.join(nav_share, 'rviz', 'nav_neupan.rviz')],
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
    )
    neupan = ExecuteProcess(
        cmd=[
            'bash',
            PathJoinSubstitution([project_dir, 'scripts', 'run_neupan.sh']),
        ],
        additional_env={
            'VEHICLE_CONFIG': vehicle_config,
            'NEUPAN_USE_SIM_TIME': use_sim_time,
        },
        output='screen',
    )
    return LaunchDescription(
        arguments + [hardware, localization, planning, scan, nav_status, rviz, neupan]
    )

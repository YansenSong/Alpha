"""Compose localization, global planning, scan conversion, command muxing, and RViz."""

import os

import launch.logging
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, RegisterEventHandler
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _validate_inspection_configuration(context):
    enabled = LaunchConfiguration('enable_inspection_adapter').perform(context).lower() in ('true', '1', 'yes')
    mode = LaunchConfiguration('inspection_provider_mode').perform(context).lower()
    profile = LaunchConfiguration('inspection_simulation_profile').perform(context).lower()
    if mode not in ('external', 'fixture'):
        raise RuntimeError('inspection_provider_mode must be external or fixture')
    if enabled and mode == 'fixture':
        if profile not in ('true', '1', 'yes'):
            raise RuntimeError('fixture requires the explicit navigation simulation profile')
        if os.environ.get('ROBOT_MODE') != 'simulation':
            raise RuntimeError('fixture requires ROBOT_MODE=simulation')
    return []


def _report_adapter_exit(context):
    launch.logging.get_logger('robot_bringup').error(
        'inspection_adapter exited; MissionManager will mark provider stale until it returns')
    return []


def generate_launch_description():
    share = get_package_share_directory('robot_bringup')
    nav_status_share = get_package_share_directory('nav_status')
    arguments = [
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('map_pgm', default_value=''),
        DeclareLaunchArgument('globalmap_pcd', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('use_rviz', default_value='true'),
        DeclareLaunchArgument('enable_inspection_adapter', default_value='false'),
        DeclareLaunchArgument('inspection_provider_mode', default_value='external'),
        DeclareLaunchArgument('inspection_simulation_profile', default_value='false'),
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                share, 'config', 'liorf_localization.yaml')),
    ]
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'localization.launch.py')),
        launch_arguments={
            'globalmap_pcd': LaunchConfiguration('globalmap_pcd'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'params_file': LaunchConfiguration('params_file'),
        }.items())
    planning = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(share, 'launch', 'planning.launch.py')),
        launch_arguments={'map': LaunchConfiguration('map'), 'map_pgm': LaunchConfiguration('map_pgm')}.items())
    scan = Node(package='pointcloud_to_laserscan', executable='pointcloud_to_laserscan_node',
                name='pointcloud_to_laserscan', output='screen',
                parameters=[os.path.join(share, 'config', 'pcl_to_scan.yaml')],
                remappings=[('cloud_in', '/points_raw'), ('scan', '/scan')])
    adapter = Node(
        package='vehicle_control',
        executable='neupan_ackermann_adapter.py',
        name='neupan_ackermann_adapter',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'wheelbase': 0.593,
            'input_topic': '/neupan_cmd_vel_raw',
            'output_topic': '/neupan_cmd_vel',
        }])
    area_rules = Node(
        package='area_rules', executable='area_rules',
        name='area_rules', output='screen',
        respawn=True, respawn_delay=1.0,
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}])
    mux = Node(package='vehicle_control', executable='cmd_vel_mux.py', name='cmd_vel_mux',
               output='screen', parameters=[{
                   'use_sim_time': LaunchConfiguration('use_sim_time'),
                   'area_rules_required': True,
                   'rules_hold_required': True,
               }])
    nav_status = Node(
        package='nav_status', executable='nav_status_node', name='nav_status_node',
        output='screen',
        parameters=[
            os.path.join(nav_status_share, 'config', 'nav_status.yaml'),
            {'use_sim_time': True},
        ])
    mission_manager = Node(
        package='mission_manager', executable='mission_manager',
        name='mission_manager', output='screen',
        respawn=True, respawn_delay=1.0,
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}])
    inspection_adapter = Node(
        package='inspection_adapter', executable='inspection_adapter',
        name='inspection_adapter', output='screen',
        condition=IfCondition(LaunchConfiguration('enable_inspection_adapter')),
        respawn=True, respawn_delay=1.0,
        additional_env={'INSPECTION_PROVIDER_MODE': LaunchConfiguration('inspection_provider_mode')},
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}])
    inspection_exit_handler = RegisterEventHandler(OnProcessExit(
        target_action=inspection_adapter,
        on_exit=[OpaqueFunction(function=_report_adapter_exit)],
    ))
    map_bundle_monitor = Node(
        package='mission_manager', executable='map_bundle_monitor',
        name='map_bundle_monitor', output='screen',
        respawn=True, respawn_delay=1.0,
        parameters=[{
            'map_yaml': LaunchConfiguration('map'),
            'globalmap_pcd': LaunchConfiguration('globalmap_pcd'),
        }])
    rviz = Node(package='rviz2', executable='rviz2', name='rviz2', output='screen',
                condition=IfCondition(LaunchConfiguration('use_rviz')),
                arguments=['-d', os.path.join(share, 'rviz', 'nav2_default_view.rviz')])
    return LaunchDescription(
        arguments + [OpaqueFunction(function=_validate_inspection_configuration),
                     localization, area_rules, planning, scan, adapter, mux,
                     nav_status, map_bundle_monitor, mission_manager,
                     inspection_exit_handler, inspection_adapter, rviz])

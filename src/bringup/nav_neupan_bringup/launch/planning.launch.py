"""Start the real-vehicle Nav2 Smac planner and Ackermann bridge."""

import os
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.descriptions import ParameterFile
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml


def _load_vehicle_config(path):
    if not path:
        raise RuntimeError("planning.launch.py requires a non-empty 'vehicle_config' path")
    if not os.path.isfile(path):
        raise RuntimeError(f"Vehicle config does not exist: {path}")
    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}
    vehicle = data.get('vehicle', {})
    geometry = vehicle.get('geometry', {})
    planning = vehicle.get('planning', {})
    footprint = planning.get('footprint', {})
    frames = vehicle.get('frames', {})

    required = {
        'wheelbase': geometry.get('wheelbase'),
        'minimum_turning_radius': planning.get('minimum_turning_radius'),
        'front_extent': footprint.get('front_extent'),
        'rear_extent': footprint.get('rear_extent'),
        'half_width': footprint.get('half_width'),
        'padding': footprint.get('padding'),
        'base_frame': frames.get('base'),
    }
    missing = [name for name, value in required.items() if value is None or value == '']
    if missing:
        raise RuntimeError(
            f"Vehicle config is missing required planning values: {', '.join(missing)}"
        )
    return required


def _planner(context):
    map_yaml = LaunchConfiguration('map').perform(context)
    vehicle_config = LaunchConfiguration('vehicle_config').perform(context)
    use_sim_time = LaunchConfiguration('use_sim_time')

    if not map_yaml:
        raise RuntimeError("planning.launch.py requires a non-empty 'map' YAML path")

    with open(map_yaml, encoding='utf-8') as stream:
        metadata = yaml.safe_load(stream) or {}
    resolution = float(metadata.get('resolution', 0.05))
    if resolution <= 0.0:
        raise RuntimeError(f"Map resolution must be positive, got {resolution}")

    vehicle = _load_vehicle_config(vehicle_config)
    min_radius = float(vehicle['minimum_turning_radius'])
    front = float(vehicle['front_extent'])
    rear = float(vehicle['rear_extent'])
    half_width = float(vehicle['half_width'])
    padding = float(vehicle['padding'])
    base_frame = str(vehicle['base_frame'])

    if min_radius <= 0.0 or front <= 0.0 or rear < 0.0 or half_width <= 0.0:
        raise RuntimeError('Vehicle planning geometry contains non-positive dimensions')

    footprint_value = (
        f"[[-{rear:.6f}, -{half_width:.6f}], "
        f"[{front:.6f}, -{half_width:.6f}], "
        f"[{front:.6f}, {half_width:.6f}], "
        f"[-{rear:.6f}, {half_width:.6f}]]"
    )

    params = os.path.join(
        get_package_share_directory('nav_neupan_bringup'),
        'config', 'smac_planner.yaml')
    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params,
            param_rewrites={
                'use_sim_time': use_sim_time,
                'yaml_filename': map_yaml,
                'global_costmap.global_costmap.resolution': str(resolution),
                'minimum_turning_radius': str(min_radius),
                'footprint': footprint_value,
                'footprint_padding': str(padding),
                'robot_base_frame': base_frame,
            },
            convert_types=True),
        allow_substs=True)

    map_server = Node(
        package='nav2_map_server', executable='map_server', name='map_server',
        output='screen', parameters=[configured_params])
    planner_server = Node(
        package='nav2_planner', executable='planner_server', name='planner_server',
        output='screen', parameters=[configured_params],
        remappings=[('/plan', '/planner_server/preview_plan')])
    lifecycle_manager = Node(
        package='nav2_lifecycle_manager', executable='lifecycle_manager',
        name='lifecycle_manager_planning', output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'autostart': True,
            'node_names': ['map_server', 'planner_server'],
        }])
    bridge = Node(
        package='smac_neupan_bridge', executable='smac_neupan_bridge',
        name='smac_neupan_bridge', output='screen',
        parameters=[{
            'use_sim_time': use_sim_time,
            'global_frame': 'map',
            'robot_frame': base_frame,
            'planner_action': '/compute_path_to_pose',
            'planner_id': 'GridBased',
            'execution_path_topic': '/plan',
        }])
    return [map_server, planner_server, lifecycle_manager, bridge]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('map', default_value=''),
        DeclareLaunchArgument('map_pgm', default_value=''),
        DeclareLaunchArgument('vehicle_config', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        OpaqueFunction(function=_planner),
    ])

"""Start shared real-vehicle sensors and motion interface.

Project-level vehicle geometry and limits come from a root config/vehicle.yaml
file supplied through the ``vehicle_config`` launch argument. Device/network
settings remain local to their owning drivers.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _enabled(context, name):
    return LaunchConfiguration(name).perform(context).strip().lower() in {
        '1', 'true', 'yes', 'on'
    }


def _configured_components(context, motion_interface_share):
    enable_control = _enabled(context, 'enable_control')
    enable_command_gate = _enabled(context, 'enable_command_gate')
    if not enable_control:
        if enable_command_gate:
            raise RuntimeError('enable_command_gate requires enable_control:=true')
        return []

    vehicle_config = LaunchConfiguration('vehicle_config').perform(context)
    if not vehicle_config:
        raise RuntimeError(
            "vehicle_config is required when the motion interface is enabled"
        )
    if not os.path.isfile(vehicle_config):
        raise RuntimeError(f"Vehicle config does not exist: {vehicle_config}")

    actions = [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(
                    motion_interface_share,
                    'launch',
                    'motion_interface.launch.py',
                )
            ),
            launch_arguments={
                'vehicle_config': vehicle_config,
                'enable_command_gate': str(enable_command_gate).lower(),
                'enable_navigation_rules': LaunchConfiguration('enable_navigation_rules'),
                'enable_stm32_bridge': str(enable_control).lower(),
                'bridge_params_file': LaunchConfiguration('bridge_params_file'),
                'status_params_file': LaunchConfiguration('status_params_file'),
                'use_sim_time': 'false',
            }.items(),
        )
    ]

    return actions


def generate_launch_description():
    lidar_share = get_package_share_directory('lidar_driver')
    imu_share = get_package_share_directory('imu')
    motion_interface_share = get_package_share_directory('motion_interface')

    default_lidar_config = os.path.join(lidar_share, 'config', 'config.yaml')
    arguments = [
        DeclareLaunchArgument(
            'vehicle_config',
            default_value='',
            description='Absolute path to project-level config/vehicle.yaml.',
        ),
        DeclareLaunchArgument(
            'enable_lidar',
            default_value='false',
            description='Start the Hesai LiDAR driver.',
        ),
        DeclareLaunchArgument(
            'lidar_config',
            default_value=default_lidar_config,
            description='Path to lidar_driver YAML configuration.',
        ),
        DeclareLaunchArgument(
            'lidar_rviz',
            default_value='false',
            description='Start the LiDAR driver RViz window.',
        ),
        DeclareLaunchArgument(
            'enable_imu',
            default_value='false',
            description='Start the LPMS-IG1 RS232 IMU driver.',
        ),
        DeclareLaunchArgument('enable_navigation_rules', default_value='false'),
        DeclareLaunchArgument('imu_port', default_value='/dev/ttyUSB0'),
        DeclareLaunchArgument('imu_sensor_id', default_value='1'),
        DeclareLaunchArgument('imu_frame_id', default_value='imu_link'),
        DeclareLaunchArgument(
            'imu_params_file',
            default_value=os.path.join(
                imu_share, 'config', 'lpms_ig1_rs232_calibration.yaml'
            ),
            description='LPMS-IG1 software calibration parameter file.',
        ),
        DeclareLaunchArgument(
            'enable_control',
            default_value='false',
            description='Start the real-vehicle STM32 motion interface backend.',
        ),
        DeclareLaunchArgument(
            'enable_command_gate',
            default_value='false',
            description='Enable the Ackermann command gate with the motion interface.',
        ),
        DeclareLaunchArgument(
            'bridge_params_file',
            default_value=os.path.join(
                motion_interface_share, 'config', 'bridge_params.yaml'
            ),
            description=(
                'Path to the motion_interface STM32 bridge YAML. Defaults to '
                'the installed copy; scripts/start_vehicle.sh overrides it '
                'with the workspace-local file.'
            ),
        ),
        DeclareLaunchArgument(
            'status_params_file',
            default_value=os.path.join(
                motion_interface_share, 'config', 'status_params.yaml'
            ),
            description=(
                'Path to the motion_interface sta__ receiver YAML. Defaults to '
                'the installed copy; scripts/start_vehicle.sh overrides it '
                'with the workspace-local file.'
            ),
        ),
    ]

    lidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(lidar_share, 'launch', 'start.py')
        ),
        condition=IfCondition(LaunchConfiguration('enable_lidar')),
        launch_arguments={
            'config_path': LaunchConfiguration('lidar_config'),
            'with_rviz': LaunchConfiguration('lidar_rviz'),
        }.items(),
    )

    imu = Node(
        package='imu',
        executable='lpms_ig1_node',
        name='lpms_ig1_node',
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_imu')),
        parameters=[
            os.path.join(imu_share, 'config', 'lpms_ig1.yaml'),
            LaunchConfiguration('imu_params_file'),
            {
                'port': LaunchConfiguration('imu_port'),
                'sensor_id': ParameterValue(
                    LaunchConfiguration('imu_sensor_id'), value_type=int
                ),
                'frame_id': LaunchConfiguration('imu_frame_id'),
                'invert_accel_for_ros': True,
                'convert_nwu_to_enu': True,
                'use_sim_time': False,
            },
        ],
    )

    configured = OpaqueFunction(
        function=_configured_components,
        args=[motion_interface_share],
    )

    return LaunchDescription(arguments + [lidar, imu, configured])

#!/usr/bin/env python3
"""Launch the real-vehicle command gate and STM32 hardware bridge."""

import math
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _enabled(context, name):
    return LaunchConfiguration(name).perform(context).strip().lower() in {
        '1', 'true', 'yes', 'on'
    }


def _require_finite_number(mapping, key, section):
    if key not in mapping:
        raise RuntimeError(f'Missing {section}.{key}')
    value = float(mapping[key])
    if not math.isfinite(value):
        raise RuntimeError(f'{section}.{key} must be finite')
    return value


def _load_control_limits(path):
    if not path:
        raise RuntimeError(
            "vehicle_config is required when the STM32 bridge is enabled"
        )
    if not os.path.isfile(path):
        raise RuntimeError(f'Vehicle config does not exist: {path}')

    with open(path, encoding='utf-8') as stream:
        data = yaml.safe_load(stream) or {}

    limits = data.get('vehicle', {}).get('control_limits', {})
    section = 'vehicle.control_limits'
    max_speed = _require_finite_number(
        limits, 'max_forward_speed', section
    )
    max_reverse_speed = _require_finite_number(
        limits, 'max_reverse_speed', section
    )
    max_steer_deg = _require_finite_number(
        limits, 'max_steering_angle_deg', section
    )

    if max_speed < 0.0:
        raise RuntimeError(f'{section}.max_forward_speed must be >= 0')
    if max_reverse_speed > 0.0:
        raise RuntimeError(f'{section}.max_reverse_speed must be <= 0')
    if max_steer_deg < 0.0:
        raise RuntimeError(f'{section}.max_steering_angle_deg must be >= 0')

    return {
        'max_speed': max_speed,
        'max_reverse_speed': max_reverse_speed,
        'max_steer_deg': max_steer_deg,
    }


def _resolve_params_file(context, argument, needed_for):
    path = LaunchConfiguration(argument).perform(context)
    if not path:
        raise RuntimeError(f'{argument} is required when {needed_for}')
    if not os.path.isfile(path):
        raise RuntimeError(f'{argument} does not exist: {path}')
    return path


def _configured_nodes(context):
    enable_gate = _enabled(context, 'enable_command_gate')
    enable_bridge = _enabled(context, 'enable_stm32_bridge')
    enable_status = _enabled(context, 'enable_status_receiver')
    if not enable_gate and not enable_bridge and not enable_status:
        return []

    use_sim_time = LaunchConfiguration('use_sim_time')
    actions = []

    if enable_gate:
        actions.append(
            Node(
                package='motion_interface',
                executable='command_gate',
                name='motion_command_gate',
                output='screen',
                parameters=[{
                    'use_sim_time': use_sim_time,
                    'input_topic': LaunchConfiguration('input_topic'),
                    'output_topic': LaunchConfiguration('output_topic'),
                    'navigation_rules_required': LaunchConfiguration('enable_navigation_rules'),
                }],
            )
        )

    if enable_bridge:
        vehicle_config = LaunchConfiguration('vehicle_config').perform(context)
        limits = _load_control_limits(vehicle_config)
        bridge_params = _resolve_params_file(
            context, 'bridge_params_file', 'enable_stm32_bridge=true'
        )
        actions.append(
            Node(
                package='motion_interface',
                executable='stm32_bridge',
                name='stm32_vehicle_bridge',
                output='screen',
                parameters=[
                    bridge_params,
                    {
                        'use_sim_time': use_sim_time,
                        **limits,
                    },
                ],
                emulate_tty=True,
            )
        )

    if enable_status:
        # Purely passive: receives and validates the board's sta__ feedback and
        # publishes nothing. Runs independently of the bridge because the board
        # ARPs for the host itself and does not need a cmd__ first, which is
        # what makes the "receive only, command nothing" bench check possible.
        #
        # No use_sim_time here on purpose: its loss detection is timed against
        # the host's monotonic clock, which must not move with simulated time.
        status_params = _resolve_params_file(
            context, 'status_params_file', 'enable_status_receiver=true'
        )
        actions.append(
            Node(
                package='motion_interface',
                executable='stm32_status',
                name='stm32_status',
                output='screen',
                parameters=[status_params],
                emulate_tty=True,
            )
        )

    return actions


def generate_launch_description():
    package_share = get_package_share_directory('motion_interface')

    return LaunchDescription([
        DeclareLaunchArgument(
            'vehicle_config',
            default_value='',
            description=(
                'Absolute path to project-level config/vehicle.yaml. Required '
                'when enable_stm32_bridge=true.'
            ),
        ),
        DeclareLaunchArgument('enable_navigation_rules', default_value='false'),
        DeclareLaunchArgument('enable_command_gate', default_value='true'),
        DeclareLaunchArgument('enable_stm32_bridge', default_value='true'),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument(
            'input_topic',
            default_value='/neupan_cmd_vel_raw',
        ),
        DeclareLaunchArgument(
            'output_topic',
            default_value='/ackermann_cmd',
        ),
        DeclareLaunchArgument(
            'bridge_params_file',
            default_value=os.path.join(
                package_share, 'config', 'bridge_params.yaml'
            ),
            description=(
                'Path to the STM32 bridge YAML (UDP host/port, bind device, '
                'enable mask, control timing). Defaults to the installed copy; '
                'callers pass an explicit path to use a workspace-local file.'
            ),
        ),
        DeclareLaunchArgument(
            'enable_status_receiver',
            default_value='true',
            description=(
                'Start the passive sta__ status receiver. It publishes nothing '
                'and sends no control frame, so it is safe to leave on and is '
                'what the "receive status only" bench check runs.'
            ),
        ),
        DeclareLaunchArgument(
            'status_params_file',
            default_value=os.path.join(
                package_share, 'config', 'status_params.yaml'
            ),
            description=(
                'Path to the sta__ receiver YAML (bind device/address, status '
                'port, loss threshold). Defaults to the installed copy; '
                'callers pass an explicit path to use a workspace-local file.'
            ),
        ),
        OpaqueFunction(
            function=_configured_nodes,
        ),
    ])

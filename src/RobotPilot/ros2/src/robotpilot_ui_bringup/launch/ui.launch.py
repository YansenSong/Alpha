from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    use_sim_time = LaunchConfiguration("use_sim_time", default="true")

    ui_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare("robotpilot_ui_package"), "launch", "new_ui_launch.py"]
            )
        ),
        launch_arguments={"use_sim_time": use_sim_time}.items(),
    )

    route_store = Node(
        package="robotpilot_ui_package",
        executable="route_store",
        name="route_store",
        output="screen",
    )

    map_manager = Node(
        package="robotpilot_ui_package",
        executable="handler",
        name="ui_map_manager",
        output="screen",
        parameters=[{"map_management_only": True, "open_browser": False}],
    )

    return LaunchDescription([ui_launch, route_store, map_manager])

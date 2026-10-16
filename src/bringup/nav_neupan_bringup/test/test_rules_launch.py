import importlib.util
from pathlib import Path

import yaml
from launch import LaunchContext
from launch_ros.actions import Node

ROOT = Path(__file__).resolve().parents[4]


def load(name):
    path = Path(__file__).resolve().parents[1] / 'launch' / name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.get_package_share_directory = lambda package: str(ROOT / 'src/bringup' / package)
    return module


def test_scan_launch_binds_area_rules_to_vehicle_frame(tmp_path):
    navigation = load('navigation.launch.py')
    config = yaml.safe_load((ROOT / 'config/vehicle.yaml').read_text())
    config['vehicle']['sensor_mounting']['lidar']['status'] = 'VERIFIED'
    config['vehicle']['planning']['footprint']['status'] = 'VERIFIED'
    path = tmp_path / 'vehicle.yaml'; path.write_text(yaml.safe_dump(config))
    context = LaunchContext()
    context.launch_configurations.update(vehicle_config=str(path), use_sim_time='false',
                                        rules_odom_topic='/test/odom', points_topic='/test/points')
    actions = navigation._scan_node(context)
    rules = next(a for a in actions if a._Node__package == 'area_rules')
    from launch_ros.utilities import evaluate_parameters
    parameters = evaluate_parameters(context, rules._Node__parameters)[0]
    assert parameters['robot_frame'] == config['vehicle']['frames']['base']
    assert parameters['odom_topic'] == '/test/odom'
    assert parameters['use_sim_time'] is False


def test_navigation_composes_map_monitor_and_external_adapter():
    module = load('navigation.launch.py')
    nodes = [a for a in module.generate_launch_description().entities if isinstance(a, Node)]
    assert {'map_bundle_monitor', 'mission_manager', 'inspection_adapter'} <= {
        n._Node__node_executable for n in nodes}
    adapter = next(n for n in nodes if n._Node__package == 'inspection_adapter')
    assert adapter.condition is not None

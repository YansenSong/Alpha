import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from inspection_adapter.node import InspectionAdapter


class PublisherSpy:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class AdapterFixtureTest(unittest.TestCase):
    def test_external_pending_request_survives_adapter_restart_without_redispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            old = {key: os.environ.get(key) for key in
                   ("INSPECTION_PROVIDER_MODE", "INSPECTION_ADAPTER_DB")}
            os.environ["INSPECTION_PROVIDER_MODE"] = "external"
            os.environ["INSPECTION_ADAPTER_DB"] = os.path.join(directory, "adapter.sqlite3")
            rclpy.init()
            request = {"schema_version": 1, "action_run_id": "external-action-1",
                       "robot_id": "robot-001", "mission_id": "mission-1", "task_id": "task-1",
                       "step_id": "step-1", "attempt": 1, "map_id": "map-1",
                       "map_version_id": "version-1", "waypoint_id": "wp-1", "asset_ids": [],
                       "kind": "detect", "detector_types": ["fire_smoke"], "parameters": {},
                       "requested_at": datetime.now(timezone.utc).isoformat(), "timeout_ms": 120000,
                       "source_mode": "simulation"}
            capability = {"provider_id": "provider-1", "source_mode": "simulation",
                          "action_map": {"detect": {"supported": True}}}
            adapter = None
            try:
                adapter = InspectionAdapter()
                adapter.capabilities = capability
                adapter.capabilities_seen = time.monotonic()
                adapter.heartbeat_seen = time.monotonic()
                provider_requests = PublisherSpy()
                adapter.provider_request_pub = provider_requests
                adapter.on_request(String(data=json.dumps(request)))
                self.assertEqual(len(provider_requests.messages), 1)
                adapter.db.close()
                adapter.destroy_node()
                adapter = InspectionAdapter()
                adapter.capabilities = capability
                adapter.capabilities_seen = time.monotonic()
                adapter.heartbeat_seen = time.monotonic()
                provider_requests = PublisherSpy()
                adapter.provider_request_pub = provider_requests
                results = PublisherSpy()
                adapter.result_pub = results
                self.assertIn(request["action_run_id"], adapter.pending)
                adapter.on_request(String(data=json.dumps(request)))
                self.assertEqual(provider_requests.messages, [])
                result = {"schema_version": 1, "result_id": "result-1",
                          "robot_id": "robot-001", "mission_id": "mission-1",
                          "task_id": "task-1", "step_id": "step-1", "attempt": 1,
                          "action_run_id": "external-action-1", "status": "SUCCEEDED",
                          "outcome": "INCONCLUSIVE", "source_mode": "simulation",
                          "observed_at": "2026-10-10T00:00:01Z", "map_id": "map-1",
                          "map_version_id": "version-1", "confidence": None}
                adapter.on_provider_result(String(data=json.dumps(result)))
                self.assertEqual(len(results.messages), 1)
                adapter.on_request(String(data=json.dumps(request)))
                self.assertEqual(json.loads(results.messages[-1].data)["result_id"], "result-1")
                lost_request = {**request, "action_run_id": "external-action-2",
                                "step_id": "step-2"}
                adapter.on_request(String(data=json.dumps(lost_request)))
                adapter.pending_deadline["external-action-2"] = time.monotonic() - 1
                adapter.expire_pending()
                lost_result = json.loads(results.messages[-1].data)
                self.assertEqual(lost_result["status"], "TIMEOUT")
                self.assertEqual(lost_result["source_mode"], "simulation")
                self.assertEqual(len(provider_requests.messages), 1)
            finally:
                if adapter is not None:
                    adapter.db.close()
                    adapter.destroy_node()
                rclpy.shutdown()
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_fixture_result_is_explicit_and_duplicate_request_replays_same_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            old = {key: os.environ.get(key) for key in
                   ("INSPECTION_PROVIDER_MODE", "INSPECTION_FIXTURE_SCENARIO", "INSPECTION_ADAPTER_DB")}
            os.environ["INSPECTION_PROVIDER_MODE"] = "fixture"
            os.environ["INSPECTION_FIXTURE_SCENARIO"] = "inconclusive"
            os.environ["INSPECTION_ADAPTER_DB"] = os.path.join(directory, "adapter.sqlite3")
            rclpy.init()
            adapter = InspectionAdapter()
            client = Node("inspection_fixture_test_client")
            received = []
            publisher = client.create_publisher(String, "/inspection/action/request", 10)
            client.create_subscription(String, "/inspection/action/result",
                                       lambda message: received.append(json.loads(message.data)), 10)
            executor = SingleThreadedExecutor()
            executor.add_node(adapter)
            executor.add_node(client)
            request = {"schema_version": 1, "action_run_id": "fixture-action-1",
                       "robot_id": "robot-001", "mission_id": "mission-1", "task_id": "task-1",
                       "step_id": "step-1", "attempt": 1, "map_id": "map-1",
                       "map_version_id": "version-1", "waypoint_id": "wp-1", "asset_ids": [],
                       "kind": "detect", "detector_types": ["fire_smoke"], "parameters": {},
                       "requested_at": "2026-10-10T00:00:00Z", "timeout_ms": 1000,
                       "source_mode": "simulation"}
            try:
                executor.spin_once(timeout_sec=0.05)
                publisher.publish(String(data=json.dumps(request)))
                deadline = time.monotonic() + 2
                while not received and time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.05)
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0]["outcome"], "INCONCLUSIVE")
                self.assertEqual(received[0]["source_mode"], "fixture")
                self.assertIsNone(received[0]["confidence"])
                result_id = received[0]["result_id"]
                publisher.publish(String(data=json.dumps(request)))
                deadline = time.monotonic() + 2
                while len(received) < 2 and time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.05)
                self.assertEqual(received[1]["result_id"], result_id)
            finally:
                executor.remove_node(client)
                executor.remove_node(adapter)
                client.destroy_node()
                adapter.db.close()
                adapter.destroy_node()
                executor.shutdown()
                rclpy.shutdown()
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

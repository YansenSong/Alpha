import pytest

from inspection_adapter.contract import validate_capabilities, validate_request, validate_result


def request():
    return {"schema_version": 1, "action_run_id": "action-1", "robot_id": "robot-1",
            "mission_id": "mission-1", "task_id": "task-1", "step_id": "step-1",
            "attempt": 1, "map_id": "map-1", "map_version_id": "map-v1",
            "waypoint_id": "wp-1", "kind": "detect", "detector_types": ["fire_smoke"],
            "asset_ids": [], "parameters": {}, "requested_at": "2026-10-10T00:00:00Z",
            "timeout_ms": 15000}


def test_request_requires_versioned_identity_and_timezone():
    assert validate_request(request(), "robot-1")["action_run_id"] == "action-1"
    with pytest.raises(ValueError, match="another robot"):
        validate_request({**request(), "robot_id": "other"}, "robot-1")
    with pytest.raises(ValueError, match="timezone"):
        validate_request({**request(), "requested_at": "2026-10-10T00:00:00"}, "robot-1")
    with pytest.raises(ValueError, match="size"):
        validate_request({**request(), "parameters": {"large": "x" * 70000}}, "robot-1")


def test_capability_and_result_correlation_are_checked():
    caps = {"schema_version": 1, "robot_id": "robot-1", "provider_id": "provider-1",
            "source_mode": "fixture", "actions": [{"kind": "detect", "supported": True}]}
    assert validate_capabilities(caps, "robot-1")["action_map"]["detect"]["supported"]
    req = request()
    response = {"schema_version": 1, "result_id": "result-1", "robot_id": "robot-1",
                "mission_id": "mission-1", "task_id": "task-1", "step_id": "step-1",
                "attempt": 1, "action_run_id": "action-1", "status": "SUCCEEDED",
                "outcome": "INCONCLUSIVE", "source_mode": "fixture",
                "observed_at": "2026-10-10T00:00:01Z", "map_id": "map-1",
                "map_version_id": "map-v1", "confidence": None}
    assert validate_result(response, req, "robot-1")["outcome"] == "INCONCLUSIVE"
    with pytest.raises(ValueError, match="does not match"):
        validate_result({**response, "task_id": "other"}, req, "robot-1")
    with pytest.raises(ValueError, match="confidence"):
        validate_result({**response, "confidence": float("nan")}, req, "robot-1")
    with pytest.raises(ValueError, match="media paths"):
        validate_result({**response, "evidence": [{"evidence_id": "e1", "path": "/private/image.jpg"}]},
                        req, "robot-1")

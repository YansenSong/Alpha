"""Strict, model-agnostic validation for provider messages."""

import json
import math
from datetime import datetime


SOURCE_MODES = {"fixture", "simulation", "hardware"}
ACTION_KINDS = {"capture", "detect", "broadcast"}
OUTCOMES = {"NORMAL", "ABNORMAL", "INCONCLUSIVE", "NOT_APPLICABLE"}
STATUSES = {"SUCCEEDED", "FAILED", "UNAVAILABLE", "TIMEOUT"}


def parse_object(raw, maximum_bytes=65536):
    if isinstance(raw, str):
        if len(raw.encode("utf-8")) > maximum_bytes:
            raise ValueError("message exceeds size limit")
        value = json.loads(raw)
    else:
        value = raw
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("unsupported message schema")
    return value


def validate_request(raw, robot_id):
    request = parse_object(raw)
    required = ("action_run_id", "task_id", "step_id", "mission_id",
                "map_id", "map_version_id", "requested_at")
    if any(not isinstance(request.get(key), str) or not request[key] for key in required):
        raise ValueError("request identity is incomplete")
    if request.get("robot_id") != robot_id:
        raise ValueError("request belongs to another robot")
    if request.get("kind") not in ACTION_KINDS:
        raise ValueError("unsupported action kind")
    attempt = request.get("attempt")
    timeout_ms = request.get("timeout_ms")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= 120000:
        raise ValueError("timeout_ms is out of range")
    requested_at = datetime.fromisoformat(request["requested_at"].replace("Z", "+00:00"))
    if requested_at.tzinfo is None:
        raise ValueError("requested_at must include timezone")
    encoded = json.dumps(request, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("request exceeds size limit")
    return request


def validate_capabilities(raw, robot_id):
    value = parse_object(raw)
    if value.get("robot_id") != robot_id or not isinstance(value.get("provider_id"), str):
        raise ValueError("capability identity is invalid")
    if value.get("source_mode") not in SOURCE_MODES or not isinstance(value.get("actions"), list):
        raise ValueError("capability source or actions are invalid")
    actions = {}
    for item in value["actions"]:
        if not isinstance(item, dict) or item.get("kind") not in ACTION_KINDS:
            raise ValueError("capability action is invalid")
        if not isinstance(item.get("supported"), bool):
            raise ValueError("supported must be boolean")
        actions[item["kind"]] = item
    return {**value, "action_map": actions}


def validate_result(raw, request, robot_id):
    result = parse_object(raw)
    allowed = {"schema_version", "provider_id", "result_id", "robot_id", "mission_id", "task_id",
               "step_id", "attempt", "action_run_id", "status", "outcome", "detector_type",
               "confidence", "observed_at", "source_mode", "model_version", "map_id",
               "map_version_id", "waypoint_id", "asset_ids", "position", "classifications",
               "evidence", "fixture_scenario", "reason_code"}
    if set(result) - allowed:
        raise ValueError("result contains unsupported fields; media paths are prohibited")
    for key in ("action_run_id", "task_id", "step_id", "attempt"):
        if result.get(key) != request.get(key):
            raise ValueError(f"result {key} does not match request")
    for key in ("mission_id", "map_id", "map_version_id"):
        if result.get(key) != request.get(key):
            raise ValueError(f"result {key} does not match request")
    if result.get("robot_id") != robot_id or result.get("status") not in STATUSES:
        raise ValueError("result identity or status is invalid")
    if result.get("outcome") not in OUTCOMES or result.get("source_mode") not in SOURCE_MODES:
        raise ValueError("result outcome or source mode is invalid")
    if result.get("status") != "SUCCEEDED" and result.get("outcome") != "NOT_APPLICABLE":
        raise ValueError("unsuccessful action cannot claim a detection outcome")
    if not isinstance(result.get("result_id"), str) or not result["result_id"]:
        raise ValueError("result_id is required")
    observed_at = result.get("observed_at")
    if not isinstance(observed_at, str) or datetime.fromisoformat(observed_at.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("observed_at must include timezone")
    confidence = result.get("confidence")
    if confidence is not None and (isinstance(confidence, bool)
                                   or not isinstance(confidence, (float, int))
                                   or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError("confidence must be finite in [0,1] or null")
    evidence = result.get("evidence", [])
    evidence_fields = {"evidence_id", "media_type", "checksum", "size_bytes"}
    if not isinstance(evidence, list) or len(evidence) > 20 or any(
        not isinstance(item, dict) or set(item) - evidence_fields for item in evidence
    ):
        raise ValueError("evidence must contain safe metadata only; media paths are prohibited")
    position = result.get("position")
    if position is not None and (not isinstance(position, dict)
                                 or set(position) - {"frame_id", "x", "y", "yaw", "observed_at"}):
        raise ValueError("position metadata is invalid")
    classifications = result.get("classifications", [])
    classification_fields = {"detector_type", "label", "class_id", "value", "confidence"}
    if not isinstance(classifications, list) or len(classifications) > 100 or any(
        not isinstance(item, dict) or set(item) - classification_fields for item in classifications
    ):
        raise ValueError("classification metadata is invalid")
    if result.get("reason_code") not in (None, "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_FAILED", "PROVIDER_REJECTED"):
        raise ValueError("reason_code is invalid")
    return result

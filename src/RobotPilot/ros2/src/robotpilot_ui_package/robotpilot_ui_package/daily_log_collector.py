"""Collect ROS console records into one readable file per node and local day."""

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rcl_interfaces.msg import Log

from .data_paths import setting


LEVEL_NAMES = {
    Log.DEBUG: "DEBUG",
    Log.INFO: "INFO",
    Log.WARN: "WARN",
    Log.ERROR: "ERROR",
    Log.FATAL: "FATAL",
}


def log_filename(logger_name, day):
    name = str(logger_name or "ros_node")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-") or "ros_node"
    if safe != name or len(safe) > 80:
        safe = f"{safe[:72]}-{hashlib.sha256(name.encode()).hexdigest()[:8]}"
    return f"{safe}_{day}.log"


class DailyLogCollector(Node):
    def __init__(self):
        super().__init__("daily_log_collector", namespace="ui")
        self.log_directory = Path(setting("LOG_ROOT", "~/.ros/log")).expanduser() / "daily"
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self._day = None
        self._streams = {}
        self.create_subscription(
            Log,
            "/rosout",
            self._record,
            QoSProfile(
                depth=1000,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            ),
        )

    def _record(self, message):
        timestamp = datetime.fromtimestamp(
            message.stamp.sec + message.stamp.nanosec / 1_000_000_000,
            timezone.utc,
        ).astimezone()
        day = timestamp.strftime("%Y-%m-%d")
        if day != self._day:
            self.close_files()
            self._day = day

        filename = log_filename(message.name, day)
        stream = self._streams.get(filename)
        if stream is None:
            path = self.log_directory / filename
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o600)
            stream = os.fdopen(descriptor, "a", encoding="utf-8", buffering=1)
            self._streams[filename] = stream
        level = LEVEL_NAMES.get(message.level, str(message.level))
        timestamp_text = timestamp.isoformat(timespec="milliseconds")
        for line in (message.msg or "").splitlines() or [""]:
            stream.write(f"[{level}] [{timestamp_text}] [{message.name}]: {line}\n")

    def close_files(self):
        for stream in self._streams.values():
            stream.close()
        self._streams.clear()


def main(args=None):
    rclpy.init(args=args)
    node = DailyLogCollector()
    try:
        rclpy.spin(node)
    finally:
        node.close_files()
        node.destroy_node()
        rclpy.shutdown()

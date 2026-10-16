"""Build and frontend artifact identity for the operator status API."""

import hashlib
import os
from pathlib import Path
import xml.etree.ElementTree as ElementTree


def _package_version(share_directory):
    if not share_directory:
        return "unknown"
    package_xml = Path(share_directory) / "package.xml"
    try:
        version = ElementTree.parse(package_xml).findtext("version")
    except (ElementTree.ParseError, OSError):
        return "unknown"
    return version or "unknown"


def get_build_info(share_directory=None):
    """Return non-secret build metadata without exposing host paths."""
    package_version = _package_version(share_directory)
    frontend_build = "unknown"
    if share_directory:
        index_file = Path(share_directory) / "static" / "app" / "index.html"
        try:
            frontend_build = hashlib.sha256(index_file.read_bytes()).hexdigest()[:16]
        except OSError:
            pass
    return {
        "package": "robotpilot_ui_package",
        "version": os.environ.get("ROBOTPILOT_BUILD_VERSION", package_version),
        "package_version": package_version,
        "commit": os.environ.get("ROBOTPILOT_BUILD_COMMIT", "unknown"),
        "built_at": os.environ.get("ROBOTPILOT_BUILD_TIME", "unknown"),
        "ros_distro": os.environ.get("ROS_DISTRO", "unknown"),
        "frontend_build": frontend_build,
        "robot_mode": os.environ.get("ROBOT_MODE", "unknown"),
        "battery_source": os.environ.get("BATTERY_SOURCE", "disabled"),
    }

"""Verify the LIO-SAM export becomes a map the UI can catalog."""

import os
import sys
from types import SimpleNamespace

from robotpilot_ui_package.folders_handler import UIFoldersHandler


class _Handler:
    def __init__(self):
        self.messages = []
        self.refreshed = False
        self._save_map_busy = True

    def _pub(self, message):
        self.messages.append(message)

    def _pub_nav_data(self):
        self.refreshed = True

    def get_logger(self):
        return SimpleNamespace(error=lambda message: self.messages.append(message))


def test_lio_save_creates_catalog_map_and_keeps_point_cloud(tmp_path):
    group = tmp_path / "Warehouse"
    staging = group / ".FloorA.saving-test"
    snapshot = staging / "20261008_120000"
    snapshot.mkdir(parents=True)
    (snapshot / "GlobalMap.pcd").write_bytes(b"point cloud")
    converter = tmp_path / "converter"
    converter.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "prefix = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
        "prefix.with_suffix('.pgm').write_bytes(b'P5')\n"
        "prefix.with_suffix('.yaml').write_text('image: FloorA.pgm\\n')\n"
    )
    os.chmod(converter, 0o755)
    handler = _Handler()
    future = SimpleNamespace(result=lambda: SimpleNamespace(success=True))
    map_base = group / "FloorA"
    routes = tmp_path / "routes" / "Warehouse" / "FloorA"

    UIFoldersHandler._finish_lio_map_save(
        handler, future, str(staging), str(map_base), str(routes),
        str(converter), "FloorA",
    )

    assert (map_base / "GlobalMap.pcd").read_bytes() == b"point cloud"
    assert (group / "FloorA.pgm").read_bytes() == b"P5"
    assert (group / "FloorA.yaml").read_text() == "image: FloorA.pgm\n"
    assert (map_base / "map.pgm").read_bytes() == b"P5"
    assert (map_base / "map.yaml").read_text() == "image: map.pgm\n"
    assert routes.is_dir()
    assert not staging.exists()
    assert handler.refreshed
    assert handler.messages == ['Map saved "FloorA"']
    assert not handler._save_map_busy


def test_lio_save_failure_reports_error_without_publishing_map(tmp_path):
    handler = _Handler()
    future = SimpleNamespace(result=lambda: SimpleNamespace(success=False))
    map_base = tmp_path / "Warehouse" / "FloorA"

    UIFoldersHandler._finish_lio_map_save(
        handler, future, str(tmp_path / "staging"), str(map_base),
        str(tmp_path / "routes"), str(tmp_path / "converter"), "FloorA",
    )

    assert not map_base.with_suffix(".yaml").exists()
    assert not handler.refreshed
    assert any(message.startswith("Map save failed:") for message in handler.messages)
    assert not handler._save_map_busy

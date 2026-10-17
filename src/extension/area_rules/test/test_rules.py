import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from area_rules.rules import (RuleStore, covers, grid_to_world, map_key, occupancy_map_id,
                                        rasterize, validate_rule, active)


def grid(yaw=0):
    quaternion = SimpleNamespace(x=0, y=0, z=math.sin(yaw / 2), w=math.cos(yaw / 2))
    origin = SimpleNamespace(position=SimpleNamespace(x=-2.0, y=-4.0), orientation=quaternion)
    info = SimpleNamespace(width=80, height=80, resolution=0.1, origin=origin)
    return SimpleNamespace(header=SimpleNamespace(frame_id="map"),
                           info=info, data=[0] * (info.width * info.height))


class RuleTests(unittest.TestCase):
    def test_rotated_map_mask_marks_rule_and_not_distant_cells(self):
        occupancy = grid(math.pi / 3)
        rule = validate_rule({"id": "wall-1", "type": "wall", "name": "door",
                              "x1": 0, "y1": 0, "x2": 0, "y2": 1, "width": 0.1})
        mask = rasterize(occupancy.info, [rule], padding=0)
        marked = [(x, y) for y in range(80) for x in range(80) if mask[y * 80 + x] == 100]
        self.assertTrue(marked)
        self.assertTrue(any(covers(rule, *grid_to_world(occupancy.info, x, y)) for x, y in marked))
        self.assertFalse(any(math.hypot(*grid_to_world(occupancy.info, x, y)) > 3 for x, y in marked))

    def test_store_persists_by_map_and_rejects_stale_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            first = RuleStore(path)
            rule = {"id": "a", "name": "slow", "type": "speed", "cx": 1, "cy": 2,
                    "w": 2, "h": 2, "limit_mps": 0.2}
            first.mutate("map-a", 0, "upsert", rule)
            second = RuleStore(path)
            self.assertEqual(second.state("map-a")["rules"][0]["limit_mps"], 0.2)
            self.assertEqual(second.state("map-b")["rules"], [])
            with self.assertRaisesRegex(ValueError, "rules changed"):
                second.mutate("map-a", 0, "delete", {"id": "a"})
            self.assertNotEqual(map_key(grid()), map_key(grid(math.pi / 3)))
            self.assertEqual(len(occupancy_map_id(grid())), 12)
            self.assertNotEqual(occupancy_map_id(grid()), occupancy_map_id(grid(math.pi / 3)))

    def test_temporary_closure_duration_uses_robot_clock_and_persists_expiry(self):
        rule = validate_rule({"id": "work", "type": "closure", "cx": 1, "cy": 2,
                              "w": 1, "h": 1, "duration_seconds": 60})
        self.assertIn("expires_at", rule)
        self.assertNotIn("duration_seconds", rule)
        with self.assertRaisesRegex(ValueError, "duration"):
            validate_rule({"id": "bad", "type": "closure", "cx": 1, "cy": 2,
                           "w": 1, "h": 1, "duration_seconds": 0})

    def test_disabled_rules_remain_stored_but_do_not_block_and_can_be_reenabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            store = RuleStore(path)
            rule = {"id": "gate", "type": "keepout", "cx": 0, "cy": 0, "w": 1, "h": 1}
            enabled = store.mutate("m", 0, "upsert", rule)["rules"][0]
            self.assertTrue(enabled["enabled"])
            self.assertIn(100, rasterize(grid().info, [enabled], padding=0))
            disabled = store.mutate("m", 1, "set_enabled", {"id": "gate", "enabled": False})["rules"][0]
            self.assertFalse(active(disabled))
            self.assertNotIn(100, rasterize(grid().info, [disabled], padding=0))
            self.assertEqual(RuleStore(path).state("m")["rules"], [disabled])
            self.assertFalse(store.expire("m"))
            with self.assertRaisesRegex(ValueError, "rules changed"):
                store.mutate("m", 1, "set_enabled", {"id": "gate", "enabled": True})
            restored = store.mutate("m", 2, "set_enabled", {"id": "gate", "enabled": True})["rules"][0]
            self.assertEqual(restored, enabled)

    def test_toggle_preserves_closure_expiry_and_validates_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RuleStore(Path(directory) / "rules.json")
            rule = {"id": "closure", "type": "closure", "cx": 0, "cy": 0, "w": 1, "h": 1, "duration_seconds": 60}
            saved = store.mutate("m", 0, "upsert", rule)["rules"][0]
            for version, enabled in [(1, False), (2, True)]:
                result = store.mutate("m", version, "set_enabled", {"id": "closure", "enabled": enabled})
                self.assertEqual(result["rules"][0]["expires_at"], saved["expires_at"])
            with self.assertRaisesRegex(ValueError, "boolean"):
                store.mutate("m", 3, "set_enabled", {"id": "closure", "enabled": "false"})
            with self.assertRaisesRegex(ValueError, "boolean"):
                validate_rule({**rule, "enabled": 0})

    def test_invalid_limits_do_not_enter_store(self):
        with self.assertRaisesRegex(ValueError, "speed limit"):
            validate_rule({"id": "bad", "type": "speed", "cx": 0, "cy": 0,
                           "w": 1, "h": 1, "limit_mps": 0})


if __name__ == "__main__":
    unittest.main()

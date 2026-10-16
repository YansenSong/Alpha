import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock

from robotpilot_ui_package.battery_model import (
    advance_simulated_percent,
    normalize_percent,
    resolve_simulation_scenario,
    update_low_battery_latch,
)
from robotpilot_ui_package.battery import BatteryMonitor


class BatteryModelTest(unittest.TestCase):
    def test_normalize_percent_rejects_invalid_hardware_samples(self):
        self.assertEqual(normalize_percent("82.5"), 82.5)
        for value in ("", "unknown", -1, 101, float("nan"), float("inf")):
            self.assertIsNone(normalize_percent(value))

    def test_simulated_discharge_and_charge_are_deterministic(self):
        self.assertAlmostEqual(advance_simulated_percent(80, 5, False, 0.2, 1), 79)
        self.assertAlmostEqual(advance_simulated_percent(80, 5, True, 0.2, 1), 85)

    def test_simulated_percent_clamps_at_battery_limits(self):
        self.assertEqual(advance_simulated_percent(1, 10, False, 1, 1), 0)
        self.assertEqual(advance_simulated_percent(99, 10, True, 1, 1), 100)

    def test_negative_rates_are_rejected(self):
        with self.assertRaises(ValueError):
            advance_simulated_percent(50, 1, False, -0.1, 0.1)

    def test_named_scenarios_are_deterministic_and_bounded(self):
        self.assertEqual(resolve_simulation_scenario("low_battery", 50, 76.5), (10.0, False, True, ""))
        self.assertEqual(resolve_simulation_scenario("full", 50, 76.5), (100.0, True, True, ""))
        self.assertEqual(resolve_simulation_scenario("communication_lost", 44, 76.5), (44.0, False, False, ""))
        self.assertEqual(resolve_simulation_scenario("charging_fault", 50, 76.5)[3], "simulated_charging_failed")
        with self.assertRaises(ValueError):
            resolve_simulation_scenario("arbitrary", 50, 76.5)

    def test_platform_threshold_config_is_validated_and_applied(self):
        applied = []
        monitor = SimpleNamespace(
            source_mode="sim",
            threshold_config_version=0,
            set_parameters=lambda parameters: applied.extend(parameters),
        )
        BatteryMonitor._platform_config(
            monitor,
            SimpleNamespace(data='{"low_battery_threshold":25,"config_version":3}'),
        )
        self.assertEqual(monitor.threshold_config_version, 3)
        self.assertEqual(applied[0].name, "low_battery_threshold")
        self.assertEqual(applied[0].value, 25.0)
        BatteryMonitor._platform_config(
            monitor,
            SimpleNamespace(data='{"low_battery_threshold":100,"config_version":4}'),
        )
        self.assertEqual(monitor.threshold_config_version, 3)

    def test_low_battery_latch_has_recovery_margin_and_holds_unknown(self):
        active = update_low_battery_latch(False, 20, 20, True)
        self.assertTrue(active)
        self.assertTrue(update_low_battery_latch(active, 22, 20, True))
        self.assertFalse(update_low_battery_latch(active, 23, 20, True))
        self.assertTrue(update_low_battery_latch(active, None, 20, False))

    def test_serial_unavailable_does_not_fall_back_to_simulation(self):
        monitor = SimpleNamespace(
            source_mode="serial",
            last_tick=time.monotonic() - 1,
            serial_error="serial device unavailable",
            get_parameter=lambda name: SimpleNamespace(value=20),
            _read_serial_percent=lambda: None,
            _publish_state=Mock(),
        )

        BatteryMonitor.read_battery_status(monitor)

        monitor._publish_state.assert_called_once_with(
            reason="serial device unavailable"
        )

    def test_disabled_and_simulated_modes_publish_explicit_source(self):
        disabled = SimpleNamespace(
            source_mode="disabled",
            last_tick=time.monotonic(),
            get_parameter=lambda name: SimpleNamespace(value=20),
            _publish_state=Mock(),
        )
        BatteryMonitor.read_battery_status(disabled)
        disabled._publish_state.assert_called_once_with(
            reason="Battery telemetry is disabled"
        )

        values = {
            "sim_available": True,
            "sim_charging": True,
            "sim_drain_rate_percent_per_second": 0.1,
            "sim_charge_rate_percent_per_second": 1.0,
            "low_battery_threshold": 20,
        }
        simulated = SimpleNamespace(
            source_mode="sim",
            last_tick=time.monotonic() - 2,
            percent=50,
            get_parameter=lambda name: SimpleNamespace(value=values[name]),
            _publish_state=Mock(),
        )
        BatteryMonitor.read_battery_status(simulated)
        self.assertAlmostEqual(simulated.percent, 52, delta=0.05)
        simulated._publish_state.assert_called_once()
        self.assertEqual(simulated._publish_state.call_args.kwargs["source"], "simulated")
        self.assertTrue(simulated._publish_state.call_args.kwargs["charging"])


if __name__ == "__main__":
    unittest.main()

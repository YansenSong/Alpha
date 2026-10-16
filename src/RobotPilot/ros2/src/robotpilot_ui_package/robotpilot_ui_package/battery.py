"""Battery telemetry with explicit hardware, simulation, and disabled modes."""

import json
import signal
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32, String

from .battery_model import (
    advance_simulated_percent,
    normalize_percent,
    resolve_simulation_scenario,
    update_low_battery_latch,
)


class BatteryMonitor(Node):
    def __init__(self):
        super().__init__("battery_monitor")
        self.declare_parameter("battery_source", "disabled")
        self.declare_parameter("serial_port", "/dev/ttyUSB0")
        self.declare_parameter("serial_baud", 9600)
        self.declare_parameter("sim_initial_percent", 76.5)
        self.declare_parameter("sim_drain_rate_percent_per_second", 0.01)
        self.declare_parameter("sim_charge_rate_percent_per_second", 0.1)
        self.declare_parameter("sim_charging", False)
        self.declare_parameter("sim_available", True)
        self.declare_parameter("low_battery_threshold", 20.0)
        self.declare_parameter("sim_voltage_v", 24.7)
        self.declare_parameter("sim_discharge_current_a", 1.2)
        self.declare_parameter("sim_charge_current_a", 1.2)

        self.source_mode = str(self.get_parameter("battery_source").value).strip().lower()
        if self.source_mode not in ("sim", "serial", "disabled"):
            raise ValueError("battery_source must be one of: sim, serial, disabled")

        self.serial_port = None
        self.serial_error = ""
        self.percent = normalize_percent(self.get_parameter("sim_initial_percent").value)
        if self.percent is None:
            raise ValueError("sim_initial_percent must be from 0 through 100")
        self.last_tick = time.monotonic()
        self.legacy_pub = self.create_publisher(Float32, "/battery_status", 10)
        self.state_pub = self.create_publisher(String, "/battery/state", 10)
        self.create_subscription(String, "/battery/sim_scenario", self._sim_scenario, 10)
        self.sim_fault = ""
        self.return_to_charge_state = "not_available"
        self.threshold_config_version = 0
        # Start latched conservatively so a node restart at a value just above
        # threshold does not prematurely clear an existing platform fault.
        self.low_battery_active = True
        config_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, "/battery/platform_config", self._platform_config, config_qos)

        if self.source_mode == "serial":
            self._open_serial()
        self.timer = self.create_timer(1.0, self.read_battery_status)
        self.get_logger().info(f"Battery source configured as {self.source_mode}")

    def _open_serial(self):
        if self.serial_port and self.serial_port.is_open:
            return True
        try:
            import serial

            self.serial_port = serial.Serial(
                str(self.get_parameter("serial_port").value),
                int(self.get_parameter("serial_baud").value),
                timeout=1,
            )
            self.serial_error = ""
            return True
        except Exception as error:
            self.serial_port = None
            self.serial_error = f"Unable to open battery serial port: {error}"
            self.get_logger().warning(self.serial_error)
            return False

    @staticmethod
    def _observed_at():
        return datetime.now(timezone.utc).isoformat()

    def _publish_state(self, *, percent=None, source="unavailable", available=False,
                       charging=None, reason=""):
        threshold = float(self.get_parameter("low_battery_threshold").value)
        simulated = available and source == "simulated"
        voltage = float(self.get_parameter("sim_voltage_v").value) if simulated else None
        current = None
        charging_state = "unknown" if source == "hardware" and available else "unavailable"
        if simulated:
            charging_state = "charging" if charging else "discharging"
            current = float(self.get_parameter(
                "sim_charge_current_a" if charging else "sim_discharge_current_a"
            ).value) * (1 if charging else -1)
        self.low_battery_active = update_low_battery_latch(
            self.low_battery_active, percent, threshold, available
        )
        state = {
            "percent": percent if available else None,
            "source": source,
            "simulated": source == "simulated",
            "available": bool(available),
            "observed_at": self._observed_at(),
            "stale": False,
            "charging": charging if available else None,
            "low_battery_threshold": threshold,
            "threshold_config_version": self.threshold_config_version,
            "low_battery": self.low_battery_active if available else None,
            "voltage_v": voltage,
            "current_a": current,
            "charging_state": charging_state,
            "return_to_charge_state": self.return_to_charge_state,
            "fault": self.sim_fault if source == "simulated" else "",
            "reason": reason or self.sim_fault,
        }
        self.state_pub.publish(String(data=json.dumps(state, separators=(",", ":"))))
        if available:
            self.legacy_pub.publish(Float32(data=float(percent)))

    def _platform_config(self, message):
        if self.source_mode == "disabled":
            return
        try:
            payload = json.loads(message.data)
            threshold = payload["low_battery_threshold"]
            version = payload["config_version"]
            if (isinstance(threshold, bool) or not isinstance(threshold, int)
                    or not 1 <= threshold <= 99 or isinstance(version, bool)
                    or not isinstance(version, int) or version < 1):
                return
        except (ValueError, TypeError, KeyError):
            return
        self.set_parameters([Parameter("low_battery_threshold", value=float(threshold))])
        self.threshold_config_version = version

    def _sim_scenario(self, message):
        """Apply named, bounded scenarios; never permit controls in hardware mode."""
        if self.source_mode != "sim":
            return
        scenario = message.data.strip()
        try:
            self.percent, charging, available, self.sim_fault = resolve_simulation_scenario(
                scenario,
                self.percent,
                float(self.get_parameter("sim_initial_percent").value),
            )
        except ValueError:
            self.get_logger().warning(f"Ignoring unknown battery scenario: {scenario}")
            return
        self.set_parameters([
            Parameter("sim_charging", value=charging),
            Parameter("sim_available", value=available),
        ])

    def _read_serial_percent(self):
        if not self._open_serial():
            return None
        try:
            line = self.serial_port.readline().decode("utf-8").strip()
            if not line:
                self.serial_error = "Waiting for a battery reading from the serial device"
                return None
            percent = normalize_percent(line)
            if percent is None:
                self.serial_error = "Battery serial reading must be a number from 0 through 100"
                return None
            self.serial_error = ""
            return percent
        except Exception as error:
            self.serial_error = f"Error reading battery serial device: {error}"
            try:
                self.serial_port.close()
            except Exception:
                pass
            self.serial_port = None
            self.get_logger().error(self.serial_error)
            return None

    def read_battery_status(self):
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_tick)
        self.last_tick = now

        if self.source_mode == "disabled":
            self._publish_state(reason="Battery telemetry is disabled")
            return

        if self.source_mode == "serial":
            percent = self._read_serial_percent()
            if percent is None:
                self._publish_state(reason=self.serial_error or "Battery reading unavailable")
                return
            self._publish_state(percent=percent, source="hardware", available=True)
            return

        if not bool(self.get_parameter("sim_available").value):
            self._publish_state(reason="Simulated battery communication is unavailable")
            return

        charging = bool(self.get_parameter("sim_charging").value)
        self.percent = advance_simulated_percent(
            self.percent,
            elapsed,
            charging,
            float(self.get_parameter("sim_drain_rate_percent_per_second").value),
            float(self.get_parameter("sim_charge_rate_percent_per_second").value),
        )
        self._publish_state(
            percent=self.percent,
            source="simulated",
            available=True,
            charging=charging,
        )


def main():
    rclpy.init()
    battery_monitor = BatteryMonitor()
    try:
        rclpy.spin(battery_monitor)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if battery_monitor.serial_port:
            battery_monitor.serial_port.close()
        battery_monitor.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

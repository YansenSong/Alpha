#!/usr/bin/env python3
"""
cmd_vel_mux.py — manual/autonomous command selection with a stop override

Prioritizes fresh teleoperation commands from /cmd_vel over NeuPAN commands
from /neupan_cmd_vel, and forwards the selected command to the
ackermann_steering_controller as TwistStamped. The /stop override has highest
priority.

Both /stop=true and /stop=false control the persistent software stop latch.
The authenticated Web HMI publishes that Bool topic directly and receives
robot state on /safety/software_stop/state. The mission manager's separate
/mission/hold remains an independent motion hold.

"""
import copy
import json
import math
import os
from pathlib import Path
import signal
import time
from datetime import datetime, timezone
import uuid

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TwistStamped
from std_msgs.msg import Bool, String


class CmdVelMux(Node):
    def __init__(self):
        super().__init__('cmd_vel_mux')

        self.pub = self.create_publisher(
            TwistStamped, '/ackermann_steering_controller/reference', 10
        )

        self.neupan_sub = self.create_subscription(
            Twist, '/neupan_cmd_vel', self.neupan_callback, 10
        )
        self.manual_sub = self.create_subscription(
            Twist, '/cmd_vel', self.manual_callback, 10
        )
        self.stop_sub = self.create_subscription(
            Bool, '/stop', self.stop_callback, 10
        )
        self.software_stop_request_sub = self.create_subscription(
            String, '/safety/software_stop/request',
            self.software_stop_request_callback, 10
        )
        self.software_stop_state_pub = self.create_publisher(
            String, '/safety/software_stop/state', 10
        )
        self.mission_hold_sub = self.create_subscription(
            Bool, '/mission/hold', self.mission_hold_callback, 10
        )
        self.area_control_sub = self.create_subscription(
            String, '/area_rules/control', self.area_control_callback, 10
        )
        self.rules_hold_sub = self.create_subscription(
            Bool, '/navigation/rules_hold', self.rules_hold_callback, 10
        )

        self.neupan_msg: Twist | None = None
        self.neupan_received_at: float | None = None
        self.manual_msg: Twist | None = None
        self.manual_received_at: float | None = None
        self.declare_parameter('manual_cmd_timeout', 0.5)
        self.manual_cmd_timeout = float(
            self.get_parameter('manual_cmd_timeout').value
        )
        self.declare_parameter('neupan_cmd_timeout', 0.5)
        self.neupan_cmd_timeout = float(
            self.get_parameter('neupan_cmd_timeout').value
        )
        self.declare_parameter(
            'software_stop_state_file',
            os.environ.get(
                'SOFTWARE_STOP_STATE_FILE',
                str(Path.home() / '.ros' / 'software_stop.json'),
            ),
        )
        self.software_stop_state_file = Path(
            self.get_parameter('software_stop_state_file').value
        ).expanduser()
        self.software_stop_state = self.load_software_stop_state()
        self.stop_requested = bool(self.software_stop_state['active'])
        self.last_stop_state_publish = 0.0
        self.mission_hold_requested = False
        self.declare_parameter('area_rules_required', False)
        self.declare_parameter('area_control_timeout', 0.5)
        self.area_rules_required = bool(self.get_parameter('area_rules_required').value)
        self.area_control_timeout = float(self.get_parameter('area_control_timeout').value)
        self.area_control = None
        self.area_control_received_at = None
        self.declare_parameter('rules_hold_required', False)
        self.declare_parameter('rules_hold_timeout', 0.5)
        self.rules_hold_required = bool(self.get_parameter('rules_hold_required').value)
        self.rules_hold_timeout = float(self.get_parameter('rules_hold_timeout').value)
        self.rules_hold = True
        self.rules_hold_received_at = None
        self.declare_parameter('max_acceleration_mps2', 0.5)
        self.max_acceleration = max(0.01, float(self.get_parameter('max_acceleration_mps2').value))
        self.last_output_speed = 0.0
        self.last_output_at = time.monotonic()

        self.timer = self.create_timer(0.05, self.timer_callback)

        self.get_logger().info(
            'cmd_vel_mux started: manual(/cmd_vel) overrides '
            'NeuPAN(/neupan_cmd_vel); /stop and /mission/hold override both → '
            '/ackermann_steering_controller/reference'
        )
        if self.stop_requested:
            self.get_logger().warn(
                'Restored active software stop from persistent state; '
                'publish /stop=false to release it'
            )

    def neupan_callback(self, msg: Twist):
        self.neupan_msg = msg
        self.neupan_received_at = time.monotonic()

    def manual_callback(self, msg: Twist):
        self.manual_msg = msg
        self.manual_received_at = time.monotonic()

    def stop_callback(self, msg: Bool):
        requested = bool(msg.data)
        self.set_software_stop(
            active=requested,
            source='ros_stop_topic',
            reason=(
                'Software stop asserted via /stop=true'
                if requested
                else 'Software stop released via /stop=false'
            ),
            request_id=str(uuid.uuid4()),
        )

    def load_software_stop_state(self):
        try:
            state = json.loads(self.software_stop_state_file.read_text(encoding='utf-8'))
            if not isinstance(state, dict) or not isinstance(state.get('active'), bool):
                raise ValueError('invalid state shape')
            return {
                'active': state['active'],
                'source': str(state.get('source') or 'persistent_state'),
                'reason': str(state.get('reason') or ''),
                'request_id': str(state.get('request_id') or ''),
                'observed_at': str(state.get('observed_at') or ''),
                'result': 'confirmed' if state.get('durable', True) else 'degraded',
                'durable': state.get('durable', True) is True,
            }
        except FileNotFoundError:
            return {
                'active': False,
                'source': 'startup',
                'reason': 'No persisted software stop is active',
                'request_id': '',
                'observed_at': self.utc_now(),
                'result': 'confirmed',
                'durable': True,
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            # A damaged/unreadable latch must fail closed. Do not silently
            # resume motion because persistent safety state could not be read.
            return {
                'active': True,
                'source': 'startup_safety_fallback',
                'reason': f'Persisted stop state unavailable: {exc}',
                'request_id': 'startup-state-unreadable',
                'observed_at': self.utc_now(),
                'result': 'degraded',
                'durable': False,
            }

    @staticmethod
    def utc_now():
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    def persist_software_stop_state(self):
        path = self.software_stop_state_file
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(self.software_stop_state, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def set_software_stop(self, *, active, source, reason, request_id, result='confirmed'):
        next_state = {
            'active': active,
            'source': source,
            'reason': reason,
            'request_id': request_id,
            'observed_at': self.utc_now(),
            'result': result,
            'durable': True,
        }
        previous_state = self.software_stop_state
        if active:
            # Assert in memory before disk IO so a storage failure never
            # delays the immediate zero-velocity override.
            self.stop_requested = True
            self.software_stop_state = next_state
        try:
            self.software_stop_state = next_state
            self.persist_software_stop_state()
        except OSError as exc:
            if not active:
                # A release only takes effect after the cleared state has
                # reached durable storage. Keep the previous stop asserted.
                self.software_stop_state = previous_state
                self.software_stop_state.update({
                    'request_id': request_id,
                    'observed_at': self.utc_now(),
                    'result': 'rejected',
                    'reason': f'Stop remains active; release persistence failed: {exc}',
                })
                self.publish_software_stop_state(force=True)
                self.get_logger().error(f'Software stop release was not persisted: {exc}')
                return
            self.software_stop_state.update({
                'durable': False,
                'result': 'degraded',
                'reason': f'{reason}; stop state persistence failed: {exc}',
            })
            self.get_logger().error(
                f'Software stop state could not be persisted: {exc}'
            )
        else:
            self.software_stop_state = next_state
            self.stop_requested = active
        self.publish_software_stop_state(force=True)
        self.get_logger().warn(
            f'Software stop {"ACTIVE" if active else "RELEASED"}: {reason}'
        )

    def software_stop_request_callback(self, msg: String):
        try:
            request = json.loads(msg.data)
            action = request.get('action')
            request_id = request.get('request_id')
            if action not in {'get_state', 'request_stop', 'request_release'}:
                raise ValueError('Unsupported software stop action')
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise ValueError('request_id must be a non-empty string up to 128 characters')
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            self.get_logger().warn(f'Invalid software stop request: {exc}')
            return

        if action == 'get_state':
            self.software_stop_state['request_id'] = request_id
            self.software_stop_state['result'] = 'confirmed'
            self.software_stop_state['observed_at'] = self.utc_now()
            self.publish_software_stop_state(force=True)
            return

        source = str(request.get('source') or 'web')[:100]
        reason = str(request.get('reason') or '')[:500]
        if action == 'request_stop':
            self.set_software_stop(
                active=True,
                source=source,
                reason=reason or 'Operator requested software stop',
                request_id=request_id,
            )
            return

        self.set_software_stop(
            active=False,
            source=source,
            reason=reason or 'Software stop released by request',
            request_id=request_id,
        )

    def publish_software_stop_state(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_stop_state_publish < 1.0:
            return
        self.last_stop_state_publish = now
        state = dict(self.software_stop_state)
        state['active'] = self.stop_requested
        state['observed_at'] = self.utc_now()
        state['physical_estop'] = {'available': False, 'active': None}
        self.software_stop_state_pub.publish(String(data=json.dumps(state, sort_keys=True)))

    def mission_hold_callback(self, msg: Bool):
        self.mission_hold_requested = bool(msg.data)

    def rules_hold_callback(self, msg: Bool):
        self.rules_hold = bool(msg.data)
        self.rules_hold_received_at = time.monotonic()

    def rules_hold_active(self):
        if self.rules_hold_received_at is None:
            return self.rules_hold_required
        if time.monotonic() - self.rules_hold_received_at > self.rules_hold_timeout:
            return True
        return self.rules_hold

    def area_control_callback(self, msg: String):
        try:
            control = json.loads(msg.data)
            if not isinstance(control.get('ready'), bool) or not isinstance(control.get('stop'), bool):
                return
            limit = control.get('speed_limit')
            if limit is not None and (not isinstance(limit, (int, float))
                                      or isinstance(limit, bool) or not math.isfinite(limit)
                                      or limit <= 0):
                return
        except (ValueError, TypeError, AttributeError):
            return
        self.area_control = control
        self.area_control_received_at = time.monotonic()

    def timer_callback(self):
        self.publish_software_stop_state()
        area_fresh = (self.area_control is not None
                      and self.area_control_received_at is not None
                      and time.monotonic() - self.area_control_received_at <= self.area_control_timeout)
        area_blocked = ((self.area_rules_required or self.area_control_received_at is not None)
                        and (not area_fresh or not self.area_control['ready']
                             or self.area_control['stop']))
        if (self.stop_requested or self.mission_hold_requested or
                self.rules_hold_active() or area_blocked):
            # Publish at the mux timer rate so the controller receives a
            # continuous zero command and cannot resume from a stale command.
            twist = Twist()
            source = 'stop'
        else:
            manual_is_fresh = (
                self.manual_msg is not None
                and self.manual_received_at is not None
                and time.monotonic() - self.manual_received_at
                <= self.manual_cmd_timeout
            )
            if manual_is_fresh:
                twist = self.manual_msg
                source = 'manual'
            elif (
                self.neupan_msg is not None
                and self.neupan_received_at is not None
                and time.monotonic() - self.neupan_received_at <= self.neupan_cmd_timeout
            ):
                twist = self.neupan_msg
                source = 'neupan'
            else:
                return

            if area_fresh and self.area_control['speed_limit'] is not None:
                limit = self.area_control['speed_limit']
                if abs(twist.linear.x) > limit:
                    twist = copy.deepcopy(twist)
                    ratio = limit / abs(twist.linear.x)
                    twist.linear.x *= ratio
                    twist.angular.z *= ratio

        ts = TwistStamped()
        now = time.monotonic()
        requested = twist.linear.x
        if source != 'stop' and abs(requested) > abs(self.last_output_speed):
            allowed = abs(self.last_output_speed) + self.max_acceleration * max(
                0.0, min(now - self.last_output_at, 0.2))
            if abs(requested) > allowed:
                twist = copy.deepcopy(twist)
                ratio = allowed / abs(requested)
                twist.linear.x *= ratio
                twist.angular.z *= ratio
        self.last_output_speed = twist.linear.x
        self.last_output_at = now
        ts.header.stamp = self.get_clock().now().to_msg()
        ts.header.frame_id = 'base_link'
        ts.twist = twist
        self.pub.publish(ts)

        self.get_logger().debug(
            f'[{source}] v={twist.linear.x:.2f}, ω={twist.angular.z:.2f}',
            throttle_duration_sec=10.0,
        )


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelMux()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

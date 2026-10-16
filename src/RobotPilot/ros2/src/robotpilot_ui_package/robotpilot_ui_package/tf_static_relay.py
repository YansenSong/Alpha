"""Merge latched static transforms and replay them for rosbridge clients."""

import signal

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from tf2_msgs.msg import TFMessage


class TfStaticRelay(Node):
    def __init__(self):
        super().__init__("tf_static_relay")
        source_qos = QoSProfile(
            depth=100,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
        destination_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.VOLATILE,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._transforms = {}
        self._publisher = self.create_publisher(TFMessage, "/ui/tf_static", destination_qos)
        self._subscription = self.create_subscription(
            TFMessage, "/tf_static", self._on_tf, source_qos
        )
        self._timer = self.create_timer(2.0, self._publish)

    def _on_tf(self, message):
        for transform in message.transforms:
            self._transforms[transform.child_frame_id] = transform
        self._publish()

    def _publish(self):
        if self._transforms:
            self._publisher.publish(TFMessage(transforms=list(self._transforms.values())))


def main():
    rclpy.init()
    node = TfStaticRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()

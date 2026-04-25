import rclpy
import math
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
import tf2_ros


class OdomTFBroadcaster(Node):
    def __init__(self):
        super().__init__('odom_tf_broadcaster')
        self.declare_parameter('odom_topic', '/odom')
        self.declare_parameter('odom_frame_id', 'odom')
        self.declare_parameter('child_frame_id', 'base_footprint')
        self.declare_parameter('use_odom_msg_stamp', False)
        self.declare_parameter('zero_at_startup', True)

        self.odom_topic = self.get_parameter('odom_topic').get_parameter_value().string_value
        self.odom_frame_id = self.get_parameter('odom_frame_id').get_parameter_value().string_value
        self.child_frame_id = self.get_parameter('child_frame_id').get_parameter_value().string_value
        self.use_odom_msg_stamp = self.get_parameter(
            'use_odom_msg_stamp'
        ).get_parameter_value().bool_value
        self.zero_at_startup = self.get_parameter(
            'zero_at_startup'
        ).get_parameter_value().bool_value
        self.initial_x = None
        self.initial_y = None
        self.initial_z = None
        self.initial_yaw = None

        self.subscription = self.create_subscription(
            Odometry,
            self.odom_topic,
            self.odom_callback,
            50)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        self.get_logger().info(
            f"Odom TF Broadcaster relaying {self.odom_frame_id} -> {self.child_frame_id} from {self.odom_topic}"
        )

    @staticmethod
    def yaw_from_quaternion(q):
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny_cosp, cosy_cosp)

    @staticmethod
    def normalize_angle(angle):
        return math.atan2(math.sin(angle), math.cos(angle))

    def odom_callback(self, msg):
        norm = (
            msg.pose.pose.orientation.x ** 2
            + msg.pose.pose.orientation.y ** 2
            + msg.pose.pose.orientation.z ** 2
            + msg.pose.pose.orientation.w ** 2
        )
        if abs(norm - 1.0) >= 0.1:
            self.get_logger().warn(
                'Ignoring odom message with invalid quaternion',
                throttle_duration_sec=2.0,
            )
            return

        current_yaw = self.yaw_from_quaternion(msg.pose.pose.orientation)

        if self.zero_at_startup and self.initial_x is None:
            self.initial_x = msg.pose.pose.position.x
            self.initial_y = msg.pose.pose.position.y
            self.initial_z = msg.pose.pose.position.z
            self.initial_yaw = current_yaw
            self.get_logger().info(
                f"Zeroing odom TF at startup pose x={self.initial_x:.3f}, "
                f"y={self.initial_y:.3f}, yaw={self.initial_yaw:.3f}"
            )

        if self.zero_at_startup:
            dx = msg.pose.pose.position.x - self.initial_x
            dy = msg.pose.pose.position.y - self.initial_y
            cos_yaw = math.cos(-self.initial_yaw)
            sin_yaw = math.sin(-self.initial_yaw)
            rel_x = cos_yaw * dx - sin_yaw * dy
            rel_y = sin_yaw * dx + cos_yaw * dy
            rel_z = msg.pose.pose.position.z - self.initial_z
            rel_yaw = self.normalize_angle(current_yaw - self.initial_yaw)
        else:
            rel_x = msg.pose.pose.position.x
            rel_y = msg.pose.pose.position.y
            rel_z = msg.pose.pose.position.z
            rel_yaw = current_yaw

        t = TransformStamped()
        if self.use_odom_msg_stamp:
            t.header.stamp = msg.header.stamp
        else:
            t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self.odom_frame_id
        t.child_frame_id = self.child_frame_id

        t.transform.translation.x = rel_x
        t.transform.translation.y = rel_y
        t.transform.translation.z = rel_z
        t.transform.rotation.x = 0.0
        t.transform.rotation.y = 0.0
        t.transform.rotation.z = math.sin(rel_yaw / 2.0)
        t.transform.rotation.w = math.cos(rel_yaw / 2.0)

        self.tf_broadcaster.sendTransform(t)


def main(args=None):
    rclpy.init(args=args)
    node = OdomTFBroadcaster()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()

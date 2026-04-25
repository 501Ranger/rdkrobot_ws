import rclpy
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

        self.odom_topic = self.get_parameter('odom_topic').get_parameter_value().string_value
        self.odom_frame_id = self.get_parameter('odom_frame_id').get_parameter_value().string_value
        self.child_frame_id = self.get_parameter('child_frame_id').get_parameter_value().string_value
        self.use_odom_msg_stamp = self.get_parameter(
            'use_odom_msg_stamp'
        ).get_parameter_value().bool_value

        self.subscription = self.create_subscription(
            Odometry,
            self.odom_topic,
            self.odom_callback,
            50)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        self.get_logger().info(
            f"Odom TF Broadcaster relaying {self.odom_frame_id} -> {self.child_frame_id} from {self.odom_topic}"
        )

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

        t = TransformStamped()
        if self.use_odom_msg_stamp:
            t.header.stamp = msg.header.stamp
        else:
            t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self.odom_frame_id
        t.child_frame_id = self.child_frame_id

        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation

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

import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
import tf2_ros

class OdomTFBroadcaster(Node):
    def __init__(self):
        super().__init__('odom_tf_broadcaster')
        self.subscription = self.create_subscription(
            Odometry,
            '/odom',
            self.odom_callback,
            10)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)
        self._last_tf = None
        # 以 50Hz 重发最新 TF，防止 ESP32 串口延迟导致 TF 缓冲出现空洞
        self.create_timer(0.02, self._republish_timer)
        self.get_logger().info("Odom TF Broadcaster node has started.")

    def odom_callback(self, msg):
        t = TransformStamped()
        # 使用上位机系统时钟，解决 ESP32 与 RDK X5 时钟不同步问题
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_footprint'
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z
        t.transform.rotation = msg.pose.pose.orientation
        self._last_tf = t
        self.tf_broadcaster.sendTransform(t)

    def _republish_timer(self):
        # 若已收到过 odom，以当前时间戳重发，保持 TF 缓冲连续
        if self._last_tf is None:
            return
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self._last_tf.header.frame_id
        t.child_frame_id = self._last_tf.child_frame_id
        t.transform = self._last_tf.transform
        self.tf_broadcaster.sendTransform(t)

def main(args=None):
    rclpy.init(args=args)
    node = OdomTFBroadcaster()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()

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
        self.get_logger().info("Odom TF Broadcaster node has started.")

    def odom_callback(self, msg):
        t = TransformStamped()

        # 使用上位机当前时间，解决时间同步问题
        t.header.stamp = self.get_clock().now().to_msg()
        # 设置父坐标系
        t.header.frame_id = 'odom'
        # 设置子坐标系 (Robot footprint)
        t.child_frame_id = 'base_footprint'

        # 从 odom 话题中提取位置 (Translation)
        t.transform.translation.x = msg.pose.pose.position.x
        t.transform.translation.y = msg.pose.pose.position.y
        t.transform.translation.z = msg.pose.pose.position.z

        # 从 odom 话题中提取姿态 (Rotation / Quaternion)
        t.transform.rotation = msg.pose.pose.orientation

        # 发布 TF
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

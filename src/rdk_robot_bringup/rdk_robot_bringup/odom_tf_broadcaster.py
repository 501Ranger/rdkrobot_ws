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
        
        # 初始化里程计数据，确保四元数 W=1.0 是合法的单位旋转
        self.last_odom_msg = Odometry()
        self.last_odom_msg.pose.pose.orientation.w = 1.0
        
        # 提高发布频率到 50Hz，确保时间轴连续，解决 Message Filter 延迟
        self.timer = self.create_timer(0.02, self.publish_tf)
        self.get_logger().info("Odom TF Broadcaster started at 50Hz with valid quaternion.")

    def odom_callback(self, msg):
        # 检查收到的消息是否包含合法的四元数
        if abs(msg.pose.pose.orientation.x**2 + msg.pose.pose.orientation.y**2 + 
               msg.pose.pose.orientation.z**2 + msg.pose.pose.orientation.w**2 - 1.0) < 0.1:
            self.last_odom_msg = msg

    def publish_tf(self):
        t = TransformStamped()
        
        # 使用当前时间戳，确保它是 TF 缓存中最新的
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = 'odom'
        t.child_frame_id = 'base_footprint'

        t.transform.translation.x = self.last_odom_msg.pose.pose.position.x
        t.transform.translation.y = self.last_odom_msg.pose.pose.position.y
        t.transform.translation.z = self.last_odom_msg.pose.pose.position.z
        t.transform.rotation = self.last_odom_msg.pose.pose.orientation

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

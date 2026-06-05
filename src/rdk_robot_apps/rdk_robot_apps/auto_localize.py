import rclpy
from rclpy.node import Node
from std_srvs.srv import Empty, Trigger
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool
from rclpy.qos import QoSProfile, DurabilityPolicy
import time
import threading


class AutoLocalizer(Node):
    def __init__(self):
        super().__init__("auto_localizer")
        self.cli = self.create_client(Empty, "/reinitialize_global_localization")
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        
        # 配置 Transient Local QoS，使新订阅者能收到最后的发布值
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(Bool, "/auto_localize/status", qos)
        self.is_running = False
        self.status_pub.publish(Bool(data=False))

        # 创建 ROS 2 服务服务器，用于被 API 调用
        self.srv = self.create_service(
            Trigger, "/trigger_auto_localize", self.handle_trigger
        )
        self.get_logger().info(
            "Auto Localizer Service Node initialized. Waiting for service calls on /trigger_auto_localize..."
        )

    def handle_trigger(self, request, response):
        if self.is_running:
            response.success = False
            response.message = "Auto-localization sequence is already running."
            return response

        # 启动新线程来执行动作序列，避免阻塞 ROS 2 执行器
        threading.Thread(target=self.run_sequence, daemon=True).start()
        response.success = True
        response.message = "Auto-localization sequence triggered successfully."
        return response

    def run_sequence(self):
        self.is_running = True
        # 发布状态为 True
        self.status_pub.publish(Bool(data=True))
        self.get_logger().info(
            "Waiting for /reinitialize_global_localization service..."
        )
        
        # 等待 AMCL 重定位服务可用
        while not self.cli.wait_for_service(timeout_sec=1.0):
            if not rclpy.ok():
                self.is_running = False
                return

        self.get_logger().info(
            "Service found. Reinitializing global localization (scattering particles)..."
        )
        req = Empty.Request()
        self.cli.call_async(req)

        # 稍微等一小会儿，让 AMCL 把粒子撒开
        time.sleep(2.0)

        self.get_logger().info("Phase 1: Rotating to collect initial features...")
        msg = Twist()
        msg.angular.z = 0.5  # 0.5 rad/s 的旋转速度

        # 阶段一：原地旋转 8 秒
        for _ in range(80):
            if not rclpy.ok() or not self.is_running:
                return
            self.cmd_pub.publish(msg)
            time.sleep(0.1)

        self.get_logger().info("Phase 2: Moving forward to break corridor symmetry...")
        # 阶段二：往前走 4 秒 (0.15 m/s)，探查新的视野，打破走廊对称性
        msg.angular.z = 0.0
        msg.linear.x = 0.15
        for _ in range(40):
            if not rclpy.ok() or not self.is_running:
                return
            self.cmd_pub.publish(msg)
            time.sleep(0.1)

        self.get_logger().info("Phase 3: Rotating again to confirm location...")
        # 阶段三：反向旋转 8 秒，确认最终位置
        msg.linear.x = 0.0
        msg.angular.z = -0.5
        for _ in range(80):
            if not rclpy.ok() or not self.is_running:
                return
            self.cmd_pub.publish(msg)
            time.sleep(0.1)

        # 停止所有运动
        msg.angular.z = 0.0
        msg.linear.x = 0.0
        self.cmd_pub.publish(msg)
        self.get_logger().info(
            "Auto localization sequence completed! Robot should now be localized."
        )
        self.is_running = False
        self.status_pub.publish(Bool(data=False))


def main():
    rclpy.init()
    node = AutoLocalizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()


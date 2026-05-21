import rclpy
from rclpy.node import Node
from std_srvs.srv import Empty
from geometry_msgs.msg import Twist
import time
import threading


class AutoLocalizer(Node):
    def __init__(self):
        super().__init__("auto_localizer")
        self.cli = self.create_client(Empty, "/reinitialize_global_localization")
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        self.thread = threading.Thread(target=self.run_sequence)
        self.thread.start()

    def run_sequence(self):
        self.get_logger().info(
            "Waiting for /reinitialize_global_localization service..."
        )
        while not self.cli.wait_for_service(timeout_sec=1.0):
            if not rclpy.ok():
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
            if not rclpy.ok():
                return
            self.cmd_pub.publish(msg)
            time.sleep(0.1)

        self.get_logger().info("Phase 2: Moving forward to break corridor symmetry...")
        # 阶段二：往前走 4 秒 (0.15 m/s)，探查新的视野，打破走廊对称性
        msg.angular.z = 0.0
        msg.linear.x = 0.15
        for _ in range(40):
            if not rclpy.ok():
                return
            self.cmd_pub.publish(msg)
            time.sleep(0.1)

        self.get_logger().info("Phase 3: Rotating again to confirm location...")
        # 阶段三：反向旋转 8 秒，确认最终位置
        msg.linear.x = 0.0
        msg.angular.z = -0.5
        for _ in range(80):
            if not rclpy.ok():
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

        # 退出节点
        try:
            rclpy.shutdown()
        except Exception:
            pass


def main():
    rclpy.init()
    node = AutoLocalizer()
    try:
        rclpy.spin(node)
    except Exception:
        pass


if __name__ == "__main__":
    main()

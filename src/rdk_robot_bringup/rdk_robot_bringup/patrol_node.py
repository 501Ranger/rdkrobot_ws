import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
import math
import time


class PatrolNode(Node):
    def __init__(self):
        super().__init__("patrol_node")
        # 创建一个 Nav2 的导航动作客户端
        self._action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")

        # === 巡检航点列表 (x, y, yaw) ===
        # 这里是一组示例航点。你可以通过在 RViz 中观察地图上的坐标，
        # 把你想要让小车去的地方按顺序填在下面！
        self.waypoints = [
            (0.0, -19.0, 0.0),  # 点1：从原点出发
            (0.0, 11.5, 1.57),  # 点2
            (-37.0, 12.0, 3.14),  # 点3
            (-39.0, -18.0, -1.57),  # 点4
            (-0.0, -0.0, 0.0),  # 点4：回到原点
        ]
        self.current_waypoint_index = 0

        self.get_logger().info(
            "Patrol Node Initialized. Waiting for Nav2 Action Server..."
        )
        self._action_client.wait_for_server()
        self.get_logger().info(
            "Nav2 Action Server Found! Starting Patrol in 5 seconds..."
        )

        # 给一定时间让机器人的自定位（auto_localize）先跑完
        time.sleep(5.0)
        self.send_next_goal()

    def send_next_goal(self):
        if self.current_waypoint_index >= len(self.waypoints):
            self.get_logger().info("--- One Full Loop Completed! Starting over... ---")
            self.current_waypoint_index = 0  # 实现无限循环巡检

        x, y, yaw = self.waypoints[self.current_waypoint_index]
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = "map"
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()

        goal_msg.pose.pose.position.x = float(x)
        goal_msg.pose.pose.position.y = float(y)

        # Yaw (弧度) 转换为 Quaternion (四元数)
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info(
            f">>> Navigating to Waypoint {self.current_waypoint_index + 1}/{len(self.waypoints)}: X={x}, Y={y}"
        )

        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error("Goal rejected by Nav2 server :(")
            return

        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        self.get_logger().info(
            f"<<< Successfully reached Waypoint {self.current_waypoint_index + 1}!"
        )
        self.current_waypoint_index += 1

        # 到达目标点后，停顿 3 秒钟（模拟拍照、检查等任务）
        self.get_logger().info("Pausing for 3 seconds...")
        time.sleep(3.0)

        # 发送下一个点
        self.send_next_goal()


def main(args=None):
    rclpy.init(args=args)
    node = PatrolNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Patrol Node stopped manually.")
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()

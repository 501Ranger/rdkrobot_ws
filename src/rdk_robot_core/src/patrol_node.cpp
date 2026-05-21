#include <chrono>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>

using namespace std::chrono_literals;

struct Waypoint {
    double x;
    double y;
    double yaw;
};

class PatrolNode : public rclcpp::Node {
public:
    using NavigateToPose = nav2_msgs::action::NavigateToPose;
    using GoalHandleNav = rclcpp_action::ClientGoalHandle<NavigateToPose>;

    PatrolNode() : Node("patrol_node"), current_waypoint_index_(0) {
        // 初始化
        action_client_ = rclcpp_action::create_client<NavigateToPose>(this, "navigate_to_pose");

        // 航点列表
        waypoints_ = {
            {0.0, -19.0, 0.0},
            {0.0, 11.5, 1.57},
            {-37.0, 12.0, 3.14},
            {-39.0, -18.0, -1.57},
            {-0.0, -0.0, 0.0}};

        RCLCPP_INFO(this->get_logger(), "Patrol Node Initialized. Waiting for Nav2 Action Server...");

        // 异步等待 Action 服务器启动
        if (!action_client_->wait_for_action_server(std::chrono::seconds(10))) {
            RCLCPP_ERROR(this->get_logger(), "Action server not available after waiting");
            return;
        }
        RCLCPP_INFO(this->get_logger(), "Nav2 Action Server Found! Starting Patrol in 5 seconds...");

        pause_timer_ = this->create_wall_timer(
            3s,
            [this]() {
                pause_timer_->cancel();  // 触发后立刻停用自身，确保只执行一次
                this->send_next_goal();
            });
        pause_timer_->cancel();
        
        startup_timer_ = create_wall_timer(5s, [this]() {
            startup_timer_->cancel();
            this->send_next_goal();
        });
    }

private:
    void send_next_goal() {
        if (current_waypoint_index_ >= waypoints_.size()) {
            RCLCPP_INFO(this->get_logger(), "--- One Full Loop Completed! Starting over... ---");
            current_waypoint_index_ = 0;
        }

        const auto& wp = waypoints_[current_waypoint_index_];
        auto goal_msg = NavigateToPose::Goal();

        // 设置目标位置
        goal_msg.pose.header.frame_id = "map";
        goal_msg.pose.header.stamp = this->get_clock()->now();

        goal_msg.pose.pose.position.x = wp.x;
        goal_msg.pose.pose.position.y = wp.y;
        goal_msg.pose.pose.orientation.z = std::sin(wp.yaw / 2.0);
        goal_msg.pose.pose.orientation.w = std::cos(wp.yaw / 2.0);

        RCLCPP_INFO(this->get_logger(), ">>> Navigating to Waypoint %zu/%zu: X=%.2f, Y=%.2f",
                    current_waypoint_index_ + 1, waypoints_.size(), wp.x, wp.y);

        typename rclcpp_action::Client<NavigateToPose>::SendGoalOptions send_goal_options;

        send_goal_options.goal_response_callback = [this](const GoalHandleNav::SharedPtr& goal_handle) {
            if (!goal_handle)
                RCLCPP_ERROR(this->get_logger(), "Goal was rejected by server :(");
            else
                RCLCPP_INFO(this->get_logger(), "Goal accepted by server, waiting for result...");
        };
        send_goal_options.result_callback = [this](const GoalHandleNav::WrappedResult& result) {
            this->get_result_callback(result);
        };

        // 异步发送目标
        action_client_->async_send_goal(goal_msg, send_goal_options);
    }

    void get_result_callback(const GoalHandleNav::WrappedResult& result) {
        switch (result.code) {
            case rclcpp_action::ResultCode::SUCCEEDED:
                RCLCPP_INFO(this->get_logger(), "<<< Successfully reached Waypoint %zu!", current_waypoint_index_ + 1);
                break;
            case rclcpp_action::ResultCode::ABORTED:
                RCLCPP_ERROR(this->get_logger(), "Goal was aborted");
                return;
            case rclcpp_action::ResultCode::CANCELED:
                RCLCPP_ERROR(this->get_logger(), "Goal was canceled");
                return;
            default:
                RCLCPP_ERROR(this->get_logger(), "Unknown result code");
                return;
        }

        // 索引递增
        current_waypoint_index_++;

        // 创建一个 3 秒的单次定时器,模拟拍照、检查等任务。
        RCLCPP_INFO(this->get_logger(), "Pausing for 3 seconds...");
        pause_timer_->reset();
    }
    rclcpp_action::Client<NavigateToPose>::SharedPtr action_client_;
    std::vector<Waypoint> waypoints_;
    size_t current_waypoint_index_;
    rclcpp::TimerBase::SharedPtr startup_timer_;
    rclcpp::TimerBase::SharedPtr pause_timer_;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    auto node = std::make_shared<PatrolNode>();
    try {
        rclcpp::spin(node);
    } catch (const std::exception& e) {
        RCLCPP_INFO(node->get_logger(), "Patrol Node stopped.");
    }
    rclcpp::shutdown();
    return 0;
}
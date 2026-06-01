#include <chrono>
#include <cmath>
#include <vector>
#include <string>
#include <nav2_msgs/action/navigate_to_pose.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <std_msgs/msg/string.hpp>
#include <geometry_msgs/msg/pose_array.hpp>

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

    PatrolNode() : Node("patrol_node"), current_waypoint_index_(0), is_active_(false), loop_mode_(true) {
        // 先初始化定时器，保证任何时候都安全，避免由于 wait_for_action_server 超时返回导致的空指针问题
        pause_timer_ = this->create_wall_timer(
            3s,
            [this]() {
                if (this->pause_timer_) {
                    this->pause_timer_->cancel();
                }
                if (this->is_active_) {
                    this->send_next_goal();
                }
            });
        if (pause_timer_) {
            pause_timer_->cancel();
        }

        // 初始化 Action Client
        action_client_ = rclcpp_action::create_client<NavigateToPose>(this, "navigate_to_pose");

        // 默认航点列表（备用）
        waypoints_ = {
            {0.0, -19.0, 0.0},
            {0.0, 11.5, 1.57},
            {-37.0, 12.0, 3.14},
            {-39.0, -18.0, -1.57},
            {-0.0, -0.0, 0.0}};

        // 创建命令订阅者
        cmd_sub_ = this->create_subscription<std_msgs::msg::String>(
            "/patrol/cmd", 10, std::bind(&PatrolNode::cmd_callback, this, std::placeholders::_1));

        // 创建动态航点订阅者
        waypoints_sub_ = this->create_subscription<geometry_msgs::msg::PoseArray>(
            "/patrol/set_waypoints", 10, std::bind(&PatrolNode::waypoints_callback, this, std::placeholders::_1));

        // 创建巡逻反馈发布者
        feedback_pub_ = this->create_publisher<std_msgs::msg::String>("/patrol/feedback", 10);

        RCLCPP_INFO(this->get_logger(), "Patrol Node Initialized. Waiting for command on /patrol/cmd...");

        // 异步等待 Action 服务器启动
        if (!action_client_->wait_for_action_server(std::chrono::seconds(10))) {
            RCLCPP_ERROR(this->get_logger(), "Action server 'navigate_to_pose' not available after waiting");
            return;
        }
        RCLCPP_INFO(this->get_logger(), "Nav2 Action Server Found! Ready to patrol.");
    }

private:
    void cmd_callback(const std_msgs::msg::String::SharedPtr msg) {
        std::string cmd = msg->data;
        RCLCPP_INFO(this->get_logger(), "Received patrol command: '%s'", cmd.c_str());

        if (cmd == "start" || cmd == "start_once" || cmd == "resume") {
            if (is_active_) {
                RCLCPP_WARN(this->get_logger(), "Patrol is already running.");
                return;
            }
            if (waypoints_.empty()) {
                RCLCPP_ERROR(this->get_logger(), "Cannot start patrol: waypoint list is empty.");
                return;
            }
            if (cmd == "start") {
                loop_mode_ = true;
            } else if (cmd == "start_once") {
                loop_mode_ = false;
            }
            is_active_ = true;
            RCLCPP_INFO(this->get_logger(), "Starting/Resuming patrol (loop=%s)...", loop_mode_ ? "true" : "false");
            this->send_next_goal();
        } 
        else if (cmd == "pause") {
            if (!is_active_) {
                RCLCPP_WARN(this->get_logger(), "Patrol is already paused or idle.");
                return;
            }
            is_active_ = false;
            if (pause_timer_) {
                pause_timer_->cancel();
            }
            if (current_goal_handle_) {
                RCLCPP_INFO(this->get_logger(), "Canceling current navigation goal...");
                action_client_->async_cancel_goal(current_goal_handle_);
            }
            RCLCPP_INFO(this->get_logger(), "Patrol paused.");
        } 
        else if (cmd == "stop") {
            is_active_ = false;
            if (pause_timer_) {
                pause_timer_->cancel();
            }
            if (current_goal_handle_) {
                RCLCPP_INFO(this->get_logger(), "Canceling current navigation goal...");
                action_client_->async_cancel_goal(current_goal_handle_);
            }
            current_waypoint_index_ = 0;
            RCLCPP_INFO(this->get_logger(), "Patrol stopped. Waypoint index reset to 0.");
        }
        else {
            RCLCPP_WARN(this->get_logger(), "Unknown command: '%s'", cmd.c_str());
        }
    }

    void waypoints_callback(const geometry_msgs::msg::PoseArray::SharedPtr msg) {
        RCLCPP_INFO(this->get_logger(), "Received %zu new waypoints dynamically.", msg->poses.size());

        // 如果当前有任务运行，先取消它
        if (current_goal_handle_) {
            action_client_->async_cancel_goal(current_goal_handle_);
        }
        if (pause_timer_) {
            pause_timer_->cancel();
        }

        waypoints_.clear();
        for (const auto& pose : msg->poses) {
            Waypoint wp;
            wp.x = pose.position.x;
            wp.y = pose.position.y;
            
            // 四元数转 yaw
            double siny_cosp = 2.0 * (pose.orientation.w * pose.orientation.z + pose.orientation.x * pose.orientation.y);
            double cosy_cosp = 1.0 - 2.0 * (pose.orientation.y * pose.orientation.y + pose.orientation.z * pose.orientation.z);
            wp.yaw = std::atan2(siny_cosp, cosy_cosp);
            
            waypoints_.push_back(wp);
        }

        current_waypoint_index_ = 0;
        RCLCPP_INFO(this->get_logger(), "Successfully updated patrol waypoints.");

        // 如果当前处于激活状态且新航点不为空，直接开始执行第一个航点
        if (is_active_ && !waypoints_.empty()) {
            this->send_next_goal();
        }
    }

    void send_next_goal() {
        if (!is_active_) return;

        if (waypoints_.empty()) {
            RCLCPP_WARN(this->get_logger(), "Waypoint list is empty. Stopping patrol.");
            is_active_ = false;
            return;
        }

        if (current_waypoint_index_ >= waypoints_.size()) {
            if (loop_mode_) {
                RCLCPP_INFO(this->get_logger(), "--- One Full Loop Completed! Starting over... ---");
                current_waypoint_index_ = 0;
            } else {
                RCLCPP_INFO(this->get_logger(), "--- One-time Patrol Completed! Stopping patrol. ---");
                {
                    std_msgs::msg::String fb_msg;
                    fb_msg.data = "completed";
                    feedback_pub_->publish(fb_msg);
                }
                is_active_ = false;
                current_waypoint_index_ = 0;
                return;
            }
        }

        const auto& wp = waypoints_[current_waypoint_index_];
        auto goal_msg = NavigateToPose::Goal();

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
            if (!goal_handle) {
                RCLCPP_ERROR(this->get_logger(), "Goal was rejected by server :(");
            } else {
                RCLCPP_INFO(this->get_logger(), "Goal accepted by server, waiting for result...");
                this->current_goal_handle_ = goal_handle;
            }
        };
        send_goal_options.result_callback = [this](const GoalHandleNav::WrappedResult& result) {
            this->current_goal_handle_ = nullptr;
            this->get_result_callback(result);
        };

        action_client_->async_send_goal(goal_msg, send_goal_options);
    }

    void get_result_callback(const GoalHandleNav::WrappedResult& result) {
        switch (result.code) {
            case rclcpp_action::ResultCode::SUCCEEDED:
                RCLCPP_INFO(this->get_logger(), "<<< Successfully reached Waypoint %zu!", current_waypoint_index_ + 1);
                {
                    std_msgs::msg::String fb_msg;
                    fb_msg.data = "reached_" + std::to_string(current_waypoint_index_ + 1);
                    feedback_pub_->publish(fb_msg);
                }
                break;
            case rclcpp_action::ResultCode::ABORTED:
                RCLCPP_ERROR(this->get_logger(), "Goal was aborted.");
                return;
            case rclcpp_action::ResultCode::CANCELED:
                RCLCPP_INFO(this->get_logger(), "Goal was canceled.");
                return;
            default:
                RCLCPP_ERROR(this->get_logger(), "Unknown result code.");
                return;
        }

        // 索引递增
        current_waypoint_index_++;

        // 只有在巡逻仍然激活的情况下，才重置定时器去往下一个航点
        if (is_active_) {
            RCLCPP_INFO(this->get_logger(), "Pausing for 3 seconds before next waypoint...");
            if (pause_timer_) {
                pause_timer_->reset();
            }
        }
    }

    // ROS 2 通信对象
    rclcpp_action::Client<NavigateToPose>::SharedPtr action_client_;
    GoalHandleNav::SharedPtr current_goal_handle_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr cmd_sub_;
    rclcpp::Subscription<geometry_msgs::msg::PoseArray>::SharedPtr waypoints_sub_;
    rclcpp::TimerBase::SharedPtr pause_timer_;
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr feedback_pub_;

    // 内部状态
    std::vector<Waypoint> waypoints_;
    size_t current_waypoint_index_;
    bool is_active_;
    bool loop_mode_;
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
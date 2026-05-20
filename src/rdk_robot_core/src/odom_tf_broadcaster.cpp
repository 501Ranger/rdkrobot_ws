#include <chrono>
#include <memory>
#include <mutex>
#include <string>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2_ros/transform_broadcaster.h"

using namespace std::chrono_literals;

/**
 * @brief OdomTFBroadcaster 节点
 * 订阅 /odom 话题并广播 TF 变换 (odom -> base_footprint)
 * 包含定时重发功能，解决底层硬件(如ESP32)时钟不同步导致的 TF 丢失问题
 */
class OdomTFBroadcaster : public rclcpp::Node {
public:
    OdomTFBroadcaster() : Node("odom_tf_broadcaster") {
        // 初始化 TF 广播器
        tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);

        // 订阅里程计话题
        odom_sub_ = this->create_subscription<nav_msgs::msg::Odometry>(
            "/odom", 10,
            std::bind(&OdomTFBroadcaster::odom_callback, this, std::placeholders::_1));

        // 创建定时器：20Hz (50ms) 重发最新的 TF，确保 TF 缓冲区连续
        timer_ = this->create_wall_timer(
            50ms, std::bind(&OdomTFBroadcaster::republish_timer_callback, this));

        RCLCPP_INFO(this->get_logger(), "Odom TF Broadcaster (C++) started.");
    }

private:
    void odom_callback(const nav_msgs::msg::Odometry::SharedPtr msg) {
        std::lock_guard<std::mutex> lock(mutex_);
        
        auto t = geometry_msgs::msg::TransformStamped();
        t.header.stamp = this->get_clock()->now();
        t.header.frame_id = "odom";
        t.child_frame_id = "base_footprint";

        t.transform.translation.x = msg->pose.pose.position.x;
        t.transform.translation.y = msg->pose.pose.position.y;
        t.transform.translation.z = msg->pose.pose.position.z;
        t.transform.rotation = msg->pose.pose.orientation;

        last_tf_ = t;
        tf_broadcaster_->sendTransform(t);
    }

    void republish_timer_callback() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (last_tf_.header.frame_id.empty()) {
            return;
        }

        // 更新时间戳并重发，解决某些情况下 TF 缓冲出现的空洞
        last_tf_.header.stamp = this->get_clock()->now();
        tf_broadcaster_->sendTransform(last_tf_);
    }

    // ROS 2 相关成员
    rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_sub_;
    std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
    rclcpp::TimerBase::SharedPtr timer_;

    // 数据缓存与线程安全
    geometry_msgs::msg::TransformStamped last_tf_;
    std::mutex mutex_;
};

int main(int argc, char* argv[]) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<OdomTFBroadcaster>());
    rclcpp::shutdown();
    return 0;
}
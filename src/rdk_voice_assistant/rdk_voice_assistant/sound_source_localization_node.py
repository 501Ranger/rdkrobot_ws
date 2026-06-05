import json
import random
import time
import threading
import re
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String


class SoundSourceLocalizationNode(Node):
    """ROS 2 Node that calculates or simulates Sound Source Localization (DOA)."""

    def __init__(self) -> None:
        super().__init__('sound_source_localization_node')

        # Declare parameters
        self.declare_parameter('simulation_mode', True)
        self.declare_parameter('default_confidence', 0.9)
        self.declare_parameter('periodic_simulation', False)
        self.declare_parameter('periodic_interval_sec', 15.0)
        self.declare_parameter('serial_port', '/dev/ttyUSB0')
        self.declare_parameter('baud_rate', 115200)

        self.simulation_mode = self.get_parameter('simulation_mode').value
        self.default_confidence = self.get_parameter('default_confidence').value
        self.periodic_simulation = self.get_parameter('periodic_simulation').value
        self.periodic_interval_sec = self.get_parameter('periodic_interval_sec').value
        self.serial_port = self.get_parameter('serial_port').value
        self.baud_rate = self.get_parameter('baud_rate').value

        # Publishers
        self.angle_pub = self.create_publisher(Float32, '/voice/source_angle', 10)
        self.confidence_pub = self.create_publisher(Float32, '/voice/source_confidence', 10)
        self.event_pub = self.create_publisher(String, '/voice/source_event', 10)

        # Subscribers for simulation triggers
        self.trigger_sub = self.create_subscription(
            String,
            '/voice/trigger_localization',
            self._on_trigger_localization,
            10
        )

        self.get_logger().info(
            f'Sound Source Localization Node initialized. Mode: {"Simulation" if self.simulation_mode else "Hardware"}'
        )

        if self.simulation_mode:
            # Periodic timer for simulated events if configured
            if self.periodic_simulation:
                self.timer = self.create_timer(self.periodic_interval_sec, self._simulate_random_event)
                self.get_logger().info(f'Periodic simulation timer started ({self.periodic_interval_sec}s)')
        else:
            # Hardware mode: start serial reading thread
            self.running = True
            self.thread = threading.Thread(target=self._serial_read_loop, daemon=True)
            self.thread.start()
            self.get_logger().info(f'Started serial reading thread on {self.serial_port} @ {self.baud_rate}')

    def _serial_read_loop(self) -> None:
        import serial
        
        # Match pattern for wake-up angle, e.g., "WAKE UP! angle:120" or "WAKE UP! angle：120"
        pattern = re.compile(r'WAKE\s+UP!\s+angle[：:]\s*(\d+)', re.IGNORECASE)
        
        while rclpy.ok() and self.running:
            try:
                self.get_logger().info(f"Connecting to serial port {self.serial_port}...")
                with serial.Serial(self.serial_port, self.baud_rate, timeout=1.0) as ser:
                    self.get_logger().info(f"Successfully connected to {self.serial_port}")
                    while rclpy.ok() and self.running:
                        line_bytes = ser.readline()
                        if not line_bytes:
                            continue
                        try:
                            line = line_bytes.decode('utf-8', errors='ignore').strip()
                        except Exception:
                            continue
                            
                        if line:
                            self.get_logger().debug(f"Serial received: {line}")
                            match = pattern.search(line)
                            if match:
                                try:
                                    angle = float(match.group(1))
                                    self.get_logger().info(f"Detected hardware wake angle: {angle}°")
                                    self.publish_localization(angle, self.default_confidence)
                                except ValueError:
                                    pass
            except serial.SerialException as e:
                self.get_logger().error(f"Serial port error on {self.serial_port}: {e}")
                # Wait before retrying
                time.sleep(2.0)

    def publish_localization(self, angle_deg: float, confidence: float) -> None:
        """Publish the Sound Source Localization metrics across ROS 2 topics."""
        # Normalize angle to [0.0, 360.0)
        angle_deg = float(angle_deg) % 360.0

        # Publish raw angle
        angle_msg = Float32()
        angle_msg.data = angle_deg
        self.angle_pub.publish(angle_msg)

        # Publish raw confidence
        conf_msg = Float32()
        conf_msg.data = float(confidence)
        self.confidence_pub.publish(conf_msg)

        # Publish structured JSON event string
        event_data = {
            'angle_deg': angle_deg,
            'confidence': confidence,
            'timestamp': time.time()
        }
        event_msg = String()
        event_msg.data = json.dumps(event_data)
        self.event_pub.publish(event_msg)

        self.get_logger().info(
            f'Published Sound Source Location: angle={angle_deg:.1f}°, confidence={confidence:.2f}'
        )

    def _simulate_random_event(self) -> None:
        """Helper to generate and publish a random DOA direction."""
        angle = float(random.randint(0, 359))
        confidence = round(random.uniform(0.7, 1.0), 2)
        self.publish_localization(angle, confidence)

    def _on_trigger_localization(self, msg: String) -> None:
        """Handle incoming command/JSON/text on the trigger topic to simulate audio DOA events."""
        if not self.simulation_mode:
            self.get_logger().warn('Received trigger command, but simulation_mode is False.')
            return

        payload = msg.data.strip()
        self.get_logger().info(f'Received Sound Localization simulation trigger: "{payload}"')

        # Try parsing as JSON first
        try:
            data = json.loads(payload)
            if isinstance(data, dict):
                angle = float(data.get('angle_deg', data.get('angle', random.randint(0, 359))))
                confidence = float(data.get('confidence', self.default_confidence))
                self.publish_localization(angle, confidence)
                return
        except Exception:
            pass

        # Try parsing as plain float angle
        try:
            angle = float(payload)
            self.publish_localization(angle, self.default_confidence)
            return
        except ValueError:
            pass

        # Fallback to random if payload is "random", "true", or unrecognized
        self._simulate_random_event()

    def destroy_node(self) -> None:
        self.running = False
        super().destroy_node()


def main(args: Optional[list] = None) -> None:
    rclpy.init(args=args)
    node = SoundSourceLocalizationNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

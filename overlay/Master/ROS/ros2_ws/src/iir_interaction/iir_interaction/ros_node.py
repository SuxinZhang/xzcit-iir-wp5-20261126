"""Bridge ROS topics to the local interaction service.
将 ROS 话题接入本机交互服务。
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import urllib.error
import urllib.request

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String


class InteractionNode(Node):
    def __init__(self):
        super().__init__('iir_interaction')
        self.token = os.environ['IIR_INTERACTION_TOKEN']
        self.battery = None
        self.sos_worker = ThreadPoolExecutor(max_workers=1)
        self.speech_worker = ThreadPoolExecutor(max_workers=1)
        self.sos_speech_worker = ThreadPoolExecutor(max_workers=1)
        self.publisher = self.create_publisher(String, '/interaction/command', 10)
        self.create_subscription(Bool, '/chassis/sos_active', self.on_sos, 10)
        self.create_subscription(String, '/interaction/patrol_event', self.on_event, 10)
        self.create_subscription(Float32, '/battery_voltage', self.on_battery, 10)
        self.create_timer(0.5, self.poll_command)

    def request(self, path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request('http://127.0.0.1:8095' + path, data=payload, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def on_sos(self, message):
        self.sos_worker.submit(self.process_sos, message.data)

    def process_sos(self, active):
        try:
            self.request('/sos', {'active': active})
            if active:
                self.sos_speech_worker.submit(self.speak_sos)
        except (urllib.error.URLError, OSError) as exc:
            self.get_logger().error(f'SOS interaction failed: {exc}')

    def speak_sos(self):
        try:
            self.request('/speak', {'event': 'sos', 'source': 'sos'})
        except (urllib.error.URLError, OSError) as exc:
            self.get_logger().error(f'SOS speech failed: {exc}')

    def on_event(self, message):
        self.speech_worker.submit(self.process_event, message.data)

    def process_event(self, event):
        try:
            self.request('/speak', {'event': event, 'source': 'patrol_tts'})
        except (urllib.error.URLError, OSError) as exc:
            self.get_logger().error(f'patrol announcement failed: {exc}')

    def on_battery(self, message):
        self.battery = message.data

    def poll_command(self):
        try:
            command = self.request('/commands/next')['command']
            if command:
                msg = String()
                msg.data = command
                self.publisher.publish(msg)
                if command == 'report_battery':
                    if self.battery is None:
                        self.get_logger().error('battery voltage has not been received')
                    else:
                        self.speech_worker.submit(self.report_battery, self.battery)
        except (urllib.error.URLError, OSError) as exc:
            self.get_logger().error(f'interaction request failed: {exc}')

    def report_battery(self, voltage):
        try:
            self.request('/speak', {'text': f'电池电压 {voltage:.1f} 伏。', 'source': 'local_dialogue'})
        except (urllib.error.URLError, OSError) as exc:
            self.get_logger().error(f'battery announcement failed: {exc}')

    def destroy_node(self):
        self.sos_worker.shutdown(wait=True)
        self.speech_worker.shutdown(wait=True)
        self.sos_speech_worker.shutdown(wait=True)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = InteractionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

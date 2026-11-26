"""Verify that speech cannot block the SOS callback.
验证语音播报不会阻塞 SOS 回调。
"""
import importlib
import sys
import threading
import types
import unittest
from unittest.mock import patch


class RosWorkerTests(unittest.TestCase):
    def test_sos_runs_while_patrol_speech_is_blocked(self):
        rclpy = types.ModuleType('rclpy')
        node = types.ModuleType('rclpy.node')
        node.Node = object
        std_msgs = types.ModuleType('std_msgs')
        msgs = types.ModuleType('std_msgs.msg')
        msgs.Bool = msgs.Float32 = msgs.String = object
        with patch.dict(sys.modules, {'rclpy': rclpy, 'rclpy.node': node, 'std_msgs': std_msgs, 'std_msgs.msg': msgs}):
            module = importlib.import_module('iir_interaction.ros_node')
            from concurrent.futures import ThreadPoolExecutor
            instance = object.__new__(module.InteractionNode)
            instance.sos_worker = ThreadPoolExecutor(max_workers=1)
            instance.speech_worker = ThreadPoolExecutor(max_workers=1)
            speech_started, release, sos_started = threading.Event(), threading.Event(), threading.Event()
            def request(path, body):
                if path == '/speak' and body['source'] == 'patrol_tts':
                    speech_started.set()
                    release.wait(3)
                if path == '/sos':
                    sos_started.set()
            instance.request = request
            try:
                instance.on_event(types.SimpleNamespace(data='departure'))
                self.assertTrue(speech_started.wait(1))
                instance.on_sos(types.SimpleNamespace(data=False))
                self.assertTrue(sos_started.wait(1))
            finally:
                release.set()
                instance.speech_worker.shutdown()
                instance.sos_worker.shutdown()

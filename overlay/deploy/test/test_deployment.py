import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

DEPLOY = Path(__file__).resolve().parents[1]


class DeploymentTest(unittest.TestCase):
    def test_mediamtx_audio_only_has_no_camera_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'media.json'
            env = os.environ | {'IIR_MEDIA_AUTH_SECRET': 'test-token',
                                'IIR_CAMERA_UPSTREAM': '',
                                'IIR_MEDIAMTX_CONFIG': str(target)}
            subprocess.run(['python3', str(DEPLOY / 'mediamtx/render.py')], env=env, check=True)
            self.assertEqual(set(json.loads(target.read_text())['paths']),
                             {'robot_mic', 'platform_voice'})

    def test_aec_load_failure_leaves_no_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\nimport sys\n'
                            'args=sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]: print("1 mic")\n'
                            'elif args == ["list", "short", "sinks"]: print("2 speaker")\n'
                            'elif args[0] == "load-module": sys.exit(1)\n'
                            'else: sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = os.environ | {'PATH': directory + ':' + os.environ['PATH'],
                                'IIR_AEC_SOURCE_MASTER': 'mic',
                                'IIR_AEC_SINK_MASTER': 'speaker',
                                'PULSE_SERVER': 'unix:/run/user/1000/pulse/native',
                                'IIR_AEC_STATE': str(state)}
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'start'], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(state.exists())

    def _aec_env(self, state, pactl, systemctl=None):
        env = os.environ | {'IIR_PACTL': str(pactl),
                            'IIR_AEC_SOURCE_MASTER': 'mic',
                            'IIR_AEC_SINK_MASTER': 'speaker',
                            'IIR_AEC_CHECK_SECONDS': '0',
                            'PULSE_SERVER': 'unix:/run/user/1000/pulse/native',
                            'IIR_AEC_STATE': str(state)}
        if systemctl is not None:
            env['IIR_SYSTEMCTL'] = str(systemctl)
        return env

    def _fake_systemctl(self, directory):
        fake = Path(directory) / 'systemctl'
        fake.write_text('#!/usr/bin/env python3\n'
                        'import sys\n'
                        'print("systemctl", *sys.argv[1:], file=sys.stderr)\n')
        fake.chmod(0o755)
        return fake

    def test_aec_start_loads_module_when_none_is_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("1 mic")\n'
                            'elif args == ["list", "short", "sinks"]:\n'
                            '    print("2 speaker")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    pass\n'
                            'elif args[0] == "load-module":\n'
                            '    print(21)\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            # A stale id from before the module was unloaded must not be trusted.
            state.write_text('12\n')
            env = self._aec_env(state, fake)
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'start'], env=env,
                                    capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(state.read_text(), '21\n')

    def test_aec_start_reuses_live_module(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("1 mic\\n2 iir_aec_source")\n'
                            'elif args == ["list", "short", "sinks"]:\n'
                            '    print("2 speaker")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    print("12 module-echo-cancel source_name=iir_aec_source")\n'
                            'elif args[0] == "load-module":\n'
                            '    sys.exit(1)\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = self._aec_env(state, fake)
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'start'], env=env,
                                    capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(state.read_text(), '12\n')

    def test_aec_start_replaces_module_without_its_source(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("1 mic")\n'
                            'elif args == ["list", "short", "sinks"]:\n'
                            '    print("2 speaker")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    print("12 module-echo-cancel source_name=iir_aec_source")\n'
                            'elif args[0] == "unload-module":\n'
                            '    sys.exit(0)\n'
                            'elif args[0] == "load-module":\n'
                            '    print(33)\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = self._aec_env(state, fake)
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'start'], env=env,
                                    capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(state.read_text(), '33\n')

    def test_aec_stop_tolerates_vanished_module(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "modules"]:\n'
                            '    pass\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            state.write_text('12\n')
            env = self._aec_env(state, fake)
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'stop'], env=env,
                                    capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(state.exists())

    def test_aec_watch_restarts_asr_after_reloading_module(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("1 mic")\n'
                            'elif args == ["list", "short", "sinks"]:\n'
                            '    print("2 speaker")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    pass\n'
                            'elif args[0] == "load-module":\n'
                            '    print(44)\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = self._aec_env(state, fake, self._fake_systemctl(directory))
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'watch', '2'], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(state.read_text(), '44\n')
            # The module is new, so the running parec is on a source that no
            # longer exists: ASR must be restarted to reattach it.
            self.assertIn('restart iir-asr.service', result.stderr)

    def test_aec_watch_waits_for_second_bad_round_before_restarting(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("19 mic\\n31 iir_aec_source")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    print("12 module-echo-cancel source_name=iir_aec_source")\n'
                            'elif args == ["list", "short", "clients"]:\n'
                            '    print("160 protocol-native.c parec")\n'
                            'elif args == ["list", "short", "source-outputs"]:\n'
                            '    print("40 19 160 protocol-native.c s16le 1ch 16000Hz")\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = self._aec_env(state, fake, self._fake_systemctl(directory))
            one = subprocess.run([str(DEPLOY / 'aec.sh'), 'watch', '1'], env=env,
                                 capture_output=True, text=True)
            self.assertEqual(one.returncode, 0)
            # A single round is not enough: the stream may just be moving.
            self.assertNotIn('restart iir-asr', one.stderr)
            two = subprocess.run([str(DEPLOY / 'aec.sh'), 'watch', '2'], env=env,
                                 capture_output=True, text=True)
            self.assertEqual(two.returncode, 0)
            self.assertIn('restart iir-asr.service', two.stderr)

    def test_aec_watch_leaves_asr_alone_when_module_is_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("1 mic\\n2 iir_aec_source")\n'
                            'elif args == ["list", "short", "sinks"]:\n'
                            '    print("2 speaker")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    print("12 module-echo-cancel source_name=iir_aec_source")\n'
                            'elif args[0] == "load-module":\n'
                            '    sys.exit(1)\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = self._aec_env(state, fake, self._fake_systemctl(directory))
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'watch', '1'], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(state.read_text(), '12\n')
            self.assertNotIn('restart iir-asr', result.stderr)

    def test_aec_watch_keeps_going_when_master_source_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'pactl'
            fake.write_text('#!/usr/bin/env python3\n'
                            'import sys\n'
                            'args = sys.argv[1:]\n'
                            'if args == ["list", "short", "sources"]:\n'
                            '    print("9 other")\n'
                            'elif args == ["list", "short", "modules"]:\n'
                            '    pass\n'
                            'else:\n'
                            '    sys.exit(2)\n')
            fake.chmod(0o755)
            state = Path(directory) / 'aec-state'
            env = self._aec_env(state, fake, self._fake_systemctl(directory))
            result = subprocess.run([str(DEPLOY / 'aec.sh'), 'watch', '1'], env=env,
                                    capture_output=True, text=True)
            # A missing microphone must not kill the watchdog: the USB device
            # comes back and the next round repairs the path.
            self.assertEqual(result.returncode, 0)
            self.assertIn('master source or sink is missing', result.stderr)
            self.assertNotIn('restart iir-asr', result.stderr)
            self.assertFalse(state.exists())

    def test_mediamtx_config_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'media.json'
            env = os.environ | {'IIR_MEDIA_AUTH_SECRET': 'test-password',
                                'IIR_CAMERA_UPSTREAM': 'rtsp://127.0.0.1:9999/camera',
                                'IIR_MEDIAMTX_CONFIG': str(target)}
            subprocess.run(['python3', str(DEPLOY / 'mediamtx/render.py')], env=env, check=True)
            config = json.loads(target.read_text())
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config['webrtcAddress'], '127.0.0.1:8889')
            self.assertEqual(config['rtspAddress'], '127.0.0.1:8554')
            self.assertEqual(config['paths']['camera']['source'], env['IIR_CAMERA_UPSTREAM'])
            users = config['authInternalUsers']
            self.assertEqual(users[0]['ips'], ['127.0.0.1'])
            self.assertEqual(users[0]['permissions'], [
                {'action': 'publish', 'path': 'platform_voice'},
                {'action': 'read', 'path': 'robot_mic'},
                {'action': 'read', 'path': 'camera'}])
            self.assertEqual(users[1]['permissions'], [
                {'action': 'publish', 'path': 'robot_mic'},
                {'action': 'read', 'path': 'platform_voice'}])

    def test_udev_uses_selected_devices_and_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'udevadm'
            fake.write_text('#!/usr/bin/env python3\nimport sys\ndev=sys.argv[-1]\n'
                            'assert sys.argv[1:4] == ["info", "--query=property", "--name"]\n'
                            'print("DEVPATH=/devices/" + dev.rsplit("/", 1)[-1])\n'
                            'print("SUBSYSTEM=" + ("video4linux" if dev.endswith("camera") else "tty"))\n')
            fake.chmod(0o755)
            env = os.environ | {'PATH': directory + ':' + os.environ['PATH']}
            cmd = ['python3', str(DEPLOY / 'generate-udev.py'), '--chassis', '/dev/chassis',
                   '--lidar', '/dev/lidar', '--camera', '/dev/camera']
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), [
                'SUBSYSTEM=="tty", DEVPATH=="/devices/chassis", SYMLINK+="iir_chassis"',
                'SUBSYSTEM=="tty", DEVPATH=="/devices/lidar", SYMLINK+="iir_lidar"',
                'SUBSYSTEM=="video4linux", DEVPATH=="/devices/camera", SYMLINK+="iir_camera"'])
            cmd[5] = '/dev/chassis'
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_keywords_file_installs_on_fresh_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'models' / 'iir-keywords.txt'
            result = subprocess.run(['bash', str(DEPLOY / 'install-keywords.sh'),
                                     str(DEPLOY / 'kws/keywords.txt'), str(dest)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dest.read_bytes(), (DEPLOY / 'kws/keywords.txt').read_bytes())
            self.assertEqual(dest.stat().st_mode & 0o777, 0o644)

    def test_keywords_file_keeps_on_site_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'iir-keywords.txt'
            dest.write_text('x iǎo x ún @小巡\n')
            result = subprocess.run(['bash', str(DEPLOY / 'install-keywords.sh'),
                                     str(DEPLOY / 'kws/keywords.txt'), str(dest)],
                                    capture_output=True, text=True)
            # A reinstall must not silently revert on-site keyword tuning.
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dest.read_text(), 'x iǎo x ún @小巡\n')
            self.assertIn('Keeping existing keywords', result.stderr)

    def test_keywords_file_accepts_identical_target(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'iir-keywords.txt'
            dest.write_bytes((DEPLOY / 'kws/keywords.txt').read_bytes())
            result = subprocess.run(['bash', str(DEPLOY / 'install-keywords.sh'),
                                     str(DEPLOY / 'kws/keywords.txt'), str(dest)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('already current', result.stdout)

    def test_keywords_file_rejects_missing_or_empty_source(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / 'empty.txt'
            empty.write_text('')
            for source in (Path(directory) / 'absent.txt', empty):
                with self.subTest(source=source.name):
                    result = subprocess.run(['bash', str(DEPLOY / 'install-keywords.sh'),
                                             str(source), str(Path(directory) / 'out.txt')],
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((Path(directory) / 'out.txt').exists())

    def test_install_installs_keyword_file(self):
        script = (DEPLOY / 'install.sh').read_text()
        self.assertIn('install-keywords.sh', script)
        self.assertIn('kws/keywords.txt', script)

    def test_shipped_keywords_cover_observed_spellings(self):
        lines = [line.split() for line in
                 (DEPLOY / 'kws/keywords.txt').read_text().splitlines() if line.strip()]
        labels = [words[-1] for words in lines]
        # wake.py maps every label back to 小巡, so a new spelling must not
        # introduce a second wake name the ASR text path cannot match.
        self.assertTrue(all(label.startswith('@小巡') for label in labels), labels)
        self.assertIn('@小巡', labels)
        self.assertIn('@小巡小巡', labels)
        # 小能 is a distinct acoustic spelling (the ASR hears 小能小的意思);
        # 小寻/小群 are the same token sequence as 小巡 and need no line.
        self.assertIn(['x', 'iǎo', 'n', 'éng', '@小巡'], lines)

    def test_bridge_skips_cleanly_when_not_configured(self):
        # The legacy 8088 service owns the bridge role on the current board;
        # an empty IIR_WEB_BRIDGE must end the unit successfully, not failed.
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ | {'IIR_WEB_BRIDGE': '', 'HOME': directory}
            result = subprocess.run(['bash', str(DEPLOY / 'run-bridge.sh')], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('bridge disabled', result.stdout)

    def test_bridge_requires_ros_setup_when_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ | {'IIR_WEB_BRIDGE': str(Path(directory) / 'shim.py')}
            env.pop('IIR_ROS_SETUP', None)
            env.pop('IIR_ROS_WS_SETUP', None)
            result = subprocess.run(['bash', str(DEPLOY / 'run-bridge.sh')], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_audio_readiness_rejects_blocked_and_unavailable(self):
        script = r"""
import io, json, os, runpy, sys
from unittest.mock import patch
body = {'available': sys.argv[1] == 'true', 'blocked': None if sys.argv[2] == 'none' else 'failure',
        'owner': None, 'sos': False, 'sessions': {}}
os.environ['IIR_INTERACTION_TOKEN'] = 'token'
sys.argv = ['wait-ready.py', 'audio']
def response(request, timeout):
    assert request.get_header('Authorization') == 'Bearer token'
    return io.BytesIO(json.dumps(body).encode())
with patch('urllib.request.urlopen', response):
    runpy.run_path(os.environ['IIR_TEST_READY_SCRIPT'], run_name='__main__')
"""
        env = os.environ | {'IIR_TEST_READY_SCRIPT': str(DEPLOY / 'wait-ready.py')}
        for available, blocked, expected in [('true', 'none', True), ('true', 'failed', False), ('false', 'none', False)]:
            result = subprocess.run(['python3', '-c', script, available, blocked], env=env, capture_output=True)
            self.assertEqual(result.returncode == 0, expected)


if __name__ == '__main__':
    unittest.main()

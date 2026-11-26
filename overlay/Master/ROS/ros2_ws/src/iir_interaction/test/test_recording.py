"""Verify diagnostic audio preserves samples and private file permissions.
验证诊断录音保留采样与私有文件权限。
"""
from pathlib import Path
import tempfile
import unittest
import wave

from iir_interaction.asr import save_recording


class RecordingTests(unittest.TestCase):
    def test_saves_exact_pcm_with_unique_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            pcm = b'\x01\x00\xff\xff' * 160
            first = save_recording(directory, pcm)
            second = save_recording(directory, pcm)
            self.assertNotEqual(first, second)
            self.assertEqual(Path(first).stat().st_mode & 0o777, 0o600)
            with wave.open(first) as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
                self.assertEqual(wav.readframes(wav.getnframes()), pcm)

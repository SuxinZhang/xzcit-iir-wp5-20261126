"""Check the pre-roll handed to the keyword decoder around each VAD segment.
使用假 VAD 检查每个片段交给关键词解码器的前导音频。
"""
import io
import unittest

import numpy as np

from iir_interaction.asr import speech_segments

CHUNK = 512
CAP = int(0.3 * 16000)


class _Front:
    def __init__(self, samples, start):
        self.samples = samples
        self.start = start


class _FakeVad:
    """Queue one segment per (start, length, trigger) once trigger samples arrive.
    到达 trigger 个采样点后，按顺序交出 (start, length, trigger) 描述的片段。
    """

    def __init__(self, segments):
        self.pending = list(segments)
        self.ready = []
        self.accepted = 0

    def accept_waveform(self, samples):
        self.accepted += len(samples)
        while self.pending and self.accepted >= self.pending[0][2]:
            start, length, _ = self.pending.pop(0)
            self.ready.append(_Front(self.source[start:start + length], start))

    def empty(self):
        return not self.ready

    @property
    def front(self):
        return self.ready[0]

    def pop(self):
        self.ready.pop(0)


def _stream(count):
    """Deterministic int16 samples, converted the same way the capture loop does.
    生成确定的 int16 采样，并按采集循环相同的方式转换。
    """
    pcm = ((np.arange(count) * 37) % 20000 - 10000).astype('<i2')
    return pcm, pcm.astype(np.float32) / 32768.0


def _run(segments, count):
    pcm, floats = _stream(count)
    vad = _FakeVad(segments)
    vad.source = floats
    reader = io.BytesIO(pcm.tobytes())
    return speech_segments(reader, vad), floats


class PreRollTests(unittest.TestCase):
    def test_pre_roll_is_the_audio_before_the_segment_start(self):
        segments, floats = _run([(8000, 400, 8640)], 9000)
        segment, pre_roll = next(segments)
        self.assertTrue(np.array_equal(segment, floats[8000:8400]))
        self.assertTrue(np.array_equal(pre_roll, floats[8000 - CAP:8000]))

    def test_pre_roll_is_padded_when_the_previous_segment_is_close(self):
        segments, floats = _run([(5000, 1600, 7000), (8000, 400, 8640)], 9000)
        first, first_pre = next(segments)
        second, second_pre = next(segments)
        self.assertTrue(np.array_equal(first, floats[5000:6600]))
        self.assertTrue(np.array_equal(first_pre, floats[5000 - CAP:5000]))
        self.assertTrue(np.array_equal(second, floats[8000:8400]))
        # 6600 is where the previous segment ended, so only 1400 samples of real
        # audio precede the second segment; the rest is silence.  Replaying the
        # previous utterance instead would feed it to the decoder twice.
        # 6600 是上一片段结束处，第二片段前只有 1400 个真实采样，其余补静音。
        # 若改为回放上一句，就会把上一句重复送进解码器。
        self.assertTrue(np.array_equal(second_pre[-1400:], floats[6600:8000]))
        self.assertFalse(second_pre[:-1400].any())

    def test_pre_roll_keeps_a_constant_length(self):
        # The hit rate depends on where the phrase sits inside the decoded clip,
        # so a shorter lead for a later segment would move it into a worse spot.
        # 命中率取决于短语在解码片段中的位置，后出现的片段若前导更短，
        # 就会把短语挪到更不利的位置。
        segments, _ = _run([(8000, 400, 8640), (30000, 400, 31000)], 33000)
        _, first_pre = next(segments)
        _, second_pre = next(segments)
        self.assertEqual(len(first_pre), CAP)
        self.assertEqual(len(second_pre), CAP)

    def test_pre_roll_is_silence_once_the_start_has_been_dropped(self):
        # The segment is reported 4 s after its start, past the kept history.
        # 片段在起点之后 4 秒才报告，已超出保留的历史。
        segments, floats = _run([(4000, 400, 44000)], 46000)
        segment, pre_roll = next(segments)
        self.assertTrue(np.array_equal(segment, floats[4000:4400]))
        self.assertEqual(len(pre_roll), CAP)
        self.assertFalse(pre_roll.any())

    def test_stream_end_is_an_error(self):
        segments, _ = _run([], CHUNK * 3)
        with self.assertRaisesRegex(RuntimeError, 'parec audio stream ended'):
            next(segments)


if __name__ == '__main__':
    unittest.main()

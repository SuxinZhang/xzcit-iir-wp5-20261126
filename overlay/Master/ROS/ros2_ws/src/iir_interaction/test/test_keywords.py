"""Verify streaming keyword usage and deployed-model wake detection.
验证流式关键词调用方式以及已部署模型的唤醒检测。
"""
import os
import unittest
import wave


class FakeStream:
    def __init__(self):
        self.sample_rate = None
        self.samples = None
        self.finished = False

    def accept_waveform(self, sample_rate, samples):
        self.sample_rate = sample_rate
        self.samples = samples

    def input_finished(self):
        self.finished = True


class FakeSpotter:
    def __init__(self, results):
        self.results = list(results)
        self.created_with = []
        self.stream = None
        self.current = ''
        self.reset_calls = 0

    def create_stream(self, keywords=None):
        self.created_with.append(keywords)
        self.stream = FakeStream()
        return self.stream

    def is_ready(self, stream):
        return bool(self.results)

    def decode_stream(self, stream):
        self.current = self.results.pop(0)

    def get_result(self, stream):
        return self.current

    def reset_stream(self, stream):
        self.reset_calls += 1


class KeywordStreamingContractTests(unittest.TestCase):
    def test_segment_is_finished_with_tail_silence(self):
        import numpy as np
        from iir_interaction.keywords import (SAMPLE_RATE, TAIL_PADDING_SECONDS,
                                              detect_keyword)
        spotter = FakeSpotter(['小巡'])
        samples = np.ones(16000, dtype=np.float32)
        self.assertEqual(detect_keyword(spotter, samples), '小巡')

        stream = spotter.stream
        self.assertTrue(stream.finished)
        self.assertEqual(stream.sample_rate, SAMPLE_RATE)
        tail = int(TAIL_PADDING_SECONDS * SAMPLE_RATE)
        self.assertEqual(len(stream.samples), len(samples) + tail)
        self.assertTrue(np.all(stream.samples[:len(samples)] == 1.0))
        self.assertTrue(np.all(stream.samples[len(samples):] == 0.0))

    def test_hit_resets_the_stream_for_reuse(self):
        import numpy as np
        from iir_interaction.keywords import detect_keyword
        spotter = FakeSpotter(['小巡'])
        detect_keyword(spotter, np.zeros(16000, dtype=np.float32))
        self.assertEqual(spotter.reset_calls, 1)

    def test_empty_result_does_not_reset(self):
        import numpy as np
        from iir_interaction.keywords import detect_keyword
        spotter = FakeSpotter(['', ''])
        self.assertEqual(detect_keyword(spotter, np.zeros(16000, dtype=np.float32)), '')
        self.assertEqual(spotter.reset_calls, 0)

    def test_extra_keywords_are_passed_when_creating_a_stream(self):
        from iir_interaction.keywords import Spotter
        inner = FakeSpotter([''])
        spotter = Spotter(inner, 'x iǎo x ún @小巡')
        spotter.create_stream()
        self.assertEqual(inner.created_with, ['x iǎo x ún @小巡'])

    def test_no_extra_keywords_use_the_file_only(self):
        from iir_interaction.keywords import Spotter
        inner = FakeSpotter([''])
        spotter = Spotter(inner)
        spotter.create_stream()
        self.assertEqual(inner.created_with, [None])


@unittest.skipUnless(os.environ.get('IIR_KWS_TEST_POSITIVE'), 'requires board keyword model and WAV fixtures')
class KeywordTests(unittest.TestCase):
    def test_wake_audio_hits_but_command_speech_and_silence_do_not(self):
        import numpy as np
        from iir_interaction.keywords import create_spotter, detect_keyword
        spotter = create_spotter(os.environ)
        for variable, expected in [('IIR_KWS_TEST_POSITIVE', '小巡小巡'),
                                   ('IIR_KWS_TEST_NEGATIVE', ''),
                                   ('IIR_KWS_TEST_COMMAND', '')]:
            with self.subTest(variable=variable):
                with wave.open(os.environ[variable]) as wav:
                    samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
                self.assertEqual(detect_keyword(spotter, samples), expected)
        self.assertEqual(detect_keyword(spotter, np.zeros(32000, dtype=np.float32)), '')


if __name__ == '__main__':
    unittest.main()

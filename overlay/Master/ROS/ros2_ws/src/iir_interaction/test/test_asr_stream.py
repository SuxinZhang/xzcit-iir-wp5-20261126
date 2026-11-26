"""Check real VAD segmentation with the deployed model and audio fixture.
使用已部署模型与音频样本检查真实 VAD 分段。
"""
import io
import os
import unittest
import wave


@unittest.skipUnless(os.environ.get('IIR_ASR_TEST_WAV'), 'requires board VAD model and WAV fixture')
class SpeechSegmentTests(unittest.TestCase):
    def test_phrase_crossing_old_three_second_boundary_stays_in_one_segment(self):
        import numpy as np
        import sherpa_onnx
        from iir_interaction.asr import speech_segments
        with wave.open(os.environ['IIR_ASR_TEST_WAV']) as wav:
            self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2))
            phrase = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
        config = sherpa_onnx.VadModelConfig()
        config.sample_rate = 16000
        config.silero_vad.model = os.environ['IIR_ASR_VAD_MODEL']
        config.silero_vad.min_silence_duration = 0.3
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        audio = np.concatenate([np.zeros(40000, dtype='<i2'), phrase, np.zeros(16000, dtype='<i2')])
        reader = io.BytesIO(audio.astype('<i2').tobytes())
        segment, pre_roll = next(speech_segments(reader, vad))
        self.assertGreater(len(segment), len(phrase) * 0.75)
        self.assertLess(reader.tell() / 32000, 2.5 + len(phrase) / 16000 + 0.7)
        # The keyword decoder needs the audio just before the VAD's own start
        # mark, because a single wake word stops matching without its onset.
        # The lead is a constant length so the phrase keeps the same position in
        # the decoded clip no matter how much history is still buffered.
        # 关键词解码需要 VAD 起点之前的音频，否则单次唤醒词会因缺失起音而不命中。
        # 前导长度恒定，使短语在解码片段中的位置不随缓冲历史变化。
        self.assertEqual(len(pre_roll), int(0.3 * 16000))
        with self.assertRaisesRegex(RuntimeError, 'parec audio stream ended'):
            next(speech_segments(reader, vad))

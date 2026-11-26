"""Probe how much acoustic wake evidence the missed segments actually carry.

The point is to separate two very different causes of a missed wake: the audio
contains the phrase but the score fell short, or the phrase is not in the
segment at all (wrong VAD boundary).  Only the first can be fixed by tuning.
One spotter per threshold, reused across files, keeps this inside a minute.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
FOCUS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
THRESHOLDS = (0.25, 0.05, 0.005)


def load(path):
    with wave.open(path, 'rb') as wav:
        rate = wav.getframerate()
        frames = wav.getnframes()
        data = wav.readframes(frames)
    return np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0, rate, frames


def make(threshold):
    return sherpa_onnx.KeywordSpotter(
        tokens=MODEL + '/tokens.txt',
        encoder=MODEL + '/encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx',
        decoder=MODEL + '/decoder-epoch-13-avg-2-chunk-8-left-64.onnx',
        joiner=MODEL + '/joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx',
        keywords_file=KEYWORDS,
        num_threads=2, max_active_paths=8,
        keywords_score=1.0, keywords_threshold=threshold,
        num_trailing_blanks=1, provider='cpu')


def detect(spotter, samples):
    stream = spotter.create_stream()
    stream.accept_waveform(16000, samples)
    stream.accept_waveform(16000, np.zeros(10560, dtype=np.float32))
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        result = spotter.get_result(stream)
        if result:
            return True
        # no reset needed: only existence of any hit matters here
    return False


def main():
    spotters = [(threshold, make(threshold)) for threshold in THRESHOLDS]
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        samples, rate, frames = load(path)
        fires = [threshold for threshold, spotter in spotters
                 if detect(spotter, samples)]
        tag = 'FOCUS' if name in FOCUS else '     '
        print(f'{tag} {name} dur={frames / rate:5.2f}s '
              f'fires_at={fires if fires else "never"}', flush=True)


if __name__ == '__main__':
    main()

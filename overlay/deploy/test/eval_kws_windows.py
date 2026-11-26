"""Slide a window over the two silent wake attempts looking for a clean match.

Both segments stay silent even at threshold 0.005, which means no decode step
ever completes the keyword path.  A sliding window separates "the phrase is
there but split across a pause" from "the phrase is not recognisable at all".
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
MISSES = ('56761Z', '42949Z')
WINDOW = 16000      # 1.0 s
HOP = 4000          # 0.25 s
PAD = np.zeros(10560, dtype=np.float32)


def load(path):
    with wave.open(path, 'rb') as wav:
        data = wav.readframes(wav.getnframes())
    return np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0


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
    stream.accept_waveform(16000, PAD)
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        if spotter.get_result(stream):
            return True
    return False


def main():
    spotter = make(0.05)
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        if name not in MISSES:
            continue
        samples = load(path)
        hits = []
        for start in range(0, max(1, len(samples) - WINDOW + 1), HOP):
            if detect(spotter, samples[start:start + WINDOW]):
                hits.append(f'{start / 16000:.2f}-'
                            f'{(start + WINDOW) / 16000:.2f}s')
        print(f'{name} dur={len(samples) / 16000:.2f}s '
              f'windows={hits if hits else "none"}', flush=True)


if __name__ == '__main__':
    main()

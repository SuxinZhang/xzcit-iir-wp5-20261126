"""Measure how much leading audio the keyword model needs to fire.

The VAD only starts a segment once speech is detected, so the first tens of
milliseconds of the wake word may never reach the spotter.  Trimming a known
hit from the front shows how much onset loss the match tolerates; if it dies
after 100 ms, a leading pre-roll is worth more than any threshold change.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
HITS = ('91500Z', '20034Z', '75094Z')
TRIMS_MS = (0, 50, 100, 150, 200, 300, 400, 500)
PAD = np.zeros(10560, dtype=np.float32)


def load(path):
    with wave.open(path, 'rb') as wav:
        data = wav.readframes(wav.getnframes())
    return np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0


def make():
    return sherpa_onnx.KeywordSpotter(
        tokens=MODEL + '/tokens.txt',
        encoder=MODEL + '/encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx',
        decoder=MODEL + '/decoder-epoch-13-avg-2-chunk-8-left-64.onnx',
        joiner=MODEL + '/joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx',
        keywords_file=KEYWORDS,
        num_threads=2, max_active_paths=8,
        keywords_score=1.0, keywords_threshold=0.25,
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
    spotter = make()
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        if name not in HITS:
            continue
        samples = load(path)
        results = []
        for trim in TRIMS_MS:
            cut = trim * 16
            results.append(f'{trim}:{"Y" if detect(spotter, samples[cut:]) else "n"}')
        print(f'{name} ' + ' '.join(results), flush=True)


if __name__ == '__main__':
    main()

"""Score KWS configs on real wake attempts vs ordinary-speech segments.

Run on the board with the venv interpreter.  The positive set is the five
recordings whose ASR transcript shows the speaker actually said the wake
word; the remaining sixteen are ordinary conversation and must stay silent.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}


def load(path):
    with wave.open(path, 'rb') as wav:
        rate = wav.getframerate()
        data = wav.readframes(wav.getnframes())
    return np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0, rate


def make(score, threshold, paths, blanks):
    return sherpa_onnx.KeywordSpotter(
        tokens=MODEL + '/tokens.txt',
        encoder=MODEL + '/encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx',
        decoder=MODEL + '/decoder-epoch-13-avg-2-chunk-8-left-64.onnx',
        joiner=MODEL + '/joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx',
        keywords_file=KEYWORDS,
        num_threads=2, max_active_paths=paths,
        keywords_score=score, keywords_threshold=threshold,
        num_trailing_blanks=blanks, provider='cpu')


def detect(spotter, samples):
    stream = spotter.create_stream()
    stream.accept_waveform(16000, samples)
    stream.accept_waveform(16000, np.zeros(10560, dtype=np.float32))
    stream.input_finished()
    hits = []
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        result = spotter.get_result(stream)
        if result:
            hits.append(result)
            spotter.reset_stream(stream)
    return hits


def main():
    audio = []
    for path in sorted(glob.glob(REC + '/*.wav')):
        samples, rate = load(path)
        assert rate == 16000, rate
        # The timestamp prefix is fixed width, so the seconds field is the
        # stable short label used by the baseline scorer.
        audio.append((os.path.basename(path)[17:23], samples))

    configs = (
        ('current', 1.0, 0.25, 8, 1),
        ('thr.20', 1.0, 0.20, 8, 1),
        ('thr.15', 1.0, 0.15, 8, 1),
        ('thr.10', 1.0, 0.10, 8, 1),
        ('score.5', 0.5, 0.15, 8, 1),
        ('score.5-t.20', 0.5, 0.20, 8, 1),
        ('paths16', 1.0, 0.15, 16, 1),
        ('blanks0', 1.0, 0.15, 8, 0),
    )
    for label, score, threshold, paths, blanks in configs:
        spotter = make(score, threshold, paths, blanks)
        tp = fp = 0
        missed = []
        false = []
        for name, samples in audio:
            hit = bool(detect(spotter, samples))
            if name in POS:
                tp += hit
                if not hit:
                    missed.append(name)
            elif hit:
                fp += 1
                false.append(name)
        print(f'{label:12} recall={tp}/5  false={fp}/16  '
              f'missed={missed} falsepos={false}')


if __name__ == '__main__':
    main()

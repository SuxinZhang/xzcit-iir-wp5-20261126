"""Measure the pre-roll now handed to the keyword decoder before each segment.

The deployed path calls detect_keyword(concat(pre_roll, segment)).  The saved
recordings are already VAD segments, so the audio before their onset is not in
the files; a fixed lead of silence reproduces the live call and shows whether
the extra lead changes any decision.  0.1 s is the smallest lead that covers the
worst observed VAD lag (46 ms), 0.3 s is what the code ships.
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
    stream.accept_waveform(16000, np.concatenate([samples, PAD]))
    stream.input_finished()
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        keyword = spotter.get_result(stream)
        if keyword:
            spotter.reset_stream(stream)
            return keyword
    return ''


def main():
    audio = [(os.path.basename(path)[17:23], load(path))
             for path in sorted(glob.glob(REC + '/*.wav'))]
    for threshold in (0.25, 0.15):
        spotter = make(threshold)
        for lead_seconds in (0.0, 0.1, 0.3):
            lead = np.zeros(int(lead_seconds * 16000), dtype=np.float32)
            tp = fp = 0
            missed = []
            false = []
            detail = []
            for name, samples in audio:
                keyword = detect(spotter, np.concatenate([lead, samples]))
                if name in POS:
                    tp += bool(keyword)
                    if not keyword:
                        missed.append(name)
                    else:
                        detail.append(f'{name}={keyword}')
                elif keyword:
                    fp += 1
                    false.append(name)
            print(f'lead={lead_seconds:.1f}s t={threshold} recall={tp}/5 '
                  f'false={fp}/16 missed={missed} falsepos={false} '
                  f'hits={detail}', flush=True)


if __name__ == '__main__':
    main()

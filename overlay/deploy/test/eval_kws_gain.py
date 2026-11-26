"""Test whether gain normalisation recovers the two missed wake words.

A single "小巡" is short and its energy is concentrated in a narrow band, so if
the recorded segment is much quieter than the ones that hit, the decoder sees a
different dynamic range than it was tuned for.  This prints level statistics for
every recording and then re-runs the keyword decoder after scaling each clip to
a fixed peak, to separate "too quiet" from "wrong audio".
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
LEAD = np.zeros(4800, dtype=np.float32)


def load(path):
    with wave.open(path, 'rb') as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()),
                             dtype='<i2').astype(np.float32) / 32768.0


def make(threshold=0.25):
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
            return keyword
    return ''


def level(audio):
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    db = 20 * np.log10(max(rms, 1e-9))
    return peak, db


def main():
    spotter = make()
    files = sorted(glob.glob(os.path.join(REC, '*.wav')))
    clips = [(os.path.basename(path)[17:23], load(path)) for path in files]
    for name, audio in clips:
        peak, db = level(audio)
        print('%s %s dur=%.2fs peak=%.3f rms=%.1fdB' % (
            name, 'P' if name in POS else '-', len(audio) / 16000, peak, db), flush=True)
    print('-- peak normalisation to 0.9 --', flush=True)
    for target in (0.3, 0.6, 0.9):
        hits = []
        for name, audio in clips:
            peak = float(np.max(np.abs(audio)))
            scaled = audio * (target / peak) if peak > 0 else audio
            if detect(spotter, np.concatenate([LEAD, scaled])):
                hits.append(name)
        missed = sorted(POS - set(hits))
        false = sorted(set(hits) - POS)
        print('peak=%.1f recall=%d/5 false=%d/16 missed=%s falsepos=%s' % (
            target, len(POS) - len(missed), len(false), missed, false), flush=True)


if __name__ == '__main__':
    main()

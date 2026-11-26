"""Compare segment-fed and stream-fed KWS on the real recordings.

The recordings are already VAD segments, so they cannot show the recall a raw
stream would recover; what they *can* show is the false-alarm cost of decoding
continuously instead of one segment at a time.  Concatenating every file with
one second of silence reproduces the production stream shape, and the hit
position says which recording triggered it.
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
CHUNK = 512
GAP = 16000
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


def segment_hits(spotter, samples):
    stream = spotter.create_stream()
    stream.accept_waveform(16000, np.concatenate([samples, PAD]))
    stream.input_finished()
    hits = []
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        keyword = spotter.get_result(stream)
        if keyword:
            hits.append(keyword)
            spotter.reset_stream(stream)
    return hits


def continuous_hits(spotter, samples):
    """Feed the whole timeline as 512-sample chunks, as parec would deliver it."""
    stream = spotter.create_stream()
    hits = []
    for start in range(0, len(samples) - CHUNK + 1, CHUNK):
        stream.accept_waveform(16000, samples[start:start + CHUNK])
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            keyword = spotter.get_result(stream)
            if keyword:
                hits.append((start + CHUNK, keyword))
                spotter.reset_stream(stream)
    return hits


def main():
    audio = [(os.path.basename(path)[17:23], load(path))
             for path in sorted(glob.glob(REC + '/*.wav'))]

    for threshold in (0.25, 0.15):
        spotter = make(threshold)
        tp = fp = 0
        missed = []
        false = []
        for name, samples in audio:
            hit = bool(segment_hits(spotter, samples))
            if name in POS:
                tp += hit
                if not hit:
                    missed.append(name)
            elif hit:
                fp += 1
                false.append(name)
        print(f'segment  t={threshold} recall={tp}/5 false={fp}/16 '
              f'missed={missed} falsepos={false}', flush=True)

        timeline = []
        spans = []
        position = 0
        for name, samples in audio:
            start = position
            timeline.append(samples)
            position += len(samples)
            spans.append((start, position, name))
            timeline.append(np.zeros(GAP, dtype=np.float32))
            position += GAP
        timeline = np.concatenate(timeline)
        hits = continuous_hits(spotter, timeline)
        hit_names = []
        for end, _ in hits:
            for start, stop, name in spans:
                if start <= end <= stop + GAP // 2:
                    hit_names.append(name)
                    break
            else:
                hit_names.append(f'@{end / 16000:.1f}s')
        got = [name for name in hit_names if name in POS]
        extra = [name for name in hit_names if name not in POS]
        print(f'stream   t={threshold} recall={len(set(got))}/5 '
              f'false={len(extra)}/16 hits={hit_names}', flush=True)


if __name__ == '__main__':
    main()

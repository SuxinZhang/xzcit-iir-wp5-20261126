"""Check that the keyword model fires on a live 512-sample stream.

The deployed path pads each VAD segment with 0.66 s of silence and calls
input_finished(), which only exists for offline clips.  A continuous stream
never gets either, so this confirms a hit still arrives from
num_trailing_blanks alone, and measures how many chunks after the phrase it
lands.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
FOCUS = ('91500Z', '56761Z', '42949Z', '20034Z', '75094Z')
CHUNK = 512


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


def stream_detect(spotter, samples):
    stream = spotter.create_stream()
    hits = []
    for start in range(0, len(samples) - CHUNK + 1, CHUNK):
        stream.accept_waveform(16000, samples[start:start + CHUNK])
        while spotter.is_ready(stream):
            spotter.decode_stream(stream)
            keyword = spotter.get_result(stream)
            if keyword:
                hits.append((round((start + CHUNK) / 16000, 2), keyword))
                spotter.reset_stream(stream)
    return hits


def main():
    spotter = make()
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        if name not in FOCUS:
            continue
        samples = load(path)
        hits = stream_detect(spotter, samples)
        print(f'{name} dur={len(samples) / 16000:.2f}s '
              f'hits={hits if hits else "none"}', flush=True)


if __name__ == '__main__':
    main()

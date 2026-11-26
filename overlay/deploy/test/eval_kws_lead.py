"""Sweep the length of the silence lead handed to the keyword decoder.

The shipped code prepends up to 0.3 s of pre-roll to every VAD segment.  That
shifts the phrase inside the decoded clip, and 0.1 s already flipped one
recording from hit to miss, so the lead cannot be assumed harmless.  This prints
recall and false positives for a range of leads to show where the stable region
is, and covers the lags the VAD was actually observed to produce (0 to 66 ms).
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
LEADS = (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4)


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
            spotter.reset_stream(stream)
            return keyword
    return ''


def main():
    audio = [(os.path.basename(path)[17:23], load(path))
             for path in sorted(glob.glob(REC + '/*.wav'))]
    spotter = make()
    for lead_seconds in LEADS:
        lead = np.zeros(int(lead_seconds * 16000), dtype=np.float32)
        hits = [name for name, samples in audio
                if detect(spotter, np.concatenate([lead, samples]))]
        missed = sorted(POS - set(hits))
        false = sorted(set(hits) - POS)
        print(f'lead={lead_seconds:.2f}s recall={len(POS) - len(missed)}/5 '
              f'false={len(false)}/16 missed={missed} falsepos={false}',
              flush=True)


if __name__ == '__main__':
    main()

"""Check whether retrying the keyword decoder at another offset recovers misses.

Hit/miss for a single "小巡" flips with where the phrase sits inside the decoded
clip, so one decode at one offset is a coin toss for marginal recordings.  If a
second pass at a different lead recovers a miss, the production path can retry
only after a miss and get the recall without paying the cost on every segment.

Prints, for every recording, which leads hit, then the best union over pairs of
leads (recall on the 5 positives, false positives on the 16 negatives) and the
added decode cost of a second pass.
"""
import glob
import os
import time
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
PAD = np.zeros(10560, dtype=np.float32)
LEADS = (0.0, 0.05, 0.15, 0.2, 0.3, 0.4)


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


def main():
    spotter = make()
    files = sorted(glob.glob(os.path.join(REC, '*.wav')))
    rows = []
    for path in files:
        name = os.path.basename(path)[17:23]
        audio = load(path)
        hits = []
        ms = []
        for lead in LEADS:
            samples = np.concatenate([np.zeros(int(lead * 16000), dtype=np.float32), audio])
            started = time.monotonic()
            keyword = detect(spotter, samples)
            ms.append((time.monotonic() - started) * 1000)
            hits.append(bool(keyword))
        rows.append((name, hits, sum(ms) / len(ms)))
        print('%s %s %s' % (name, 'P' if name in POS else '-',
                            ''.join('1' if h else '0' for h in hits)), flush=True)
    print('leads %s' % ' '.join('%.2f' % lead for lead in LEADS), flush=True)
    for index, lead in enumerate(LEADS):
        pos = sum(1 for name, hits, _ in rows if name in POS and hits[index])
        false = sum(1 for name, hits, _ in rows if name not in POS and hits[index])
        print('lead=%.2f recall=%d/5 false=%d/16' % (lead, pos, false), flush=True)
    print('-- pairs: first pass at 0.30 (production), retry at the second lead --', flush=True)
    first = LEADS.index(0.3)
    for index, lead in enumerate(LEADS):
        if index == first:
            continue
        pos = sum(1 for name, hits, _ in rows
                  if name in POS and (hits[first] or hits[index]))
        false = sum(1 for name, hits, _ in rows
                    if name not in POS and (hits[first] or hits[index]))
        print('0.30+%.2f recall=%d/5 false=%d/16' % (lead, pos, false), flush=True)
    cost = sum(ms for _, _, ms in rows) / len(rows)
    print('mean decode ms per pass %.0f' % cost, flush=True)


if __name__ == '__main__':
    main()

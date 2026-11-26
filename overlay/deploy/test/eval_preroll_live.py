"""Score the keyword decoder with and without the audio before a VAD segment.

Each recording is embedded in 1 s of silence so the real VAD has to find its
onset exactly as it does live.  The loop mirrors the shipped speech_segments():
the VAD's own start mark locates the pre-roll, and only the keyword decoder sees
it.  Reported per segment: how far the VAD start landed from the true onset, the
pre-roll length, whether pre-roll + segment rejoins the original audio, and the
keyword found with and without the pre-roll.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
VAD_MODEL = '/home/orangepi/iir-wp5/models/silero_vad.onnx'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
KEYWORDS = MODEL + '/iir-keywords.txt'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
LEAD = 16000
CAP = int(0.3 * 16000)
CHUNK = 512
PAD = np.zeros(10560, dtype=np.float32)


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


def offset_of(haystack, needle):
    """First sample index where needle appears in haystack, or -1.
    返回 needle 在 haystack 中首次出现的采样下标，找不到时为 -1。
    """
    if len(needle) < CHUNK:
        return -1
    # VAD copies samples verbatim, so the int16 round trip is exact.
    # VAD 原样拷贝采样，int16 往返转换是精确的。
    hay = (haystack * 32768).astype('<i2').tobytes()
    head = (needle[:CHUNK] * 32768).astype('<i2').tobytes()
    index = hay.find(head)
    return -1 if index < 0 else index // 2


def segments_of(timeline):
    """Yield (segment, pre_roll, vad_start) the way the service does.
    按服务端相同的方式返回 (片段, 前导, VAD 起点)。
    """
    config = sherpa_onnx.VadModelConfig()
    config.sample_rate = 16000
    config.silero_vad.model = VAD_MODEL
    config.silero_vad.min_silence_duration = 0.4
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
    last_end = 0
    for index in range(0, len(timeline) - CHUNK + 1, CHUNK):
        vad.accept_waveform(timeline[index:index + CHUNK])
        while not vad.empty():
            front = vad.front
            samples = np.array(front.samples, dtype=np.float32, copy=True)
            start = front.start
            vad.pop()
            begin = max(last_end, start - CAP)
            pre_roll = (timeline[begin:start] if start > begin
                        else np.zeros(0, dtype=np.float32))
            yield samples, pre_roll, start
            last_end = max(last_end, start + len(samples))


def main():
    spotter = make()
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        if name not in POS:
            continue
        mono = load(path)
        timeline = np.concatenate([np.zeros(LEAD, dtype=np.float32), mono,
                                   np.zeros(16000, dtype=np.float32)])
        for segment, pre_roll, start in segments_of(timeline):
            joined = np.concatenate([pre_roll, segment])
            rejoined = offset_of(timeline, joined)
            print(f'{name} vad_start={start} lag_ms={(start - LEAD) / 16:+.0f} '
                  f'pre_roll={len(pre_roll)} rejoin={rejoined} '
                  f'bare={detect(spotter, segment) or "-"} '
                  f'joined={detect(spotter, joined) or "-"}', flush=True)


if __name__ == '__main__':
    main()

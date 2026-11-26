"""Measure how much of the wake word's onset the VAD discards.

The live ASR runs the keyword spotter on VAD segments only, so any audio the
VAD drops from the front of an utterance never reaches the spotter.  Padding a
known-good segment with silence and pushing it through the same VAD config
shows exactly where the emitted segment starts relative to the original audio.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
VAD_MODEL = '/home/orangepi/iir-wp5/models/silero_vad.onnx'
FOCUS = ('91500Z', '56761Z', '42949Z', '20034Z', '75094Z')
LEAD = 9600   # 0.6 s of silence before the utterance
CHUNK = 512


def load(path):
    with wave.open(path, 'rb') as wav:
        data = wav.readframes(wav.getnframes())
    return np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0


def make_vad():
    config = sherpa_onnx.VadModelConfig()
    config.sample_rate = 16000
    config.silero_vad.model = VAD_MODEL
    config.silero_vad.min_silence_duration = 0.4
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)


def run(samples):
    vad = make_vad()
    segments = []
    for start in range(0, len(samples) - CHUNK + 1, CHUNK):
        vad.accept_waveform(samples[start:start + CHUNK])
        while not vad.empty():
            segments.append(np.array(vad.front.samples, dtype=np.float32, copy=True))
            vad.pop()
    return segments


def offset_of(haystack, needle):
    # VAD copies samples verbatim; the int16 round trip is exact because the
    # conversion divides and multiplies by 32768, a power of two.
    hay = (haystack * 32768).astype('<i2').tobytes()
    head = (needle[:CHUNK] * 32768).astype('<i2').tobytes()
    index = hay.find(head)
    return -1 if index < 0 else index // 2


def main():
    for path in sorted(glob.glob(REC + '/*.wav')):
        name = os.path.basename(path)[17:23]
        if name not in FOCUS:
            continue
        speech = load(path)
        padded = np.concatenate([np.zeros(LEAD, dtype=np.float32), speech,
                                 np.zeros(LEAD, dtype=np.float32)])
        segments = run(padded)
        report = []
        for segment in segments:
            start = offset_of(padded, segment)
            if start < 0:
                report.append(f'len={len(segment) / 16000:.2f}s ?')
            else:
                lead = (start - LEAD) / 16000.0
                report.append(f'len={len(segment) / 16000:.2f}s '
                              f'lead={lead * 1000:+.0f}ms')
        print(f'{name} src={len(speech) / 16000:.2f}s n={len(segments)} '
              + ' '.join(report), flush=True)


if __name__ == '__main__':
    main()

"""Transcribe every saved wake segment to establish the real denominator.

The wake rate is only meaningful if the recordings actually contain the wake
word.  This runs the same offline recognizer the service uses over all saved
segments and prints the text, so a segment that was labelled positive but holds
no "小巡" can be excluded from the denominator instead of counted as a KWS miss.
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

MODEL = '/home/orangepi/iir-wp5/models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'
REC = '/home/orangepi/iir-wp5/state/wake-recordings'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}


def load(path):
    with wave.open(path, 'rb') as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()),
                             dtype='<i2').astype(np.float32) / 32768.0


def main():
    env = {}
    with open('/home/orangepi/.config/iir/wp5.env') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=env['IIR_ASR_ENCODER'], decoder=env['IIR_ASR_DECODER'],
        joiner=env['IIR_ASR_JOINER'], tokens=env['IIR_ASR_TOKENS'],
        num_threads=2, sample_rate=16000, feature_dim=80)
    for path in sorted(glob.glob(os.path.join(REC, '*.wav'))):
        name = os.path.basename(path)[17:23]
        audio = load(path)
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, audio)
        recognizer.decode_stream(stream)
        text = stream.result.text.replace(' ', '')
        print('%s %s %s' % (name, 'P' if name in POS else '-', text), flush=True)


if __name__ == '__main__':
    main()

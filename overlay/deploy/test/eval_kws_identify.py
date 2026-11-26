"""Ask the KWS acoustic model what the last missed clip actually sounds like.

56761Z is transcribed as 小寻小声, and no spelling of 小巡/小群/小能 recovers it
acoustically, so either the audio holds a different phrase or the keyword file
lacks its spelling.  Guessing spellings is slow, so this loads the same KWS
model files as an open-vocabulary streaming transducer and prints the text it
hears.  That separates "wrong keyword spelling" from "not a wake attempt".
"""
import glob
import os
import wave

import numpy as np
import sherpa_onnx

REC = '/home/orangepi/iir-wp5/state/wake-recordings'
POS = {'91500Z', '56761Z', '42949Z', '20034Z', '75094Z'}
TARGETS = ('56761Z', '42949Z')


def load(path):
    with wave.open(path, 'rb') as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()),
                             dtype='<i2').astype(np.float32) / 32768.0


def env_of():
    env = {}
    with open('/home/orangepi/.config/iir/wp5.env') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def main():
    env = env_of()
    recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=env['IIR_KWS_TOKENS'], encoder=env['IIR_KWS_ENCODER'],
        decoder=env['IIR_KWS_DECODER'], joiner=env['IIR_KWS_JOINER'],
        num_threads=2, sample_rate=16000, feature_dim=80,
        decoding_method='greedy_search')
    for path in sorted(glob.glob(os.path.join(REC, '*.wav'))):
        name = os.path.basename(path)[17:23]
        if name not in TARGETS:
            continue
        audio = load(path)
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, np.concatenate(
            [audio, np.zeros(10560, dtype=np.float32)]))
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text = recognizer.get_result(stream).replace(' ', '')
        print('%s %s dur=%.2fs open-vocab=%s codepoints=%s' % (
            name, 'P' if name in POS else '-', len(audio) / 16000.0, text,
            ' '.join('%04x' % ord(ch) for ch in text)), flush=True)


if __name__ == '__main__':
    main()
